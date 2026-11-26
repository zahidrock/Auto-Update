from __future__ import annotations

import concurrent.futures
import json
import logging
import re
import sqlite3
import time
from collections import defaultdict
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
SETTINGS = json.loads((ROOT / "config/settings.json").read_text(encoding="utf-8"))
DB_PATH = REPO / SETTINGS["database"]
OUT_DIR = REPO / SETTINGS["output_dir"]
SEEDS = ROOT / "config/seeds.txt"
UA = "Mozilla/5.0 (compatible; PublicStreamResearch/1.0)"
SESSION = requests.Session()
SESSION.headers.update({"User-Agent": UA, "Accept": "*/*"})
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

def connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DB_PATH)
    db.execute("PRAGMA journal_mode=WAL")
    db.executescript("""
    CREATE TABLE IF NOT EXISTS sources(
      url TEXT PRIMARY KEY, discovered_from TEXT, depth INTEGER DEFAULT 0,
      last_seen TEXT DEFAULT CURRENT_TIMESTAMP, last_checked TEXT, status TEXT DEFAULT 'new'
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
    """)
    return db

def canonical_url(url):
    return url.strip().replace("&amp;", "&")

def load_seeds(db):
    urls = []
    for line in SEEDS.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and line.startswith(("http://", "https://")):
            urls.append(line)
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
            }
        elif line.startswith(("http://", "https://")):
            if meta:
                entries.append({**meta, "url": canonical_url(line), "source_url": source_url})
                meta = None
            elif re.search(r'\.(m3u8?|m3u)(?:$|[?#])', line, re.I):
                entries.append({"name": Path(urlparse(line).path).name or "Nested playlist",
                                "url": canonical_url(line), "source_url": source_url, "is_source": True})
    return entries

def category_for(name, group, url):
    hay = " ".join((name, group, url)).lower()
    rules = SETTINGS.get("categories", {})
    if any(x in hay for x in ("bangladesh", "bangla", "bd-", "bd/")):
        return "Bangladesh TV"
    if any(x in hay for x in ("india", "indian", "hindi", "tamil", "telugu", "bengali", "kolkata")):
        if "movie" in hay or "cinema" in hay: return "Indian Movies"
        if "music" in hay: return "Indian Music"
        return "Indian TV"
    if any(x in hay for x in ("kids", "children", "cartoon", "nick", "disney")):
        return "Kids"
    if any(x in hay for x in ("sport", "cricket", "football", "tennis")):
        return "Sports"
    if "movie" in hay or "cinema" in hay:
        return "English Movies" if any(x in hay for x in ("english", "eng", "hollywood")) else "Indian Movies"
    if "music" in hay:
        return "English Music" if any(x in hay for x in ("english", "eng")) else "Indian Music"
    if any(x in hay for x in ("english", "eng", "usa", "uk", "united states", "united kingdom")):
        return "English TV"
    return "English TV" if group.lower() in ("news", "entertainment", "documentary") else "Uncategorized"

def fetch_source(url):
    try:
        start = time.monotonic()
        response = SESSION.get(url, timeout=SETTINGS["request_timeout_seconds"], stream=True, allow_redirects=True)
        response.raise_for_status()
        chunks, total = [], 0
        for chunk in response.iter_content(65536):
            if chunk:
                chunks.append(chunk); total += len(chunk)
                if total > 12_000_000: break
        text = b"".join(chunks).decode(response.encoding or "utf-8", errors="replace")
        return url, response.url, response.status_code, text, time.monotonic() - start, None
    except Exception as exc:
        return url, url, None, "", 0.0, str(exc)[:300]

def add_channel(db, entry):
    name = entry.get("name") or "Unknown"
    cat = category_for(name, entry.get("category", ""), entry["url"])
    norm = re.sub(r"[^a-z0-9]+", "", name.lower())
    db.execute("""INSERT OR IGNORE INTO channels(name,tvg_id,logo,category,normalized_name)
                  VALUES(?,?,?,?,?)""", (name, entry.get("tvg_id",""), entry.get("logo",""), cat, norm))
    row = db.execute("SELECT id FROM channels WHERE normalized_name=? AND category=?", (norm,cat)).fetchone()
    if row:
        db.execute("""INSERT OR IGNORE INTO links(channel_id,url,source_url,source_name)
                      VALUES(?,?,?,?)""", (row[0], entry["url"], entry.get("source_url"), entry.get("source_name","public playlist")))
        db.execute("UPDATE links SET last_seen=CURRENT_TIMESTAMP WHERE url=?", (entry["url"],))

def discover(db):
    queue = [(r[0], r[1]) for r in db.execute("SELECT url,depth FROM sources WHERE last_checked IS NULL OR last_checked < datetime('now','-20 hours') ORDER BY depth ASC LIMIT ?", (SETTINGS["max_sources_per_run"],))]
    visited = set()
    while queue:
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
            db.execute("UPDATE sources SET last_checked=CURRENT_TIMESTAMP,status=? WHERE url=?",
                       ("done" if status and status < 400 else "error", requested))
            if error:
                logging.warning("Source failed %s: %s", requested, error); continue
            entries = parse_playlist(body, final_url)[:SETTINGS["max_channels_per_source"]]
            for entry in entries:
                if entry.get("is_source"):
                    nested = entry["url"]
                    if depth < SETTINGS["max_recursive_depth"] and nested not in visited:
                        db.execute("INSERT OR IGNORE INTO sources(url,discovered_from,depth) VALUES(?,?,?)",
                                   (nested, requested, depth + 1))
                        queue.append((nested, depth + 1))
                else:
                    entry["source_name"] = urlparse(final_url).netloc
                    add_channel(db, entry)
            logging.info("Parsed %s: %d entries", requested, len(entries))
        db.commit()

def check_link(row):
    link_id, url = row
    start = time.monotonic()
    try:
        with SESSION.get(url, timeout=SETTINGS["request_timeout_seconds"], stream=True, allow_redirects=True) as r:
            ttfb = time.monotonic() - start
            status = r.status_code
            if status >= 400:
                return link_id, status, ttfb, 0.0, 0, f"HTTP {status}"
            ctype = r.headers.get("Content-Type", "").lower()
            sample = next(r.iter_content(65536), b"")
            elapsed = max(time.monotonic() - start, 0.001)
            rate = len(sample) / elapsed
            is_hls = ".m3u8" in url.lower() or "mpegurl" in ctype or sample.lstrip().startswith(b"#EXTM3U")
            segment_ok = 0
            if is_hls and sample:
                manifest = sample.decode("utf-8", errors="ignore")
                segment = next((x.strip() for x in manifest.splitlines()
                                if x.strip() and not x.startswith("#")), None)
                if segment:
                    segment_url = urljoin(r.url, segment)
                    try:
                        with SESSION.get(segment_url, timeout=SETTINGS["request_timeout_seconds"],
                                         stream=True, allow_redirects=True) as sr:
                            segment_ok = int(sr.status_code < 400 and len(next(sr.iter_content(4096), b"")) >= SETTINGS["minimum_segment_bytes"])
                    except Exception:
                        segment_ok = 0
                else:
                    segment_ok = 1
            ok = status < 400 and (not is_hls or segment_ok == 1)
            return link_id, status, ttfb, rate, segment_ok, None if ok else "HLS segment check failed"
    except Exception as exc:
        return link_id, None, time.monotonic()-start, 0.0, 0, str(exc)[:300]

def validate(db):
    rows = db.execute("""SELECT id,url FROM links
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

def generate(db):
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    base = db.execute("""SELECT c.name,c.logo,c.category,l.url,l.status,l.bytes_per_second,l.ttfb
                         FROM links l JOIN channels c ON c.id=l.channel_id
                         WHERE l.status IN ('fast','slow') ORDER BY l.bytes_per_second DESC""").fetchall()
    best = {}
    for name,logo,cat,url,status,speed,ttfb in base:
        key = re.sub(r"[^a-z0-9]+","",name.lower())
        if key not in best or (status=="fast" and best[key][4]!="fast"):
            best[key] = (name,logo,cat,url,status,speed,ttfb)
    fast = [x for x in best.values() if x[4]=="fast"]
    all_fast = [x[:4] for x in base if x[4]=="fast"]
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

def main():
    db=connect()
    try:
        load_seeds(db)
        discover(db)
        validate(db)
        generate(db)
    finally:
        db.close()

if __name__ == "__main__":
    main()
