from __future__ import annotations

import concurrent.futures
import ipaddress
import json
import logging
import re
import socket
import sqlite3
import time
import os
from functools import lru_cache
from collections import defaultdict
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
SETTINGS = json.loads((ROOT / "config/settings.json").read_text(encoding="utf-8"))
DB_PATH = REPO / SETTINGS["database"]
OUT_DIR = REPO / SETTINGS["output_dir"]
SEEDS = ROOT / "config/seeds.txt"
UA = "Mozilla/5.0 (compatible; PublicStreamResearch/1.0)"
SESSION = requests.Session()
retry = Retry(total=3, connect=3, read=2, status=3, backoff_factor=1.0,
              status_forcelist=(429, 500, 502, 503, 504),
              allowed_methods=frozenset(["GET"]), respect_retry_after_header=True)
adapter = HTTPAdapter(max_retries=retry, pool_connections=SETTINGS["max_workers"],
                      pool_maxsize=SETTINGS["max_workers"])
SESSION.mount("http://", adapter)
SESSION.mount("https://", adapter)
SESSION.headers.update({"User-Agent": UA, "Accept": "*/*"})
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

def connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DB_PATH)
    db.execute("PRAGMA journal_mode=WAL")
    db.executescript("""
    CREATE TABLE IF NOT EXISTS sources(
      url TEXT PRIMARY KEY, discovered_from TEXT, depth INTEGER DEFAULT 0,
      last_seen TEXT DEFAULT CURRENT_TIMESTAMP, last_checked TEXT, status TEXT DEFAULT 'new',
      http_status INTEGER, last_error TEXT, entries_found INTEGER DEFAULT 0,
      stream_candidates INTEGER DEFAULT 0
    );
    CREATE TABLE IF NOT EXISTS channels(
      id INTEGER PRIMARY KEY, name TEXT NOT NULL, tvg_id TEXT, logo TEXT,
      category TEXT, normalized_name TEXT, UNIQUE(normalized_name, category)
    );
    CREATE TABLE IF NOT EXISTS links(
      id INTEGER PRIMARY KEY, channel_id INTEGER NOT NULL, url TEXT NOT NULL UNIQUE,
      source_url TEXT, source_name TEXT, first_seen TEXT DEFAULT CURRENT_TIMESTAMP,
      last_seen TEXT DEFAULT CURRENT_TIMESTAMP, status TEXT DEFAULT 'new',
      http_status INTEGER, ttfb REAL, total_seconds REAL, bytes_per_second REAL,
      segment_ok INTEGER DEFAULT 0, error TEXT, last_checked TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_links_channel ON links(channel_id);
    CREATE TABLE IF NOT EXISTS candidate_streams(
      url TEXT PRIMARY KEY, source_url TEXT NOT NULL, discovered_at TEXT DEFAULT CURRENT_TIMESTAMP,
      status TEXT DEFAULT 'candidate', notes TEXT
    );
    """)
    # Migrate registries created by earlier runs before last_checked was added.
    columns = {row[1] for row in db.execute("PRAGMA table_info(links)")}
    if "last_checked" not in columns:
        db.execute("ALTER TABLE links ADD COLUMN last_checked TEXT")
    source_columns = {row[1] for row in db.execute("PRAGMA table_info(sources)")}
    for column, definition in (
        ("last_checked", "TEXT"),
        ("http_status", "INTEGER"),
        ("last_error", "TEXT"),
        ("entries_found", "INTEGER DEFAULT 0"),
        ("stream_candidates", "INTEGER DEFAULT 0"),
    ):
        if column not in source_columns:
            db.execute(f"ALTER TABLE sources ADD COLUMN {column} {definition}")
    # Keep per-source EPG metadata with each stream so later recategorization
    # does not lose group-title, country, language, or tvg identifiers.
    link_columns = {row[1] for row in db.execute("PRAGMA table_info(links)")}
    for column, definition in (
        ("group_title", "TEXT DEFAULT ''"),
        ("country", "TEXT DEFAULT ''"),
        ("language", "TEXT DEFAULT ''"),
        ("tvg_id", "TEXT DEFAULT ''"),
        ("logo", "TEXT DEFAULT ''"),
    ):
        if column not in link_columns:
            db.execute(f"ALTER TABLE links ADD COLUMN {column} {definition}")
    db.commit()
    return db

def canonical_url(url):
    return url.strip().replace("&amp;", "&")

@lru_cache(maxsize=8192)
def public_host_resolves_globally(host):
    if host in ("localhost", "localhost.localdomain") or host.endswith((".local", ".internal", ".localhost")):
        return False
    try:
        address = ipaddress.ip_address(host)
        return address.is_global
    except ValueError:
        pass
    try:
        resolved = {item[4][0].split("%", 1)[0] for item in socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)}
        return bool(resolved) and all(ipaddress.ip_address(value).is_global for value in resolved)
    except (OSError, ValueError):
        return False


def is_public_candidate(url):
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or parsed.username or parsed.password or not parsed.hostname:
        return False
    host = parsed.hostname.lower().rstrip(".")
    if not public_host_resolves_globally(host):
        return False
    # Never publish credential-bearing or expiring signed URLs to this public repository.
    sensitive = r"[?&](?:access_?token|api_?key|auth|authorization|password|passwd|secret|signature|sig|token|x-amz-(?:signature|credential)|x-goog-signature)="
    return not bool(re.search(sensitive, url, re.I))

def host_allowed(url, setting_name):
    host = (urlparse(url).hostname or "").lower().rstrip(".")
    allowed = [str(x).lower().strip(".") for x in SETTINGS.get(setting_name, [])]
    return bool(host) and any(host == domain or host.endswith("." + domain) for domain in allowed)

def is_approved_source(url):
    return is_public_candidate(url) and host_allowed(url, "approved_source_hosts")

def is_approved_stream(url):
    # Streams may be hosted on any globally reachable public CDN/provider.
    # The public URL, redirect targets, and HLS segments are still screened.
    return is_public_candidate(url)

def approved_get(url, policy, **kwargs):
    # Follow redirects only when every hop remains on an approved host.
    current = url
    for _ in range(6):
        if not policy(current):
            raise ValueError("Request host is not approved")
        response = SESSION.get(current, allow_redirects=False, **kwargs)
        if response.status_code in (301, 302, 303, 307, 308):
            location = response.headers.get("Location")
            if not location:
                return response
            target = urljoin(response.url, location)
            response.close()
            if not policy(target):
                raise ValueError("Redirect target host is not approved")
            current = target
            continue
        return response
    raise ValueError("Too many redirects")

def is_free_to_air_label(name, group=""):
    label = f"{name or ''} {group or ''}".lower()
    blocked = r"\b(?:geo[- ]?blocked|pay[- ]?tv|subscription|premium channel|requires? login|drm)\b"
    return not bool(re.search(blocked, label, re.I))

def discover_github_playlist_sources(db):
    """Discover a bounded set of public M3U files across focused GitHub searches."""
    headers = {"Accept": "application/vnd.github+json", "User-Agent": UA}
    token = os.getenv("GITHUB_TOKEN") or os.getenv("GH_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"

    # Three focused searches improve regional/category coverage without
    # exhausting GitHub's unauthenticated search budget (10 requests/minute).
    queries = (
        "Bangladesh IPTV M3U",
        "India IPTV M3U",
        "English IPTV M3U",
    )
    repositories, seen_repos = [], set()
    for query in queries:
        try:
            response = SESSION.get(
                "https://api.github.com/search/repositories",
                params={"q": query, "sort": "updated", "order": "desc", "per_page": 12},
                headers=headers, timeout=SETTINGS["request_timeout_seconds"])
            response.raise_for_status()
            for repo in response.json().get("items", []):
                full_name = repo.get("full_name", "")
                if (full_name and full_name not in seen_repos
                        and not repo.get("archived") and not repo.get("disabled")):
                    seen_repos.add(full_name)
                    repositories.append((repo, query))
        except Exception as exc:
            logging.warning("GitHub search failed for %s: %s", query, str(exc)[:180])

    added = 0
    for repo, query in repositories[:6]:
        full_name = repo["full_name"]
        branch = repo.get("default_branch") or "main"
        tree_url = f"https://api.github.com/repos/{full_name}/git/trees/{branch}"
        try:
            tree_response = SESSION.get(tree_url, params={"recursive": "1"}, headers=headers,
                                        timeout=SETTINGS["request_timeout_seconds"])
            tree_response.raise_for_status()
            tree = tree_response.json().get("tree", [])
        except Exception as exc:
            logging.info("Skipping GitHub tree %s: %s", full_name, str(exc)[:160])
            continue

        found = 0
        for item in tree:
            path = item.get("path", "")
            lower_path = path.lower()
            if item.get("type") != "blob" or not lower_path.endswith((".m3u", ".m3u8")):
                continue
            if item.get("size", 0) > 8_000_000 or any(
                marker in lower_path for marker in ("/test", "/sample", "/backup", "/archive", "/old/")
            ):
                continue
            raw_url = f"https://raw.githubusercontent.com/{full_name}/{branch}/{path}"
            if is_approved_source(raw_url):
                before = db.total_changes
                db.execute("INSERT OR IGNORE INTO sources(url,discovered_from,depth) VALUES(?,?,0)",
                           (raw_url, f"github search: {query}; repository: {full_name}"))
                if db.total_changes > before:
                    added += 1
                found += 1
            if found >= 5 or added >= 24:
                break
        logging.info("GitHub discovery: %s (%s) yielded %d playlist files", full_name, query, found)
        if added >= 24:
            break
    db.commit()
    logging.info("Focused GitHub discovery added %d new playlist sources", added)


def load_seeds(db):
    urls = []
    for line in SEEDS.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and line.startswith(("http://", "https://")):
            if is_approved_source(line):
                urls.append(line)
            else:
                logging.warning("Skipping seed outside approved source hosts: %s", urlparse(line).hostname)
    for url in urls:
        db.execute("INSERT OR IGNORE INTO sources(url, discovered_from, depth) VALUES(?,?,0)", (url, "seed"))
    db.commit()
    return urls

def parse_playlist(text, source_url):
    entries, meta = [], None
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("#EXTINF"):
            attrs = dict(re.findall(r'([\w-]+)="([^"]*)"', line))
            name = line.rsplit(",", 1)[-1].strip() if "," in line else attrs.get("tvg-name", "Unknown")
            meta = {
                "name": name or attrs.get("tvg-name") or "Unknown",
                "tvg_id": attrs.get("tvg-id", ""),
                "logo": attrs.get("tvg-logo", ""),
                "category": attrs.get("group-title", "Uncategorized"),
                "country": attrs.get("tvg-country", ""),
                "language": attrs.get("tvg-language", ""),
            }
        elif line.startswith(("http://", "https://")):
            if meta:
                if is_approved_stream(line) and is_free_to_air_label(meta.get("name"), meta.get("category")):
                    entries.append({**meta, "url": canonical_url(line), "source_url": source_url})
                meta = None
            elif is_approved_source(line) and re.search(r'\.m3u(?:$|[?#])', line, re.I):
                entries.append({"name": Path(urlparse(line).path).name or "Nested playlist",
                                "url": canonical_url(line), "source_url": source_url, "is_source": True})
    return entries

def category_for(name, group, url, source_url="", country="", language=""):
    # Use channel metadata plus the playlist index path. The index path is
    # important because community M3U files often omit tvg-country/language.
    source_path = urlparse(source_url).path.lower()
    hay = " ".join((name, group, country, language, source_path)).lower()
    country_code = (country or "").lower().strip()
    language_code = (language or "").lower().strip()

    source_bd = "/countries/bd." in source_path
    source_in = "/countries/in." in source_path
    source_english = "/languages/eng." in source_path
    source_movies = "/categories/movies." in source_path or "/output/movie." in source_path
    source_music = "/categories/music." in source_path
    source_kids = "/categories/kids." in source_path
    source_sports = "/categories/sports." in source_path

    is_bd = source_bd or country_code in ("bd", "bgd") or language_code in ("ben-bd", "bn-bd") or (
        any(x in hay for x in ("bangladesh", "bangla"))
        or "btvlive.gov.bd" in source_url or "btv.gov.bd" in source_url
    )
    is_india = source_in or country_code in ("in", "ind") or language_code in (
        "hin", "tam", "tel", "kan", "mal", "mar", "guj", "ori", "asm", "pan"
    ) or any(x in hay for x in ("india", "indian", "hindi", "tamil", "telugu", "kolkata"))
    is_english = source_english or language_code in ("eng", "en", "english") or any(
        x in hay for x in ("english", "hollywood", "countries/gb", "countries/us",
                           "countries/ca", "countries/au", "countries/nz")
    )
    is_kids = source_kids or any(x in hay for x in ("kids", "children", "cartoon", "nick", "disney", "animation"))
    is_sports = source_sports or any(x in hay for x in ("sport", "cricket", "football", "tennis", "formula 1"))
    is_movie = source_movies or any(x in hay for x in ("movie", "movies", "cinema", "film", "hollywood"))
    is_music = source_music or any(x in hay for x in ("music", "musical", "mtv", "vevo"))

    if is_kids:
        return "Kids"
    if is_sports:
        return "Sports"
    if is_movie:
        if is_india: return "Indian Movies"
        if is_english: return "English Movies"
        return "Uncategorized"
    if is_music:
        if is_india: return "Indian Music"
        if is_english: return "English Music"
        return "Uncategorized"
    if is_bd:
        return "Bangladesh TV"
    if is_india:
        return "Indian TV"
    if is_english:
        return "English TV"
    return "Uncategorized"

def discover_playlist_refs(body, base_url):
    # Follow explicit playlist links found in public HTML, Markdown, or JSON indexes.
    refs = set()
    pattern = r"""https?://[^\s"'<>]+|(?:\./|/)[^\s"'<>]+\.m3u8?(?:\?[^\s"'<>]*)?"""
    candidates = re.findall(pattern, body, re.I)
    for candidate in candidates:
        candidate = candidate.rstrip("),.;]}'")
        absolute = urljoin(base_url, candidate)
        if re.search(r"\.m3u(?:$|[?#])", absolute, re.I) and is_approved_source(absolute):
            refs.add(canonical_url(absolute))
    return refs

def discover_stream_refs(body, page_url):
    # Extract public HLS candidates from any approved public source page.
    # They still pass public-host, redirect, token, and media validation checks.
    refs = []
    pattern = r"""https?://[^\s"'<>]+|(?:\./|/)[^\s"'<>]+\.m3u8(?:\?[^\s"'<>]*)?"""
    candidates = re.findall(pattern, body, re.I)
    slug = Path(urlparse(page_url).path.rstrip("/")).name or "Public stream page"
    name = re.sub(r"[-_]+", " ", slug).strip()
    for candidate in candidates:
        candidate = candidate.rstrip("),.;]}'")
        absolute = canonical_url(urljoin(page_url, candidate))
        if re.search(r"\.m3u8(?:$|[?#])", absolute, re.I) and is_public_candidate(absolute):
            refs.append({
                "name": name,
                "category": "Unverified",
                "country": "",
                "language": "",
                "url": absolute,
                "source_url": page_url,
                "approved": is_approved_stream(absolute),
            })
    return refs

def fetch_source(url):
    if not is_approved_source(url):
        return url, url, None, "", 0.0, "Source host is not approved"
    start = time.monotonic()
    response = None
    try:
        response = approved_get(url, is_approved_source,
                                timeout=SETTINGS["request_timeout_seconds"], stream=True)
        final_url = response.url
        status = response.status_code
        if not is_approved_source(final_url):
            response.close()
            return url, final_url, status, "", time.monotonic() - start, "Redirected to an unapproved source host"
        response.raise_for_status()
        chunks, total = [], 0
        for chunk in response.iter_content(65536):
            if chunk:
                chunks.append(chunk)
                total += len(chunk)
                if total > 12_000_000:
                    break
        body = b"".join(chunks).decode(response.encoding or "utf-8", errors="replace")
        response.close()
        return url, final_url, status, body, time.monotonic() - start, None
    except Exception as exc:
        # Preserve HTTP errors such as 401/403/404 in the source diagnostics.
        status = response.status_code if response is not None else None
        final_url = response.url if response is not None else url
        if response is not None:
            response.close()
        return url, final_url, status, "", time.monotonic() - start, str(exc)[:300]

def add_channel(db, entry):
    name = entry.get("name") or "Unknown"
    group = entry.get("category", "")
    source_url = entry.get("source_url", "")
    if (not is_approved_source(source_url)
            or not is_approved_stream(entry["url"])
            or not is_free_to_air_label(name, group)):
        return
    cat = category_for(name, group, entry["url"], source_url,
                       entry.get("country", ""), entry.get("language", ""))
    norm = re.sub(r"[^a-z0-9]+", "", name.lower())
    db.execute("""INSERT OR IGNORE INTO channels(name,tvg_id,logo,category,normalized_name)
                  VALUES(?,?,?,?,?)""",
               (name, entry.get("tvg_id", ""), entry.get("logo", ""), cat, norm))
    row = db.execute("SELECT id FROM channels WHERE normalized_name=? AND category=?", (norm, cat)).fetchone()
    if row:
        db.execute("""INSERT INTO links(
                          channel_id,url,source_url,source_name,group_title,country,language,tvg_id,logo
                      ) VALUES(?,?,?,?,?,?,?,?,?)
                      ON CONFLICT(url) DO UPDATE SET
                        group_title=CASE WHEN excluded.group_title<>'' THEN excluded.group_title ELSE links.group_title END,
                        country=CASE WHEN excluded.country<>'' THEN excluded.country ELSE links.country END,
                        language=CASE WHEN excluded.language<>'' THEN excluded.language ELSE links.language END,
                        tvg_id=CASE WHEN excluded.tvg_id<>'' THEN excluded.tvg_id ELSE links.tvg_id END,
                        logo=CASE WHEN excluded.logo<>'' THEN excluded.logo ELSE links.logo END,
                        source_url=CASE
                          WHEN lower(excluded.source_url) LIKE '%/countries/bd.%'
                            OR lower(excluded.source_url) LIKE '%/countries/in.%'
                            OR lower(excluded.source_url) LIKE '%/languages/eng.%'
                            OR lower(excluded.source_url) LIKE '%/categories/%'
                          THEN excluded.source_url ELSE links.source_url END,
                        last_seen=CURRENT_TIMESTAMP""",
                   (row[0], entry["url"], source_url,
                    entry.get("source_name", "public playlist"), group,
                    entry.get("country", ""), entry.get("language", ""),
                    entry.get("tvg_id", ""), entry.get("logo", "")))
        # Merge metadata from duplicate appearances of the same stream URL.
        db.execute("UPDATE links SET last_seen=CURRENT_TIMESTAMP WHERE url=?", (entry["url"],))


def prune_unapproved(db):
    bad_links = []
    for link_id, url, source_url in db.execute("SELECT id,url,source_url FROM links"):
        if not is_approved_stream(url) or not is_approved_source(source_url or ""):
            bad_links.append((link_id,))
    if bad_links:
        db.executemany("DELETE FROM links WHERE id=?", bad_links)

    bad_sources = [
        (url,) for (url,) in db.execute("SELECT url FROM sources")
        if not is_approved_source(url)
    ]
    if bad_sources:
        db.executemany("DELETE FROM sources WHERE url=?", bad_sources)

    db.execute("DELETE FROM channels WHERE NOT EXISTS (SELECT 1 FROM links WHERE links.channel_id=channels.id)")
    db.commit()
    logging.info("Removed %d unapproved links and %d unapproved sources", len(bad_links), len(bad_sources))

def discover(db):
    queue = [(r[0], r[1]) for r in db.execute("SELECT url,depth FROM sources WHERE last_checked IS NULL OR last_checked < datetime('now','-20 hours') ORDER BY depth ASC LIMIT ?", (SETTINGS["max_sources_per_run"],)) if is_approved_source(r[0])]
    visited = set()
    while queue and len(visited) < SETTINGS["max_sources_per_run"]:
        batch = []
        for url, depth in queue:
            if url not in visited:
                visited.add(url); batch.append((url, depth))
        queue = []
        if not batch: break
        with concurrent.futures.ThreadPoolExecutor(max_workers=SETTINGS["max_workers"]) as pool:
            results = list(pool.map(lambda x: fetch_source(x[0]), batch))
        for (requested, depth), result in zip(batch, results):
            _, final_url, status, body, elapsed, error = result
            if error:
                db.execute("""UPDATE sources SET last_checked=CURRENT_TIMESTAMP,status='error',
                              http_status=?,last_error=?,entries_found=0,stream_candidates=0
                              WHERE url=?""", (status, error, requested))
                logging.warning("Source failed %s: %s", requested, error)
                continue
            entries = parse_playlist(body, final_url)[:SETTINGS["max_channels_per_source"]]
            stream_entries = []
            if not body.lstrip().startswith("#EXTM3U"):
                stream_entries = discover_stream_refs(body, final_url)
            nested_from_entries = {entry["url"] for entry in entries if entry.get("is_source")}
            nested_refs = discover_playlist_refs(body, final_url)
            nested_sources = nested_from_entries | nested_refs
            stream_candidates = sum(1 for entry in entries if not entry.get("is_source")) + len(stream_entries)
            # A successful HTTP fetch with no playable or nested stream references is
            # not a healthy discovery result; keep it distinct from a useful source.
            source_state = "done" if stream_candidates or nested_sources else "empty"
            entries_found = len(entries) + len(stream_entries) + len(nested_sources - nested_from_entries)
            db.execute("""UPDATE sources SET last_checked=CURRENT_TIMESTAMP,status=?,http_status=?,
                          last_error=NULL,entries_found=?,stream_candidates=? WHERE url=?""",
                       (source_state, status, entries_found, stream_candidates, requested))
            for stream_entry in stream_entries:
                if stream_entry.get("approved"):
                    add_channel(db, stream_entry)
                else:
                    db.execute(
                        "INSERT OR IGNORE INTO candidate_streams(url,source_url,notes) VALUES(?,?,?)",
                        (stream_entry["url"], stream_entry["source_url"],
                         "Found on a public source page; awaiting stream validation")
                    )
            for nested in sorted(nested_sources):
                if depth < SETTINGS["max_recursive_depth"] and nested not in visited:
                    db.execute("INSERT OR IGNORE INTO sources(url,discovered_from,depth) VALUES(?,?,?)",
                               (nested, requested, depth + 1))
                    queue.append((nested, depth + 1))
            for entry in entries:
                if not entry.get("is_source"):
                    entry["source_name"] = urlparse(final_url).netloc
                    add_channel(db, entry)
            logging.info("Parsed %s: %d entries, %d stream candidates, %d nested sources",
                         requested, entries_found, stream_candidates, len(nested_sources))
        db.commit()


def recategorize_channels(db):
    """Reclassify channels using metadata retained separately for every source link."""
    rows = db.execute("""
        SELECT c.id, c.name, c.category, c.normalized_name,
               l.url, COALESCE(l.source_url,''), COALESCE(l.group_title,''),
               COALESCE(l.country,''), COALESCE(l.language,'')
        FROM channels c JOIN links l ON l.channel_id=c.id
        ORDER BY c.id, l.id
    """).fetchall()
    grouped = {}
    for channel_id, name, current, normalized, url, source_url, group, country, language in rows:
        item = grouped.setdefault(channel_id, {
            "name": name, "current": current, "normalized": normalized, "counts": defaultdict(int)
        })
        category = category_for(name, group, url, source_url, country, language)
        if category != "Uncategorized":
            item["counts"][category] += 1

    changed = 0
    for channel_id, item in grouped.items():
        if not item["counts"]:
            continue
        # Majority metadata wins; stable lexical tie-break avoids run-to-run flips.
        desired = sorted(item["counts"].items(), key=lambda pair: (-pair[1], pair[0]))[0][0]
        if desired == item["current"]:
            continue
        target = db.execute(
            "SELECT id FROM channels WHERE normalized_name=? AND category=? AND id<>?",
            (item["normalized"], desired, channel_id)
        ).fetchone()
        if target:
            db.execute("UPDATE links SET channel_id=? WHERE channel_id=?", (target[0], channel_id))
            db.execute("DELETE FROM channels WHERE id=?", (channel_id,))
        else:
            db.execute("UPDATE channels SET category=? WHERE id=?", (desired, channel_id))
        changed += 1
    db.commit()
    logging.info("Reclassified %d channels using retained per-link playlist metadata", changed)


def check_link(row):
    link_id, url, source_url = row
    if not is_approved_stream(url):
        return link_id, None, 0.0, 0.0, 0, "Stream host is not approved"
    # Some public stream hosts require the public playlist page as Referer/Origin.
    # This does not bypass login, DRM, geo-blocks, or signed URL controls.
    headers = {}
    if source_url:
        parsed_source = urlparse(source_url)
        headers["Referer"] = source_url
        if parsed_source.scheme and parsed_source.netloc:
            headers["Origin"] = f"{parsed_source.scheme}://{parsed_source.netloc}"
    start = time.monotonic()
    try:
        with approved_get(url, is_approved_stream, timeout=SETTINGS["request_timeout_seconds"],
                          stream=True, headers=headers) as r:
            ttfb = time.monotonic() - start
            status = r.status_code
            if not is_approved_stream(r.url):
                return link_id, None, ttfb, 0.0, 0, "Redirected to an unapproved stream host"
            if status >= 400:
                return link_id, status, ttfb, 0.0, 0, f"HTTP {status}"
            ctype = r.headers.get("Content-Type", "").lower()
            sample = next(r.iter_content(65536), b"")
            elapsed = max(time.monotonic() - start, 0.001)
            rate = len(sample) / elapsed
            is_hls = ".m3u8" in url.lower() or "mpegurl" in ctype or sample.lstrip().startswith(b"#EXTM3U")
            segment_ok = 0 if is_hls else 1
            if is_hls and sample:
                manifest = sample.decode("utf-8", errors="ignore")
                segment = next((x.strip() for x in manifest.splitlines()
                                if x.strip() and not x.startswith("#")), None)
                if segment:
                    segment_url = urljoin(r.url, segment)
                    try:
                        with approved_get(segment_url, is_approved_stream,
                                          timeout=SETTINGS["request_timeout_seconds"],
                                          stream=True, headers=headers) as sr:
                            segment_ok = int(is_approved_stream(sr.url) and sr.status_code < 400 and len(next(sr.iter_content(4096), b"")) >= SETTINGS["minimum_segment_bytes"])
                    except Exception:
                        segment_ok = 0
                else:
                    segment_ok = 1
            ok = status < 400 and (not is_hls or segment_ok == 1)
            return link_id, status, ttfb, rate, segment_ok, None if ok else "HLS segment check failed"
    except Exception as exc:
        return link_id, None, time.monotonic()-start, 0.0, 0, str(exc)[:300]

def validate(db):
    rows = db.execute("""SELECT id,url,COALESCE(source_url,'') FROM links
                         WHERE last_seen >= datetime('now','-45 days')
                           AND (last_checked IS NULL OR last_checked < datetime('now','-20 hours'))
                         ORDER BY id LIMIT 1200""").fetchall()
    # last_checked is set for every tested link below; old rows are revisited on later runs.
    with concurrent.futures.ThreadPoolExecutor(max_workers=SETTINGS["max_workers"]) as pool:
        results = list(pool.map(check_link, rows))
    for link_id, status, ttfb, rate, segment_ok, error in results:
        fast = (status is not None and status < 400 and rate >= SETTINGS["minimum_download_bytes_per_second"]
                and segment_ok == 1)
        state = "fast" if fast else ("slow" if status is not None and status < 400 else "offline")
        db.execute("""UPDATE links SET status=?,http_status=?,ttfb=?,total_seconds=?,bytes_per_second=?,
                      segment_ok=?,error=?,last_checked=CURRENT_TIMESTAMP WHERE id=?""",
                   (state,status,ttfb,ttfb,rate,segment_ok,error,link_id))
    db.commit()
    logging.info("Validated %d links", len(results))

def write_playlist(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["#EXTM3U"]
    for r in rows:
        name, logo, cat, url = r
        safe = lambda s: str(s or "").replace('"', "'").replace("\n", " ")
        lines.append(f'#EXTINF:-1 tvg-name="{safe(name)}" tvg-logo="{safe(logo)}" group-title="{safe(cat)}",{safe(name)}')
        lines.append(url)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

def write_source_report(db):
    rows = db.execute("""SELECT url, COALESCE(discovered_from,''), depth, status,
                                http_status, last_checked, COALESCE(last_error,''),
                                COALESCE(entries_found,0), COALESCE(stream_candidates,0)
                         FROM sources ORDER BY depth, url""").fetchall()
    with (OUT_DIR / "source_report.csv").open("w", encoding="utf-8", newline="") as f:
        import csv
        writer = csv.writer(f)
        writer.writerow(["source_url", "discovered_from", "depth", "status", "http_status",
                         "last_checked", "last_error", "entries_found", "stream_candidates"])
        writer.writerows(rows)
    status_counts = db.execute("SELECT status, COUNT(*) FROM sources GROUP BY status").fetchall()
    logging.info("Source health: %s", ", ".join(f"{status}={count}" for status, count in status_counts) or "no sources")
    logging.info("Source diagnostics written for %d sources", len(rows))


def write_candidate_report(db):
    rows = db.execute("""SELECT url, source_url, discovered_at, status, COALESCE(notes,'')
                         FROM candidate_streams ORDER BY discovered_at DESC, source_url""").fetchall()
    with (OUT_DIR / "candidate_stream_report.csv").open("w", encoding="utf-8", newline="") as f:
        import csv
        writer = csv.writer(f)
        writer.writerow(["candidate_stream_url", "public_source_page", "discovered_at", "review_status", "notes"])
        writer.writerows(rows)
    logging.info("Unverified HLS candidates awaiting review: %d", len(rows))


def write_link_health_report(db):
    rows = db.execute("""SELECT c.name, c.category, l.url, COALESCE(l.source_url,''),
                                l.status, l.http_status, l.ttfb, l.total_seconds,
                                l.bytes_per_second, l.segment_ok, COALESCE(l.error,''),
                                l.last_checked
                         FROM links l JOIN channels c ON c.id=l.channel_id
                         ORDER BY c.category, c.name, l.status, l.url""").fetchall()
    with (OUT_DIR / "link_health_report.csv").open("w", encoding="utf-8", newline="") as f:
        import csv
        writer = csv.writer(f)
        writer.writerow(["channel", "category", "stream_url", "source_url", "status",
                         "http_status", "ttfb_seconds", "total_seconds", "bytes_per_second",
                         "segment_ok", "error", "last_checked"])
        writer.writerows(rows)
    status_counts = db.execute("SELECT status, COUNT(*) FROM links GROUP BY status").fetchall()
    logging.info("Link health: %s", ", ".join(f"{status}={count}" for status, count in status_counts) or "no links")
    logging.info("Link diagnostics written for %d links", len(rows))


def generate(db):
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    write_source_report(db)
    write_candidate_report(db)
    write_link_health_report(db)
    base = db.execute("""SELECT c.name,c.logo,c.category,l.url,l.status,l.bytes_per_second,l.ttfb
                         FROM links l JOIN channels c ON c.id=l.channel_id
                         WHERE l.status IN ('fast','slow') ORDER BY l.bytes_per_second DESC""").fetchall()
    base = [r for r in base if is_approved_stream(r[3]) and is_free_to_air_label(r[0], r[2])]
    best = {}
    for name,logo,cat,url,status,speed,ttfb in base:
        key = (re.sub(r"[^a-z0-9]+","",name.lower()), cat)
        candidate = (name,logo,cat,url,status,speed,ttfb)
        current = best.get(key)
        if current is None or (status == "fast" and current[4] != "fast") or (
            status == current[4] and (speed or 0) > (current[5] or 0)
        ):
            best[key] = candidate
    fast = [x for x in best.values() if x[4]=="fast"]
    all_fast = list({x[3]: x[:4] for x in base if x[4]=="fast"}.values())
    write_playlist(OUT_DIR/"combined.m3u", [x[:4] for x in fast])
    write_playlist(OUT_DIR/"all_fast_sources.m3u", all_fast)
    write_playlist(OUT_DIR/"backup_slow.m3u", [x[:4] for x in best.values() if x[4]=="slow"])
    for category in SETTINGS["categories"]:
        safe = re.sub(r"[^a-z0-9]+","_",category.lower()).strip("_")
        write_playlist(OUT_DIR/f"{safe}.m3u", [x[:4] for x in fast if x[2]==category])
    with (OUT_DIR/"channel_report.csv").open("w",encoding="utf-8",newline="") as f:
        import csv
        w=csv.writer(f); w.writerow(["channel","category","status","bytes_per_second","ttfb","url"])
        for x in best.values(): w.writerow([x[0],x[2],x[4],round(x[5] or 0),round(x[6] or 0,3),x[3]])
    logging.info("Generated %d fast primary channels and %d fast source links",len(fast),len(all_fast))
    category_counts = {category: sum(1 for item in fast if item[2] == category)
                       for category in SETTINGS["categories"]}
    logging.info("Fast channel counts by category: %s",
                 ", ".join(f"{category}={count}" for category, count in category_counts.items()))

def main():
    db=connect()
    try:
        prune_unapproved(db)
        load_seeds(db)
        discover_github_playlist_sources(db)
        discover(db)
        recategorize_channels(db)
        validate(db)
        generate(db)
    finally:
        db.close()

if __name__ == "__main__":
    main()
