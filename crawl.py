"""Fetch robots.txt and homepage metadata for a shard of origins.

Usage: python crawl.py SHARD NUM_SHARDS
Reads sites.csv (column: origin); writes out/robots_<shard>.jsonl.gz
"""
import asyncio, csv, gzip, json, re, sys, time
import aiohttp

SHARD, NSHARDS = int(sys.argv[1]), int(sys.argv[2])
CONC = 120
UA = "Mozilla/5.0 (compatible; robots-txt-research/1.0; +https://github.com/jomilu93/robots-txt-crawl)"
BROWSER_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0 Safari/537.36"
ROBOTS_MAX = 600_000
HOME_MAX = 400_000

origins = []
with open("sites.csv") as f:
    for i, r in enumerate(csv.DictReader(f)):
        if i % NSHARDS == SHARD:
            origins.append(r["origin"])

def meta(html, name):
    for pat in (rf'<meta[^>]+(?:name|property)\s*=\s*["\']{name}["\'][^>]*content\s*=\s*["\']([^"\']*)',
                rf'<meta[^>]+content\s*=\s*["\']([^"\']*)["\'][^>]*(?:name|property)\s*=\s*["\']{name}["\']'):
        m = re.search(pat, html, re.I | re.S)
        if m:
            return m.group(1).strip()[:500]
    return ""

def text_snippet(html):
    html = re.sub(r"(?is)<(script|style|noscript|svg)[^>]*>.*?</\1>", " ", html)
    body = re.search(r"(?is)<body[^>]*>(.*)", html)
    t = re.sub(r"(?s)<[^>]+>", " ", body.group(1) if body else html)
    t = re.sub(r"&[a-z#0-9]+;", " ", t)
    return re.sub(r"\s+", " ", t).strip()[:600]

async def get(session, url, maxb, ua):
    async with session.get(url, headers={"User-Agent": ua, "Accept": "*/*"}, allow_redirects=True, max_redirects=6) as r:
        body = await r.content.read(maxb)
        enc = r.get_encoding() if r.charset else "utf-8"
        try:
            txt = body.decode(enc, errors="replace")
        except LookupError:
            txt = body.decode("utf-8", errors="replace")
        return r.status, str(r.url), r.headers.get("Content-Type", ""), txt

async def one(session, sem, origin):
    rec = {"origin": origin}
    async with sem:
        try:
            st, fu, ct, txt = await get(session, origin + "/robots.txt", ROBOTS_MAX, UA)
            rec.update(robots_status=st, robots_final_url=fu, robots_ctype=ct, robots=txt)
        except Exception as e:
            rec.update(robots_status=-1, robots_error=type(e).__name__ + ": " + str(e)[:200])
        try:
            st, fu, ct, html = await get(session, origin + "/", HOME_MAX, BROWSER_UA)
            m = re.search(r"(?is)<title[^>]*>(.*?)</title>", html)
            lang = re.search(r'(?is)<html[^>]*\blang\s*=\s*["\']?([A-Za-z\-_]+)', html)
            rec.update(home_status=st, home_final_url=fu,
                       title=re.sub(r"\s+", " ", m.group(1)).strip()[:300] if m else "",
                       description=meta(html, "description"), og_title=meta(html, "og:title"),
                       og_site_name=meta(html, "og:site_name"), og_description=meta(html, "og:description"),
                       keywords=meta(html, "keywords"), lang=lang.group(1) if lang else "",
                       snippet=text_snippet(html))
        except Exception as e:
            rec.update(home_status=-1, home_error=type(e).__name__ + ": " + str(e)[:200])
    return rec

async def main():
    sem = asyncio.Semaphore(CONC)
    timeout = aiohttp.ClientTimeout(total=25, connect=10, sock_read=15)
    conn = aiohttp.TCPConnector(limit=CONC, ttl_dns_cache=600, ssl=False)
    t0 = time.time()
    async with aiohttp.ClientSession(timeout=timeout, connector=conn) as session:
        tasks = [one(session, sem, o) for o in origins]
        with gzip.open(f"out/robots_{SHARD:02d}.jsonl.gz", "wt") as out:
            done = 0
            for fut in asyncio.as_completed(tasks):
                out.write(json.dumps(await fut) + "\n")
                done += 1
                if done % 1000 == 0:
                    print(f"{done}/{len(origins)} {time.time()-t0:.0f}s", flush=True)
    print("done", len(origins), f"{time.time()-t0:.0f}s")

asyncio.run(main())
