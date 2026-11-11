"""
Standalone IPTV updater (Fixed Name Matching & False Positive Issues).
Source: AynaOTT + JagoBD + GitHub (BD, IN, PK, Movies/Music) -> dead check -> shudhu alive rakhbe.
PRIORITY list er channel gula playlist er sobar upore thakbe (oi order e).
"""
import json
import os
import re
import socket
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

# ------------------------------------------------------------------ settings
OUTPUT = Path("playlist.m3u")
WORKERS = 60                 
CHECK_TIMEOUT = 8            
MAX_LINKS_PER_PRIORITY = 1   
MAX_LINKS_PER_CHANNEL = 1    
MIN_KEEP_RATIO = 0.5         
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")

IPTV_BASE = "https://iptv-org.github.io/iptv"

COUNTRY_SOURCES = [
    ("Bangladesh", f"{IPTV_BASE}/countries/bd.m3u"),
    ("India",      f"{IPTV_BASE}/countries/in.m3u"),
    ("Pakistan",   f"{IPTV_BASE}/countries/pk.m3u"),
]

COMBOS = [
    ("Kolkata Movies", "movies", "ben"),
    ("Hindi Movies",   "movies", "hin"),
    ("English Movies", "movies", "eng"),
    ("Hindi Music",    "music",  "hin"),
    ("English Music",  "music",  "eng"),
    ("Bangla Music",   "music",  "ben"),
    ("Sports",         "sports", ("hin", "eng", "ben")),
]

EXTRA_PLAYLISTS = [
    "https://raw.githubusercontent.com/zahidrock/zahid/refs/heads/main/tv.m3u8",
    "https://raw.githubusercontent.com/abusaeeidx/Mrgify-BDIX-IPTV/refs/heads/main/playlist.m3u",
    "https://raw.githubusercontent.com/saeidrahmanbd/BDIX-IPTV/main/International-Playlist.m3u",
]

USE_GITHUB_SEARCH = True

GROUP_ORDER = [
    "Kolkata Movies", "Hindi Movies", "English Movies", "Hindi Music", "English Music",
    "Bangla Music", "Sports",
    "Bangladesh", "Bangla (India)", "India", "Pakistan"
]

PRIORITY = [
    ("BTV", "BD"), ("BTV World", "BD"), ("BTV Chattogram", "BD"), ("Somoy TV", "BD"),
    ("Jamuna Television", "BD"), ("Ekattor TV", "BD"), ("Channel 24", "BD"), ("DBC News", "BD"),
    ("Independent Television", "BD"), ("ATN News", "BD"), ("News24", "BD"),
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

# Filters to prevent false positives (News 24 International, etc)
BLOCK_WORDS = ["xxx", "adult", "porn", "18+", "erotic", "sex", "abc news", "fox news", "nbc news", "sky news", "france 24"]
BLOCK_REGEX = re.compile(rf"\b(?:{'|'.join(re.escape(w) for w in BLOCK_WORDS)})\b", re.I)

# List of domains/patterns that often host unrelated international streams
BLACKLIST_URL_PATTERNS = [
    "amagi.tv", "wurl.com", "rakuten", "plex.tv", "distro.tv", "freeview"
]

RE_KOLKATA = re.compile(r"\b(jalsha movies|zee bangla cinema|colors bangla cinema|bangla cinema|"
                        r"bangla movies?|bengali movies?|bengali cinema)\b", re.I)
RE_MUSIC = re.compile(r"\b(music|song|songs|gaan|mtv|sangeet)\b", re.I)
RE_MOVIE = re.compile(r"\b(movie|movies|cinema|film|films|flix|hbo|bollywood|hollywood)\b", re.I)
RE_SPORT = re.compile(r"\b(sport|sports|cricket|football)\b", re.I)
RE_BN = re.compile(r"\b(bangla|bengali)\b", re.I)
RE_HI = re.compile(r"\b(hindi|bollywood)\b", re.I)
RE_EN = re.compile(r"\b(english|hollywood|hbo)\b", re.I)
RE_BD_MUSIC = re.compile(r"\b(music|gaan|song|sangeet)\b", re.I)

RE_ATTR_NAME = re.compile(r'tvg-name="([^"]*)"', re.I)
RE_ATTR_ID = re.compile(r'tvg-id="([^"]*)"', re.I)
RE_ATTR_LOGO = re.compile(r'tvg-logo="([^"]*)"', re.I)
RE_ATTR_GROUP = re.compile(r'group-title="([^"]*)"', re.I)

# ------------------------------------------------------------------ http
socket.setdefaulttimeout(CHECK_TIMEOUT + 4)
SSL_CTX = ssl.create_default_context()
SSL_CTX.check_hostname = False
SSL_CTX.verify_mode = ssl.CERT_NONE
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/129.0.0.0 Safari/537.36")
HEADERS = {"User-Agent": UA, "Accept": "*/*", "Accept-Language": "en-US,en;q=0.9"}

def log(msg):
    print(msg, flush=True)

def http_get(url, headers=None, timeout=15):
    h = {**HEADERS, **(headers or {})}
    req = urllib.request.Request(url, headers=h)
    with urllib.request.urlopen(req, timeout=timeout, context=SSL_CTX) as r:
        raw_bytes = r.read(10 * 1024 * 1024)
        return raw_bytes.decode("utf-8", errors="ignore")

# ------------------------------------------------------------------ m3u parse
def parse_m3u(text, source):
    out, meta = [], None
    for line in text.splitlines():
        line = line.strip()
        if not line: continue
        if line.startswith("#EXTINF"):
            m_id = RE_ATTR_ID.search(line)
            m_name = RE_ATTR_NAME.search(line)
            m_logo = RE_ATTR_LOGO.search(line)
            m_group = RE_ATTR_GROUP.search(line)
            tvg_id = m_id.group(1).strip() if m_id else ""
            tvg_name = m_name.group(1).strip() if m_name else ""
            logo = m_logo.group(1).strip() if m_logo else ""
            group = m_group.group(1).strip() if m_group else "Others"
            name = line.rsplit(",", 1)[-1].strip() if "," in line else tvg_name
            meta = {"name": name or tvg_name or "Unknown", "tvg_id": tvg_id,
                    "logo": logo, "group": group or "Others", "source": source}
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
    for group, cat, lang in COMBOS:
        langs = (lang,) if isinstance(lang, str) else lang
        lang_urls = {c["url"].split("|")[0] for lg in langs for c in get(f"{IPTV_BASE}/languages/{lg}.m3u")}
        n = 0
        for c in get(f"{IPTV_BASE}/categories/{cat}.m3u"):
            if c["url"].split("|")[0] in lang_urls:
                res.append({**c, "group": group})
                n += 1
        log(f"[GitHub] {group}: {n} channel")

    for group, url in COUNTRY_SOURCES:
        res.extend({**c, "group": "Sports" if "sport" in c["group"].lower() else group} for c in get(url))

    for url in EXTRA_PLAYLISTS:
        res.extend(get(url))

    if USE_GITHUB_SEARCH and GITHUB_TOKEN:
        h = {"User-Agent": UA, "Accept": "application/vnd.github+json", "Authorization": f"Bearer {GITHUB_TOKEN}", "Referer": "https://github.com/"}
        raws = []
        for page in (1, 2, 3):
            try:
                api = ("https://api.github.com/search/code?q=" + urllib.parse.quote("EXTINF extension:m3u") + f"&per_page=50&page={page}")
                data = json.loads(http_get(api, headers=h, timeout=20))
                for it in data.get("items", []):
                    raws.append(it["html_url"].replace("https://github.com/", "https://raw.githubusercontent.com/").replace("/blob/", "/"))
                time.sleep(7)
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
            except Exception: pass
        log(f"[GitHub search] {len(raws)} file theke {found} channel")
    return res

def scrape_aynaott():
    base = "https://web.aynaott.com"
    h = {"User-Agent": UA, "X-Tenant-Id": "019dd92f-107c-7056-9e79-e5233f6e51d9", "Referer": "https://web.aynaott.com/"}
    catalog, seen = [], set()
    for page in range(1, 20):
        try:
            data = json.loads(http_get(f"{base}/api/v5/catalog/contents?type=live-tvs&per_page=100&page={page}", headers=h, timeout=15))
            recs = data.get("records", [])
            if not recs: break
            for r in recs:
                s = str(r.get("slug", "")).strip()
                if s and s not in seen:
                    seen.add(s); catalog.append(r)
            if len(recs) < 100: break
        except Exception: break
    log(f"[AynaOTT] catalog: {len(catalog)}")

    def one(item):
        slug, title = item.get("slug", ""), item.get("title", "")
        try:
            d = json.loads(http_get(f"{base}/api/v5/browse/live-tvs/{slug}", headers=h, timeout=12))
            rec = d.get("record", d)
            url = rec.get("stream", {}).get("url") or rec.get("stream_url") or rec.get("hls") or ""
            if url:
                return {"name": title, "url": url, "logo": item.get("images", {}).get("thumbnail_url", ""), "tvg_id": f"aynaott-{slug}", "group": "Bangladesh", "source": "AynaOTT"}
        except Exception: pass
        return None

    res = []
    with ThreadPoolExecutor(max_workers=10) as ex:
        for f in as_completed([ex.submit(one, i) for i in catalog]):
            r = f.result()
            if r: res.append(r)
    return res

def scrape_jagobd():
    res = []
    try:
        html = http_get("https://www.jagobd.com/", timeout=15)
        seen = set()
        for url, content in re.findall(r'<a\s+[^>]*href=[\'"](https://www\.jagobd\.com/[^\'"#?]+)[\'"][^>]*>(.*?)</a>', html, re.S):
            url = url.rstrip("/")
            if url in seen or "/category" in url or "/tag" in url: continue
            seen.add(url)
            slug = url.split("/")[-1]
            res.append({"slug": slug, "url": url, "name": slug.replace("-", " ").title(), "source": "JagoBD"})
    except Exception: pass

    def resolve(c):
        try:
            page = http_get(c["url"], timeout=12)
            m = re.findall(r'[\'"](https?://[^\'"]+?\.m3u8[^\'"]*)[\'"]', page)
            if m:
                clean = m[0].split("|")[0]
                return {"name": c["name"], "url": clean, "group": "Bangladesh", "source": "JagoBD"}
        except Exception: pass
        return None

    streams = []
    with ThreadPoolExecutor(max_workers=10) as ex:
        for f in as_completed([ex.submit(resolve, c) for c in res]):
            r = f.result()
            if r: streams.append(r)
    return streams

# ------------------------------------------------------------------ check
def check_stream(raw_url):
    if not raw_url: return False, 0
    if any(p in raw_url.lower() for p in BLACKLIST_URL_PATTERNS):
        return False, 0
        
    headers, url = dict(HEADERS), raw_url.strip()
    if "|" in raw_url:
        url, _ = raw_url.split("|", 1)
        url = url.strip()

    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=CHECK_TIMEOUT, context=SSL_CTX) as r:
            if r.status not in (200, 206): return False, 0
            ctype = r.headers.get("Content-Type", "").lower()
            if "text/html" in ctype: return False, 0
            return True, 1
    except Exception: return False, 0

def check_all(channels):
    alive = []
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        fut = {ex.submit(check_stream, c["url"]): c for c in channels}
        for f in as_completed(fut):
            ok, _ = f.result()
            if ok: alive.append(fut[f])
    return alive

# ------------------------------------------------------------------ matching logic
NOISE = {"hd", "fhd", "sd", "uhd", "4k", "live", "official", "hevc", "h265", "h264"}

def norm(name):
    n = name.lower()
    n = re.sub(r"[\(\[].*?[\)\]]", " ", n)
    n = re.sub(r"\b\d{3,4}p\b", " ", n)
    n = n.replace("television", "tv")
    n = re.sub(r"[^a-z0-9\u0980-\u09ff]+", " ", n)
    return "".join(t for t in n.split() if t not in NOISE)

PRIORITY_MAP = {norm(n): (i, n, c) for i, (n, c) in enumerate(PRIORITY)}

def is_blocked(c):
    t = f'{c["name"]} {c.get("group", "")}'
    if any(k in t.lower() for k in ["news 24", "news24", "channel 24", "channel24"]):
        if c["source"] not in ("AynaOTT", "JagoBD"):
            if not any(k in t.lower() for k in ["bangla", "bd", "bangladesh"]):
                return True
    return bool(BLOCK_REGEX.search(t))

def main():
    pool = []
    for name, fn in (("AynaOTT", scrape_aynaott), ("JagoBD", scrape_jagobd), ("GitHub", scrape_github)):
        try: pool.extend(fn())
        except Exception as e: log(f"[{name}] error: {e}")

    seen, items = set(), []
    for c in pool:
        raw = c["url"].split("|")[0].strip()
        if not raw or raw in seen or is_blocked(c): continue
        
        if RE_KOLKATA.search(c["name"]): c["group"] = "Kolkata Movies"
        elif RE_BN.search(c["name"]) and RE_MUSIC.search(c["name"]): c["group"] = "Bangla Music"
        
        seen.add(raw); items.append(c)

    log(f"Total unique channel: {len(items)}")
    alive = check_all(items)
    log(f"Alive: {len(alive)}")

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
        lst = sorted(buckets[idx], key=lambda x: (0 if x["source"] in ("AynaOTT", "JagoBD") else 1))
        top.extend(lst[:MAX_LINKS_PER_PRIORITY])

    rest = [c for c in rest if c["group"] in GROUP_ORDER]
    rest.sort(key=lambda c: GROUP_ORDER.index(c["group"]) if c["group"] in GROUP_ORDER else 99)

    lines = ["#EXTM3U"]
    for c in top + rest:
        lines.append(f'#EXTINF:-1 tvg-logo="{c.get("logo","")}" group-title="{c["group"]}",{c["name"]}\n{c["url"]}')
    
    OUTPUT.write_text("\n".join(lines), encoding="utf-8")
    log(f"Saved {len(top)+len(rest)} channels to {OUTPUT}")

if __name__ == "__main__":
    main()
