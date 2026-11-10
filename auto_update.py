"""
Standalone IPTV updater (kono GUI / iptv_core lagbe na).
Source: AynaOTT + JagoBD + GitHub (BD, IN, PK, Movies/Music) -> dead check -> shudhu alive rakhbe.
PRIORITY list er channel gula playlist er sobar upore thakbe (oi order e).
"""
import json, os, re, ssl, sys, time
import urllib.error, urllib.parse, urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

# ------------------------------------------------------------------ settings
OUTPUT = Path("playlist.m3u")
WORKERS = 60                 # ek sathe koto link check hobe
CHECK_TIMEOUT = 8            # sekond
MAX_LINKS_PER_PRIORITY = 1   # top 39 channel er proti channel e max koto alive link (0 = shob)
MAX_LINKS_PER_CHANNEL = 1    # baki channel er proti naam e max koto link (1 = duplicate nei)
MIN_KEEP_RATIO = 0.5         # alive sonkhya ager playlist er 50% er niche hole overwrite korbe na
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")

IPTV_BASE = "https://iptv-org.github.io/iptv"

# Desh wise (shob channel nibe). (group name, m3u link)
COUNTRY_SOURCES = [
    ("Bangladesh", f"{IPTV_BASE}/countries/bd.m3u"),
    ("India",      f"{IPTV_BASE}/countries/in.m3u"),
    ("Pakistan",   f"{IPTV_BASE}/countries/pk.m3u"),
]

# Category + Bhasha: duita lister common channel (group name, category, language code)
COMBOS = [
    ("Kolkata Movies", "movies", "ben"),
    ("Hindi Movies",   "movies", "hin"),
    ("English Movies", "movies", "eng"),
    ("Hindi Music",    "music",  "hin"),
    ("English Music",  "music",  "eng"),
    ("Bangla Music",   "music",  "ben"),
    ("Sports",         "sports", ("hin", "eng", "ben")),
]

# Nijer extra m3u (ekhane shob channel nibe, original group thakbe)
EXTRA_PLAYLISTS = [
    "https://raw.githubusercontent.com/zahidrock/zahid/refs/heads/main/tv.m3u8",
]

# GitHub code search (GITHUB_TOKEN lagbe). Random playlist theke shudhu movies/music (BD/IN/EN)
# ar tomar PRIORITY channel gula nibe
USE_GITHUB_SEARCH = True

# Playlist e group er order
GROUP_ORDER = ["Kolkata Movies", "Hindi Movies", "English Movies", "Hindi Music", "English Music",
               "Bangla Music", "Sports",
               "Bangladesh", "Bangla (India)", "India", "Pakistan"]   # er pore baki shob (Others)

# Sobar upore ei channel gula (ei order e) thakbe
PRIORITY = [
    ("BTV", "BD"), ("BTV World", "BD"), ("BTV Chattogram", "BD"), ("Somoy TV", "BD"),
    ("Jamuna Television", "BD"), ("Ekattor TV", "BD"), ("Channel 24", "BD"), ("DBC News", "BD"),
    ("Independent Television", "BD"), ("ATN News", "BD"), ("News 24", "BD"),
    ("Channel i", "BD"), ("NTV", "BD"), ("RTV", "BD"), ("ATN Bangla", "BD"), ("Banglavision", "BD"),
    ("Maasranga Television", "BD"), ("Deepto TV", "BD"), ("Boishakhi TV", "BD"), ("Desh TV", "BD"),
    ("Nagorik TV", "BD"), ("GTV", "BD"), ("Asian TV", "BD"), ("SA TV", "BD"), ("Channel 9", "BD"),
    ("Mohona TV", "BD"), ("My TV", "BD"), ("Bijoy TV", "BD"), ("Ananda TV", "BD"),
    ("Global Television", "BD"), ("Nexus Television", "BD"),
    ("T Sports", "BD"), ("Duronto TV", "BD"), ("Gaan Bangla", "BD"),
    ("Star Jalsha", "IN"), ("Zee Bangla", "IN"), ("Colors Bangla", "IN"), ("Sony Aath", "IN"),
    ("Jalsha Movies", "IN"),
]
GROUP_LABEL = {"BD": "Bangladesh", "IN": "Bangla (India)"}

# Adult content filter (random GitHub playlist e thakte pare)
BLOCK_WORDS = ["xxx", "adult", "porn", "18+", "erotic", "sex"]

# ------------------------------------------------------------------ http
SSL_CTX = ssl.create_default_context()
SSL_CTX.check_hostname = False
SSL_CTX.verify_mode = ssl.CERT_NONE
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/129.0.0.0 Safari/537.36")
HEADERS = {"User-Agent": UA, "Accept": "*/*", "Accept-Language": "en-US,en;q=0.9"}


def log(msg):
    print(msg, flush=True)


def http_get(url, headers=None, timeout=15):
    req = urllib.request.Request(url, headers=headers or HEADERS)
    with urllib.request.urlopen(req, timeout=timeout, context=SSL_CTX) as r:
        return r.read().decode("utf-8", errors="ignore")


# ------------------------------------------------------------------ m3u parse
def parse_m3u(text, source):
    out, meta = [], None
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith("#EXTINF"):
            def attr(k):
                m = re.search(rf'{k}="([^"]*)"', line, re.I)
                return m.group(1).strip() if m else ""
            name = line.rsplit(",", 1)[-1].strip() if "," in line else attr("tvg-name")
            meta = {"name": name or attr("tvg-name") or "Unknown", "tvg_id": attr("tvg-id"),
                    "logo": attr("tvg-logo"), "group": attr("group-title") or "Others",
                    "source": source}
        elif meta and not line.startswith("#"):
            if re.match(r"^https?://", line):
                meta["url"] = line
                out.append(meta)
            meta = None
    return out


# ------------------------------------------------------------------ scrapers
def scrape_github():
    cache = {}

    def get(url):
        if url not in cache:
            try:
                cache[url] = parse_m3u(http_get(url, timeout=40), "GitHub")
            except Exception as e:
                log(f"[GitHub] fail {url}: {e}")
                cache[url] = []
            log(f"[GitHub] {url.replace(IPTV_BASE + '/', '')}: {len(cache[url])} channel")
        return cache[url]

    res = []
    # 1) Category x Language (specific group age dewa hoy, jate duplicate hole egulo jite)
    for group, cat, lang in COMBOS:
        langs = (lang,) if isinstance(lang, str) else lang
        lang_urls = {c["url"].split("|")[0] for lg in langs for c in get(f"{IPTV_BASE}/languages/{lg}.m3u")}
        n = 0
        for c in get(f"{IPTV_BASE}/categories/{cat}.m3u"):
            if c["url"].split("|")[0] in lang_urls:
                res.append({**c, "group": group})
                n += 1
        log(f"[GitHub] {group}: {n} channel")

    # 2) Desh wise
    for group, url in COUNTRY_SOURCES:
        res.extend({**c, "group": "Sports" if "sport" in c["group"].lower() else group} for c in get(url))

    # 3) Extra playlist (original group thakbe)
    for url in EXTRA_PLAYLISTS:
        res.extend(get(url))

    # 4) GitHub code search
    if USE_GITHUB_SEARCH and GITHUB_TOKEN:
        h = {"User-Agent": "Mozilla/5.0", "Accept": "application/vnd.github+json",
             "Authorization": f"Bearer {GITHUB_TOKEN}"}
        raws = []
        for page in (1, 2, 3):
            try:
                api = ("https://api.github.com/search/code?q=" +
                       urllib.parse.quote("EXTINF extension:m3u") + f"&per_page=50&page={page}")
                data = json.loads(http_get(api, headers=h, timeout=20))
                for it in data.get("items", []):
                    raws.append(it["html_url"].replace("https://github.com/",
                                "https://raw.githubusercontent.com/").replace("/blob/", "/"))
                time.sleep(7)  # rate limit
            except Exception as e:
                log(f"[GitHub search] page {page}: {e}")
                break
        found = 0
        for raw in dict.fromkeys(raws):
            try:
                txt = http_get(raw, timeout=15)
                if "#EXTINF" in txt:
                    for c in parse_m3u(txt, "GitHub"):
                        c["search"] = True
                        res.append(c)
                        found += 1
            except Exception:
                pass
        log(f"[GitHub search] {len(raws)} file theke {found} channel")
    elif USE_GITHUB_SEARCH:
        log("[GitHub search] GITHUB_TOKEN nei, search skip kora holo")
    return res

def scrape_aynaott():
    base = "https://web.aynaott.com"
    h = {"User-Agent": UA, "Accept": "application/json, text/plain, */*",
         "X-Tenant-Id": "019dd92f-107c-7056-9e79-e5233f6e51d9", "Cache-Control": "no-cache"}
    catalog, seen = [], set()
    for page in range(1, 20):
        try:
            data = json.loads(http_get(f"{base}/api/v5/catalog/contents?type=live-tvs&per_page=100&page={page}",
                                       headers=h, timeout=15))
        except Exception as e:
            log(f"[AynaOTT] catalog page {page}: {e}")
            break
        recs = data.get("records", [])
        if not recs:
            break
        for r in recs:
            s = str(r.get("slug", "")).strip()
            if s and s not in seen:
                seen.add(s)
                catalog.append(r)
        if len(recs) < 100:
            break
    log(f"[AynaOTT] catalog: {len(catalog)}")

    def one(item):
        slug, title = item.get("slug", ""), item.get("title", "")
        img = item.get("images", {})
        logo = img.get("thumbnail_url", "") if isinstance(img, dict) else ""
        if logo and not logo.startswith("http"):
            logo = base + logo
        try:
            d = json.loads(http_get(f"{base}/api/v5/browse/live-tvs/{slug}", headers=h, timeout=12))
            rec = d.get("record", d)
            so = rec.get("stream", {})
            url = so.get("url", "") if isinstance(so, dict) else ""
            url = url or rec.get("stream_url") or rec.get("hls") or ""
            if url:
                return {"name": title, "url": url, "logo": logo, "tvg_id": f"aynaott-{slug}",
                        "group": "Bangla TV", "source": "AynaOTT"}
        except Exception:
            pass
        return None

    res = []
    with ThreadPoolExecutor(max_workers=20) as ex:
        for f in as_completed([ex.submit(one, i) for i in catalog]):
            r = f.result()
            if r:
                res.append(r)
    log(f"[AynaOTT] stream URL: {len(res)}")
    return res


def format_jagobd_url(raw):
    if not raw:
        return ""
    if raw.startswith("//"):
        raw = "https:" + raw
    try:
        parts = [p for p in urllib.parse.urlparse(raw).path.lstrip("/").split("/") if p]
        if len(parts) >= 2:
            return f"https://app24.jagobd.com.bd/{parts[0]}/{'/'.join(parts[1:])}"
    except Exception:
        pass
    clean = raw.split("|")[0]
    parts = [p for p in clean.split("/") if p]
    for i, p in enumerate(parts):
        if ".m3u8" in p or ".stream" in p:
            if i >= 2:
                return f"https://app24.jagobd.com.bd/{parts[i-1]}/{'/'.join(parts[i:])}"
            break
    return clean


def scrape_jagobd():
    cands = []
    try:
        html = http_get("https://www.jagobd.com/", timeout=15)
        skip = ['/category', '/tag', '/contact', '/about', '/privacy', '/page', '/wp-', '/feed',
                '/disclaimer', 'dmca', 'terms', 'advertise', 'copyright']
        seen = set()
        for url, content in re.findall(
                r'<a\s+[^>]*href=[\'"](https://www\.jagobd\.com/[^\'"#?]+)[\'"][^>]*>(.*?)</a>', html, re.S):
            url = url.rstrip("/")
            if url in seen or any(x in url.lower() for x in skip):
                continue
            seen.add(url)
            img = re.search(r'<img\s+[^>]*src=[\'"]([^\'"]+)[\'"]', content, re.I)
            alt = re.search(r'alt=[\'"]([^\'"]+)[\'"]', content, re.I)
            ttl = re.search(r'title=[\'"]([^\'"]+)[\'"]', content, re.I)
            slug = url.split("/")[-1]
            raw = (alt.group(1) if alt and alt.group(1).strip() else
                   ttl.group(1) if ttl and ttl.group(1).strip() else slug).strip()
            nm = re.sub(r'\s*(?:Live|Online|TV Live|Bangla TV|Live TV|Channel)\s*$', '', raw, flags=re.I).strip()
            nm = re.sub(r'[-_]+', ' ', nm).strip().title()
            cands.append({"slug": slug, "url": url, "name": nm or slug.replace("-", " ").title(),
                          "logo": img.group(1) if img else ""})
    except Exception as e:
        log(f"[JagoBD] homepage error: {e}")
    log(f"[JagoBD] channel link: {len(cands)}")

    def resolve(c):
        try:
            page = http_get(c["url"], timeout=12)
            embed = None
            for ifr in re.findall(r'<iframe[^>]+src=[\'"]([^\'"]+)[\'"]', page, re.I):
                if "embed.php" in ifr or "jagobd.com" in ifr:
                    embed = ifr
                    break
            stream = None
            if not embed:
                m = re.findall(r'[\'"](https?://[^\'"]+?\.m3u8[^\'"]*)[\'"]', page)
                stream = m[0] if m else None
            else:
                if embed.startswith("//"):
                    embed = "https:" + embed
                eh = http_get(embed, headers={"User-Agent": UA, "Referer": c["url"]}, timeout=12)
                for _fn, arr in re.findall(
                        r'function\s+(\w+)\(\)\s*\{\s*return\(\[([^\]]+)\]\.join\([\'"][\'"]\)', eh):
                    val = "".join(x.strip().strip("'\"") for x in arr.split(",")).replace(r"\/", "/")
                    if ".m3u8" in val:
                        stream = val
                        break
                if not stream:
                    d = re.findall(r'[\'"](https?://[^\'"]+?\.m3u8[^\'"]*)[\'"]', eh)
                    stream = d[0] if d else None
            if stream:
                return {"name": c["name"], "url": format_jagobd_url(stream), "logo": c["logo"],
                        "tvg_id": f"jagobd-{c['slug']}", "group": "Bangla TV", "source": "JagoBD"}
        except Exception:
            pass
        return None

    res = []
    with ThreadPoolExecutor(max_workers=15) as ex:
        for f in as_completed([ex.submit(resolve, c) for c in cands]):
            r = f.result()
            if r:
                res.append(r)
    log(f"[JagoBD] stream URL: {len(res)}")
    return res


# ------------------------------------------------------------------ stream check
def check_stream(raw_url):
    """(alive, latency_sec)"""
    if not raw_url:
        return False, 0
    headers, url = dict(HEADERS), raw_url
    if "|" in raw_url:
        url, extra = raw_url.split("|", 1)
        url = url.strip()
        for p in extra.split("&"):
            if "=" in p:
                k, v = p.split("=", 1)
                headers[k.strip()] = v.strip()
    if "jagobd.com" in url and "Referer" not in headers:
        headers["Referer"] = "https://www.jagobd.com/"
    elif "aynaott.com" in url and "Referer" not in headers:
        headers["Referer"] = "https://web.aynaott.com/"

    for attempt in range(2):
        t0 = time.time()
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=CHECK_TIMEOUT, context=SSL_CTX) as r:
                ctype = r.headers.get("Content-Type", "").lower()
                raw = r.read(2048)
                sample = raw.decode("utf-8", errors="ignore").strip()
                low = sample.lower()
                lat = time.time() - t0
                if r.status not in (200, 206):
                    return False, lat
                if ("<html" in low or "<body" in low) and "#extm3u" not in low:
                    return False, lat
                if any(t in low for t in ("#extm3u", "#ext-x-stream-inf", "#extinf",
                                          "#ext-x-targetduration", "#ext-x-media-sequence")):
                    return True, lat
                if any(v in ctype for v in ("video/", "audio/", "mpegurl", "octet-stream")):
                    return True, lat
                if raw and raw[0] == 0x47:
                    return True, lat
                if (".m3u8" in url or ".ts" in url) and sample and not sample.startswith("<"):
                    return True, lat
                return False, lat
        except urllib.error.HTTPError:
            return False, 0          # 4xx/5xx e retry kore lav nei
        except Exception:
            pass
        time.sleep(0.5)
    return False, 0


def check_all(channels):
    total, done, alive = len(channels), 0, []
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        fut = {ex.submit(check_stream, c["url"]): c for c in channels}
        for f in as_completed(fut):
            c = fut[f]
            try:
                ok, lat = f.result()
            except Exception:
                ok, lat = False, 0
            done += 1
            if ok:
                c["latency"] = lat
                alive.append(c)
            if done % 500 == 0 or done == total:
                log(f"checked {done}/{total} | alive {len(alive)}")
    return alive


# ------------------------------------------------------------------ priority matching
NOISE = {"hd", "fhd", "sd", "uhd", "4k", "live", "official", "hevc", "h265", "h264"}


def norm(name):
    n = name.lower()
    n = re.sub(r"[\(\[].*?[\)\]]", " ", n)         # (1080p) [Not 24/7]
    n = re.sub(r"\b\d{3,4}p\b", " ", n)
    n = n.replace("television", "tv")
    n = re.sub(r"[^a-z0-9\u0980-\u09ff]+", " ", n)
    return "".join(t for t in n.split() if t not in NOISE)


PRIORITY_MAP = {norm(n): (i, n, c) for i, (n, c) in enumerate(PRIORITY)}
SOURCE_RANK = {"AynaOTT": 0, "JagoBD": 1, "GitHub": 2}


def is_blocked(c):
    t = f'{c["name"]} {c.get("group", "")}'.lower()
    return any(re.search(rf"\b{re.escape(w)}\b", t) for w in BLOCK_WORDS)


def bd_group(name):
    return "Bangla Music" if re.search(r"\b(music|gaan|song|sangeet)\b", name.lower()) else "Bangladesh"


KOLKATA_RE = re.compile(r"\b(jalsha movies|zee bangla cinema|colors bangla cinema|bangla cinema|"
                        r"bangla movies?|bengali movies?|bengali cinema)\b")


def keyword_group(name, group=""):
    """Random GitHub playlist er channel er jonno naam/group dekhe category bujhe"""
    t = f"{name} {group}".lower()
    if KOLKATA_RE.search(t):
        return "Kolkata Movies"
    music = re.search(r"\b(music|song|songs|gaan|mtv)\b", t)
    movie = re.search(r"\b(movie|movies|cinema|film|films|flix|hbo|bollywood|hollywood)\b", t)
    sport = re.search(r"\b(sport|sports|cricket|football)\b", t)
    bn = re.search(r"\b(bangla|bengali)\b", t)
    hi = re.search(r"\b(hindi|bollywood)\b", t)
    en = re.search(r"\b(english|hollywood|hbo)\b", t)
    if music:
        if bn:
            return "Bangla Music"
        if hi:
            return "Hindi Music"
        if en:
            return "English Music"
    if movie:
        if hi:
            return "Hindi Movies"
        if en:
            return "English Movies"
    if sport:
        return "Sports"
    return None


def dedupe_by_name(chs, limit):
    """Ekoi naam er channel ek bar-i rakhbe (limit ta porjonto). Specific group > desh, tarpor source, tarpor speed"""
    specific = {g for g, _c, _l in COMBOS}

    def rank(c):
        g = c["group"]
        return (0 if g in specific else 1 if g in GROUP_ORDER else 2,
                SOURCE_RANK.get(c["source"], 9), c.get("latency", 99))

    kept, count = set(), {}
    for c in sorted(chs, key=rank):
        key = norm(c["name"]) or c["name"].lower()
        if count.get(key, 0) < limit:
            count[key] = count.get(key, 0) + 1
            kept.add(id(c))
    return [c for c in chs if id(c) in kept]


# ------------------------------------------------------------------ output
def write_playlist(top, rest):
    def q(s):
        return str(s).replace('"', "'").replace("\n", " ")
    lines = ["#EXTM3U"]
    for c in top + rest:
        lines.append(f'#EXTINF:-1 tvg-id="{q(c.get("tvg_id", ""))}" tvg-name="{q(c["name"])}" '
                     f'tvg-logo="{q(c.get("logo", ""))}" group-title="{q(c["group"])}",{c["name"]}')
        lines.append(c["url"])
    OUTPUT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    pool = []
    for name, fn in (("AynaOTT", scrape_aynaott), ("JagoBD", scrape_jagobd), ("GitHub", scrape_github)):
        try:
            pool.extend(fn())
        except Exception as e:
            log(f"[{name}] error: {e}")

    seen, items = set(), []
    for c in pool:
        raw = c["url"].split("|")[0].strip()
        if not raw or raw in seen or is_blocked(c):
            continue
        if c["source"] in ("AynaOTT", "JagoBD"):
            c["group"] = bd_group(c["name"])
        elif c.get("search"):
            kw = keyword_group(c["name"], c.get("group", ""))
            if kw:
                c["group"] = kw
            elif norm(c["name"]) not in PRIORITY_MAP:
                continue
        if KOLKATA_RE.search(c["name"].lower()):
            c["group"] = "Kolkata Movies"
        seen.add(raw)
        items.append(c)
    log(f"Total unique channel: {len(items)}")

    alive = check_all(items)
    log(f"Alive: {len(alive)} / {len(items)}")

    prev = OUTPUT.read_text(encoding="utf-8", errors="ignore").count("#EXTINF") if OUTPUT.exists() else 0
    if prev >= 20 and len(alive) < prev * MIN_KEEP_RATIO:
        log(f"[SAFETY] Alive ({len(alive)}) ager playlist ({prev}) er theke onek kom. Overwrite kora holo na.")
        return 1

    # priority bucket
    buckets, rest = {}, []
    for c in alive:
        hit = PRIORITY_MAP.get(norm(c["name"]))
        if hit:
            idx, canon, cc = hit
            c["name"], c["group"] = canon, GROUP_LABEL[cc]
            buckets.setdefault(idx, []).append(c)
        else:
            rest.append(c)

    top = []
    for idx in sorted(buckets):
        lst = sorted(buckets[idx], key=lambda c: (SOURCE_RANK.get(c["source"], 9), c.get("latency", 99)))
        top.extend(lst[:MAX_LINKS_PER_PRIORITY] if MAX_LINKS_PER_PRIORITY else lst)
    if MAX_LINKS_PER_CHANNEL:
        before = len(rest)
        rest = dedupe_by_name(rest, MAX_LINKS_PER_CHANNEL)
        log(f"Duplicate naam bad: {before} -> {len(rest)}")
    # A-Z na, shudhu group order e (group er vitore source er order e thakbe)
    rest.sort(key=lambda c: GROUP_ORDER.index(c["group"]) if c["group"] in GROUP_ORDER else 99)

    missing = [n for i, (n, _c) in enumerate(PRIORITY) if i not in buckets]
    log(f"Priority: {len(buckets)}/{len(PRIORITY)} channel alive paoa gese")
    if missing:
        log("Priority te alive paoa jay ni: " + ", ".join(missing))

    write_playlist(top, rest)
    log(f"{OUTPUT} e {len(top) + len(rest)} ta channel save hoise ({len(top)} ta top e)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
