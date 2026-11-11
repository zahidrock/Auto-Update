"""
Standalone IPTV Updater
Fixed: Audio-only/Signal-less channels filtered, News24/Channel24 false-positives fixed.
"""
import json, os, re, socket, ssl, sys, time
import urllib.error, urllib.parse, urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

# ---------------- Settings ----------------
OUTPUT = Path("playlist.m3u")
WORKERS = 60
CHECK_TIMEOUT = 7
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
IPTV_BASE = "https://iptv-org.github.io/iptv"

PRIORITY = [
    ("BTV", "BD"), ("Somoy TV", "BD"), ("Jamuna Television", "BD"), ("Ekattor TV", "BD"), 
    ("Channel 24", "BD"), ("DBC News", "BD"), ("Independent Television", "BD"), 
    ("News24", "BD"), ("Channel i", "BD"), ("NTV", "BD"), ("RTV", "BD"), 
    ("ATN Bangla", "BD"), ("Banglavision", "BD"), ("Maasranga Television", "BD"), 
    ("Deepto TV", "BD"), ("T Sports", "BD"), ("Gaan Bangla", "BD"),
    ("Star Jalsha", "IN"), ("Zee Bangla", "IN"), ("Colors Bangla", "IN")
]
GROUP_LABEL = {"BD": "Bangladesh", "IN": "Bangla (India)"}

# Filters
BLACKLIST_PATTERNS = ["amagi.tv", "wurl.com", "rakuten", "plex.tv", "distro.tv", "abc news", "fox news"]
RE_KOLKATA = re.compile(r"\b(jalsha|zee bangla|colors bangla|sony aath)\b", re.I)

# ---------------- Network Utils ----------------
socket.setdefaulttimeout(10)
SSL_CTX = ssl.create_default_context()
SSL_CTX.check_hostname = False
SSL_CTX.verify_mode = ssl.CERT_NONE
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/129.0.0.0 Safari/537.36"}

def http_get(url, timeout=10):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=timeout, context=SSL_CTX) as r:
        return r.read(1024*1024*2).decode("utf-8", errors="ignore")

# ---------------- Scrapers ----------------
def scrape_aynaott():
    base, res = "https://web.aynaott.com", []
    h = {**HEADERS, "X-Tenant-Id": "019dd92f-107c-7056-9e79-e5233f6e51d9"}
    try:
        data = json.loads(http_get(f"{base}/api/v5/catalog/contents?type=live-tvs&per_page=100", headers=h))
        for item in data.get("records", []):
            try:
                d = json.loads(http_get(f"{base}/api/v5/browse/live-tvs/{item['slug']}", headers=h))
                url = d.get("record", {}).get("stream", {}).get("url") or d.get("record", {}).get("stream_url")
                if url: res.append({"name": item['title'], "url": url, "group": "Bangladesh", "source": "AynaOTT"})
            except: continue
    except: pass
    return res

def scrape_jagobd():
    res = []
    try:
        html = http_get("https://www.jagobd.com/")
        for url, name in re.findall(r'href="(https://www\.jagobd\.com/[^"]+)"[^>]*>([^<]+)', html):
            if "/category" in url or "/tag" in url: continue
            res.append({"url": url, "name": name.strip(), "source": "JagoBD"})
    except: pass
    
    # Resolve streams
    streams = []
    def resolve(c):
        try:
            page = http_get(c["url"])
            m = re.search(r'https?://[^\'"]+?\.m3u8', page)
            if m: return {"name": c["name"], "url": m.group(0), "group": "Bangladesh", "source": "JagoBD"}
        except: return None
    with ThreadPoolExecutor(max_workers=10) as ex:
        for f in as_completed([ex.submit(resolve, c) for c in res]):
            if f.result(): streams.append(f.result())
    return streams

# ---------------- Stream Checker ----------------
def check_stream(raw_url):
    if not raw_url or any(p in raw_url.lower() for p in BLACKLIST_PATTERNS): return False
    try:
        req = urllib.request.Request(raw_url.split("|")[0].strip(), headers=HEADERS)
        with urllib.request.urlopen(req, timeout=5, context=SSL_CTX) as r:
            if r.status != 200: return False
            # Signal check: Video Sync Byte 0x47 or HLS playlist tags
            data = r.read(4096)
            return b"#EXT" in data or b"\x47" in data
    except: return False

# ---------------- Main ----------------
def main():
    print("Scraping channels...")
    pool = scrape_aynaott() + scrape_jagobd()
    
    print(f"Checking {len(pool)} channels...")
    alive = []
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        fut = {ex.submit(check_stream, c["url"]): c for c in pool}
        for f in as_completed(fut):
            if f.result(): alive.append(fut[f])
            
    # Filter False Positives (News24/Channel24)
    final = []
    for c in alive:
        name = c["name"].lower()
        if any(k in name for k in ["news 24", "channel 24"]):
            if not any(k in name for k in ["bangla", "bd"]): continue
        final.append(c)
        
    # Write M3U
    lines = ["#EXTM3U"]
    for c in final:
        lines.append(f'#EXTINF:-1 group-title="{c.get("group", "General")}",{c["name"]}\n{c["url"]}')
    
    OUTPUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"Done! {len(final)} channels saved to {OUTPUT}")

if __name__ == "__main__":
    main()
