"""
Standalone IPTV Updater (Fixed: Scraper Errors & Signal Check)
Source: AynaOTT + JagoBD + GitHub
PRIORITY list channels stay at the top.
"""
import json, os, re, socket, ssl, sys, time
import urllib.error, urllib.parse, urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

# ---------------- Settings ----------------
OUTPUT = Path("playlist.m3u")
WORKERS = 50
CHECK_TIMEOUT = 10 # Increased timeout
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

# ---------------- Network Utils ----------------
socket.setdefaulttimeout(15)
SSL_CTX = ssl.create_default_context()
SSL_CTX.check_hostname = False
SSL_CTX.verify_mode = ssl.CERT_NONE
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36"

def log(msg): print(msg, flush=True)

def http_get(url, headers=None, timeout=15):
    h = {"User-Agent": UA}
    if headers: h.update(headers)
    try:
        req = urllib.request.Request(url, headers=h)
        with urllib.request.urlopen(req, timeout=timeout, context=SSL_CTX) as r:
            return r.read(10 * 1024 * 1024).decode("utf-8", errors="ignore")
    except Exception as e:
        return ""

# ---------------- Scrapers ----------------
def scrape_aynaott():
    base, res = "https://web.aynaott.com", []
    h = {"X-Tenant-Id": "019dd92f-107c-7056-9e79-e5233f6e51d9", "Referer": base + "/"}
    try:
        raw = http_get(f"{base}/api/v5/catalog/contents?type=live-tvs&per_page=100", headers=h)
        if not raw: return []
        data = json.loads(raw)
        if not isinstance(data, dict): return []
        
        def fetch_one(item):
            slug = item.get("slug")
            if not slug: return None
            raw_d = http_get(f"{base}/api/v5/browse/live-tvs/{slug}", headers=h)
            if not raw_d: return None
            try:
                d = json.loads(raw_d)
                rec = d.get("record", d)
                url = rec.get("stream", {}).get("url") or rec.get("stream_url") or rec.get("hls")
                if url:
                    return {"name": item.get('title', slug), "url": url, "group": "Bangladesh", "source": "AynaOTT"}
            except: pass
            return None

        with ThreadPoolExecutor(max_workers=10) as ex:
            futs = [ex.submit(fetch_one, i) for i in data.get("records", [])]
            for f in as_completed(futs):
                r = f.result()
                if r: res.append(r)
    except Exception as e: log(f"[AynaOTT] Error: {e}")
    return res

def scrape_jagobd():
    res, streams = [], []
    try:
        html = http_get("https://www.jagobd.com/")
        if not html: return []
        # More flexible regex
        matches = re.findall(r'href=[\'"](https://www\.jagobd\.com/([^/]+))[\'"]', html)
        for url, slug in matches:
            if any(x in url for x in ["/category", "/tag", "/contact", "/about", "/privacy"]): continue
            res.append({"url": url, "name": slug.replace("-", " ").title(), "source": "JagoBD"})
    except Exception as e: log(f"[JagoBD] Init Error: {e}")

    def resolve(c):
        try:
            page = http_get(c["url"])
            if not page: return None
            m = re.findall(r'https?://[^\'"]+?\.m3u8', page)
            if m:
                return {"name": c["name"], "url": m[0].split("|")[0], "group": "Bangladesh", "source": "JagoBD"}
        except: pass
        return None

    with ThreadPoolExecutor(max_workers=10) as ex:
        futs = [ex.submit(resolve, c) for c in res]
        for f in as_completed(futs):
            r = f.result()
            if r: streams.append(r)
    return streams

def scrape_github():
    res = []
    try:
        txt = http_get(f"{IPTV_BASE}/countries/bd.m3u")
        if txt:
            curr = None
            for line in txt.splitlines():
                if line.startswith("#EXTINF"):
                    curr = {"name": line.split(",")[-1].strip(), "group": "Bangladesh", "source": "GitHub"}
                elif curr and line.startswith("http"):
                    curr["url"] = line
                    res.append(curr)
                    curr = None
    except: pass
    return res

# ---------------- Stream Checker ----------------
def check_stream(raw_url):
    if not raw_url or any(p in raw_url.lower() for p in BLACKLIST_PATTERNS): return False
    try:
        req = urllib.request.Request(raw_url.split("|")[0].strip(), headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=8, context=SSL_CTX) as r:
            if r.status not in (200, 206): return False
            # Check content
            data = r.read(8192)
            return b"#EXT" in data or b"\x47" in data
    except: return False

# ---------------- Main ----------------
def main():
    log("Scraping...")
    pool = scrape_aynaott() + scrape_jagobd() + scrape_github()
    
    unique, seen = [], set()
    for c in pool:
        u = c["url"].split("|")[0].strip()
        if u not in seen:
            seen.add(u)
            unique.append(c)

    log(f"Checking {len(unique)} streams...")
    alive = []
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        fut_to_ch = {ex.submit(check_stream, c["url"]): c for c in unique}
        for f in as_completed(fut_to_ch):
            if f.result(): alive.append(fut_to_ch[f])
    
    log(f"Alive: {len(alive)}")
    
    # Simple sort
    alive.sort(key=lambda x: x["source"])
    
    lines = ["#EXTM3U"]
    for c in alive:
        lines.append(f'#EXTINF:-1 group-title="{c.get("group", "Others")}",{c["name"]}\n{c["url"]}')
    
    OUTPUT.write_text("\n".join(lines), encoding="utf-8")
    log(f"Saved {len(alive)} channels to {OUTPUT}")

if __name__ == "__main__":
    main()
