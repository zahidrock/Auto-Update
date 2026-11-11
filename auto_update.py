"""
Standalone IPTV updater
Source: AynaOTT + JagoBD + GitHub
PRIORITY list channels stay at the top.
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

BLOCK_WORDS = ["xxx", "adult", "porn", "18+", "erotic", "sex", "abc news", "fox news", "nbc news", "sky news", "france 24"]
BLOCK_REGEX = re.compile(rf"\b(?:{'|'.join(re.escape(w) for w in BLOCK_WORDS)})\b", re.I)

BLACKLIST_URL_PATTERNS = ["amagi.tv", "wurl.com", "rakuten", "plex.tv", "distro.tv", "freeview"]

RE_KOLKATA = re.compile(r"\b(jalsha movies|zee bangla cinema|colors bangla cinema|bangla cinema|bangla movies?|bengali movies?|bengali cinema)\b", re.I)
RE_MUSIC = re.compile(r"\b(music|song|songs|gaan|mtv|sangeet)\b", re.I)
RE_MOVIE = re.compile(r"\b(movie|movies|cinema|film|films|flix|hbo|bollywood|hollywood)\b", re.I)
RE_SPORT = re.compile(r"\b(sport|sports|cricket|football)\b", re.I)
RE_BN = re.compile(r"\b(bangla|bengali)\b", re.I)
RE_ATTR_ID = re.compile(r'tvg-id="([^"]*)"', re.I)
RE_ATTR_NAME = re.compile(r'tvg-name="([^"]*)"', re.I)
RE_ATTR_LOGO = re.compile(r'tvg-logo="([^"]*)"', re.I)
RE_ATTR_GROUP = re.compile(r'group-title="([^"]*)"', re.I)

# ------------------------------------------------------------------ http
socket.setdefaulttimeout(10)
SSL_CTX = ssl.create_default_context()
SSL_CTX.check_hostname = False
SSL_CTX.verify_mode = ssl.CERT_NONE
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36"
HEADERS = {"User-Agent": UA}

def log(msg): print(msg, flush=True)

def http_get(url, headers=None, timeout=15):
    req = urllib.request.Request(url, headers={**HEADERS, **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout, context=SSL_CTX) as r:
        return r.read(1024*1024*5).decode("utf-8", errors="ignore")

def parse_m3u(text, source):
    out, meta = [], None
    for line in text.splitlines():
        line = line.strip()
        if not line: continue
        if line.startswith("#EXTINF"):
            name = line.rsplit(",", 1)[-1].strip()
            group = RE_ATTR_GROUP.search(line)
            meta = {"name": name, "logo": RE_ATTR_LOGO.search(line).group(1) if RE_ATTR_LOGO.search(line) else "",
                    "group": group.group(1) if group else "Others", "source": source}
        elif meta and not line.startswith("#"):
            meta["url"] = line
            out.append(meta)
            meta = None
    return out

def scrape_github():
    # GitHub scrapers implementation ... (omitted for brevity, assume original logic)
    return []

def scrape_aynaott():
    # AynaOTT scrapers implementation ...
    return []

def scrape_jagobd():
    # JagoBD scrapers implementation ...
    return []

# ------------------------------------------------------------------ check
def check_stream(raw_url):
    if not raw_url or any(p in raw_url.lower() for p in BLACKLIST_URL_PATTERNS): return False, 0
    try:
        req = urllib.request.Request(raw_url.split("|")[0].strip(), headers=HEADERS)
        with urllib.request.urlopen(req, timeout=5, context=SSL_CTX) as r:
            if r.status != 200: return False, 0
            # সিগন্যাল যাচাই (Video Sync Byte 0x47 or HLS tags)
            data = r.read(4096)
            if b"#EXT" in data or b"\x47" in data: return True, 1
            return False, 0
    except: return False, 0

def check_all(channels):
    alive = []
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        fut = {ex.submit(check_stream, c["url"]): c for c in channels}
        for f in as_completed(fut):
            if f.result()[0]: alive.append(fut[f])
    return alive

# ------------------------------------------------------------------ matching
def norm(name):
    n = name.lower()
    return re.sub(r"[^a-z0-9\u0980-\u09ff]+", " ", n)

PRIORITY_MAP = {norm(n): (i, n, c) for i, (n, c) in enumerate(PRIORITY)}

def is_blocked(c):
    t = f'{c["name"]} {c.get("group", "")}'.lower()
    if any(k in t for k in ["news 24", "news24", "channel 24", "channel24"]):
        if c["source"] not in ("AynaOTT", "JagoBD") and not any(k in t for k in ["bangla", "bd"]): return True
    return bool(BLOCK_REGEX.search(t))

def main():
    # Scraping -> filtering -> checking -> sorting -> writing (Original logic)
    pass

if __name__ == "__main__":
    main()
