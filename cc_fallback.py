"""Recover robots.txt and homepage captures from Common Crawl for sites we couldn't fetch live.

Uses the CDX cluster.idx of the latest crawls with direct range requests to data.commoncrawl.org.
Usage: python cc_fallback.py [limit]
"""
import asyncio, bisect, csv, gzip, io, json, re, sys, time, zlib
import aiohttp

LIMIT = int(sys.argv[1]) if len(sys.argv) > 1 else None
BASE = "https://data.commoncrawl.org/"
CONC = 8
UA = "robots-txt-research/1.0 (+https://github.com/jomilu93/robots-txt-crawl)"


def surt(host, path):
    h = host.lower().split(":")[0]
    if h.startswith("www."):
        h = h[4:]
    return ",".join(reversed(h.split("."))) + ")" + path


async def fetch(session, url, rng=None, tries=8):
    for i in range(tries):
        try:
            hdr = {"User-Agent": UA}
            if rng:
                hdr["Range"] = f"bytes={rng[0]}-{rng[0] + rng[1] - 1}"
            async with session.get(url, headers=hdr) as r:
                STATS[r.status] = STATS.get(r.status, 0) + 1
                if r.status in (200, 206):
                    return await r.read()
                if r.status in (503, 429, 500, 502, 504):
                    await asyncio.sleep(min(60, 2 ** i) + 1)
                    continue
                return None
        except Exception as e:
            STATS[type(e).__name__] = STATS.get(type(e).__name__, 0) + 1
            await asyncio.sleep(2 ** i)
    return None


async def load_cluster(session, crawl):
    raw = await fetch(session, f"{BASE}cc-index/collections/{crawl}/indexes/cluster.idx")
    keys, meta = [], []
    for line in raw.decode().splitlines():
        k, rest = line.split(" ", 1)
        ts, fn, off, ln, _ = rest.split("\t")
        keys.append(k)
        meta.append((fn, int(off), int(ln)))
    return keys, meta


block_cache = {}
FAILED = 0
STATS = {}


async def lookup(session, sem, crawl, cl, key):
    keys, meta = cl
    i = bisect.bisect_left(keys, key) - 1
    i = max(i, 0)
    found = []
    # the key may straddle into the next block; check up to 2 blocks
    for j in (i, i + 1):
        if j >= len(meta):
            break
        fn, off, ln = meta[j]
        ck = (crawl, fn, off)
        if ck not in block_cache:
            async with sem:
                data = await fetch(session, f"{BASE}cc-index/collections/{crawl}/indexes/{fn}", (off, ln))
            if not data:
                global FAILED
                FAILED += 1
                continue
            block_cache[ck] = zlib.decompress(data, 16 + zlib.MAX_WBITS).decode("utf-8", "replace")
        for line in block_cache[ck].splitlines():
            if line.startswith(key + " "):
                found.append(json.loads(line.split(" ", 2)[2]))
        if j + 1 < len(keys) and keys[j + 1] > key:
            break
    return found


def parse_warc(data):
    raw = zlib.decompress(data, 16 + zlib.MAX_WBITS)
    # WARC headers \r\n\r\n HTTP headers \r\n\r\n body
    parts = raw.split(b"\r\n\r\n", 2)
    if len(parts) < 3:
        return None, ""
    http_head = parts[1].decode("latin-1")
    m = re.match(r"HTTP/\S+\s+(\d+)", http_head)
    status = int(m.group(1)) if m else None
    body = parts[2]
    return status, body.decode("utf-8", "replace")


def meta_tag(html, name):
    for pat in (rf'<meta[^>]+(?:name|property)\s*=\s*["\']{name}["\'][^>]*content\s*=\s*["\']([^"\']*)',
                rf'<meta[^>]+content\s*=\s*["\']([^"\']*)["\'][^>]*(?:name|property)\s*=\s*["\']{name}["\']'):
        m = re.search(pat, html, re.I | re.S)
        if m:
            return m.group(1).strip()[:500]
    return ""


async def main():
    rows = list(csv.DictReader(open("fallback.csv")))
    rows.sort(key=lambda r: surt(r["origin"].split("://", 1)[1], "/"))
    if LIMIT:
        rows = rows[::max(1, len(rows) // LIMIT)][:LIMIT]
    timeout = aiohttp.ClientTimeout(total=120)
    async with aiohttp.ClientSession(timeout=timeout, connector=aiohttp.TCPConnector(limit=CONC)) as session:
        info = json.loads(await fetch(session, "https://index.commoncrawl.org/collinfo.json"))
        crawls = [c["id"] for c in info[:3]]
        print("crawls", crawls, flush=True)
        clusters = {c: await load_cluster(session, c) for c in crawls}
        sem = asyncio.Semaphore(CONC)
        t0 = time.time()

        async def best_capture(host, path, want_robots):
            caps = []
            for c in crawls:
                for rec in await lookup(session, sem, c, clusters[c], surt(host, path)):
                    if want_robots and "/robotstxt/" not in rec.get("filename", "") and not rec.get("url", "").endswith("robots.txt"):
                        continue
                    rec["crawl"] = c
                    caps.append(rec)
                if any(r.get("status") == "200" for r in caps):
                    break
            ok = [r for r in caps if r.get("status") == "200"]
            pick = sorted(ok or caps, key=lambda r: r.get("timestamp", ""), reverse=True)
            return pick[0] if pick else None

        async def one(row):
            host = row["origin"].split("://", 1)[1]
            out = {"origin": row["origin"]}
            if row["need_robots"] == "1":
                cap = await best_capture(host, "/robots.txt", True)
                if cap and cap.get("status") in ("301", "302", "307", "308") and cap.get("redirect"):
                    m = re.match(r"https?://([^/]+)(/.*)?", cap["redirect"])
                    if m and (m.group(2) or "/") == "/robots.txt":
                        cap2 = await best_capture(m.group(1), "/robots.txt", True)
                        if cap2:
                            cap = cap2
                if cap:
                    out.update(cc_robots_status=int(cap.get("status", 0) or 0), cc_robots_ts=cap.get("timestamp"), cc_crawl=cap["crawl"],
                               cc_robots_url=cap.get("url"))
                    if cap.get("status") == "200":
                        async with sem:
                            data = await fetch(session, BASE + cap["filename"], (int(cap["offset"]), int(cap["length"])))
                        if data:
                            st, body = parse_warc(data)
                            out["cc_robots"] = body[:600000]
                else:
                    out["cc_robots_status"] = None
            if row["need_home"] == "1":
                cap = await best_capture(host, "/", False)
                if cap and cap.get("status") == "200":
                    async with sem:
                        data = await fetch(session, BASE + cap["filename"], (int(cap["offset"]), int(cap["length"])))
                    if data:
                        st, html = parse_warc(data)
                        m = re.search(r"(?is)<title[^>]*>(.*?)</title>", html)
                        lang = re.search(r'(?is)<html[^>]*\blang\s*=\s*["\']?([A-Za-z\-_]+)', html)
                        out.update(cc_title=re.sub(r"\s+", " ", m.group(1)).strip()[:300] if m else "",
                                   cc_description=meta_tag(html, "description") or meta_tag(html, "og:description"),
                                   cc_site_name=meta_tag(html, "og:site_name"), cc_lang=lang.group(1) if lang else "")
            return out

        n = 0
        with gzip.open("results/cc_fallback.jsonl.gz", "wt") as f:
            for fut in asyncio.as_completed([one(r) for r in rows]):
                f.write(json.dumps(await fut) + "\n")
                n += 1
                if n % 500 == 0:
                    print(n, len(rows), f"{time.time()-t0:.0f}s", "blocks", len(block_cache), "failed", FAILED, STATS, flush=True)
                    if len(block_cache) > 600:
                        block_cache.clear()
    print("done", n, STATS)

asyncio.run(main())
