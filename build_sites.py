import gzip, csv, os, collections, json
import pandas as pd
import tldextract

BASE = os.path.dirname(os.path.abspath(__file__))
ext = tldextract.TLDExtract(suffix_list_urls=())

# Global top 50K origins (buckets 1000, 5000, 10000, 50000)
rows = []
with gzip.open(f"{BASE}/crux/data/global/202608.csv.gz", "rt") as f:
    for r in csv.DictReader(f):
        rk = int(r["rank"])
        if rk <= 50000:
            rows.append((r["origin"], rk))
print("global top50k origins:", len(rows))
top = dict(rows)

# Per-country buckets for these origins
cdir = f"{BASE}/crux/data/country"
best = collections.defaultdict(dict)  # origin -> {cc: rank}
for cc in sorted(os.listdir(cdir)):
    p = f"{cdir}/{cc}/202608.csv.gz"
    if not os.path.exists(p):
        continue
    with gzip.open(p, "rt") as f:
        for r in csv.DictReader(f):
            o = r["origin"]
            if o in top:
                best[o][cc] = int(r["rank"])

# Country ccTLD map (ccTLD -> ISO2), excluding TLDs widely used generically
GENERIC_CCTLD = {"io", "co", "tv", "me", "ai", "ly", "fm", "gg", "to", "cc", "ws", "la", "sh", "app", "so", "vc", "gd", "am", "su", "nu", "tk", "ml", "ga", "cf", "gq", "pw", "cx", "ms", "st", "lol", "bz", "xyz", "eu"}
def cc_from_suffix(suffix):
    last = suffix.split(".")[-1].lower()
    if len(last) != 2 or last in GENERIC_CCTLD:
        return None
    if last == "uk":
        return "gb"
    return last

# Approx. internet users (millions), used to weight per-country rank buckets
USERS = dict(cn=1050, in_=900, us=310, id=220, br=180, ru=130, jp=115, ng=110, mx=100, bd=90, pk=90, de=78, ph=85, vn=80, tr=75, eg=80, ir=75, gb=66, fr=60, th=60, it=52, kr=50, es=45, co=40, ar=40, pl=33, ca=36, ua=30, sa=35, za=40, ma=33, dz=30, my=30, ke=25, au=25, pe=25, tw=22, iq=30, ve=20, et=25, uz=25, tz=20, cl=17, nl=17, sd=15, gh=18, ro=17, kz=18, np=15, af=10, mm=25, lk=10, ec=13, cm=12, sy=10, au_=0, be=11, cz=10, gr=9, pt=9, se=10, hu=9, ae=10, il=9, ch=8, at=8, by=8, hk=7, sg=5.5, dk=5.8, fi=5.3, no=5.4, nz=4.9, ie=4.8, rs=6, jo=9, tn=8, ye=8, bo=8, gt=10, do_=9, cu=8, hn=6, py=6, sv=4, ni=4, cr=4.5, pa=3.5, uy=3, az=8, ao=12, ug=12, zm=6, zw=5, sn=10, ci=10, mz=8, mg=6, kh=13, la=4, mn=2.6, kg=5, tj=5, tm=2, ge=3, am=2.5, lb=5, kw=4.5, qa=2.9, om=4.5, bh=1.6, ps=4, ly=5, bg=5.5, hr=3.5, sk=5, si=1.9, lt=2.6, lv=1.7, ee=1.3, ba=2.8, mk=1.7, al=2.3, me=0.55, md=2.3, xk=1.7, cy=1.1, is_=0.38)
USERS = {k.rstrip("_"): v for k, v in USERS.items()}
# Tiebreak order by approximate Chrome usage / web population
TIE = ["us", "in", "br", "id", "jp", "de", "gb", "fr", "mx", "ru", "it", "es", "tr", "kr", "vn", "ph", "ca", "pl", "th", "ar", "co", "eg", "ng", "pk", "au", "nl", "sa", "my", "tw", "ua"]
tie_rank = {c: i for i, c in enumerate(TIE)}

out = []
for origin, rk in rows:
    host = origin.split("://", 1)[1]
    e = ext(host)
    reg = e.registered_domain or host
    cmap = best.get(origin, {})
    cc_tld = cc_from_suffix(e.suffix) if e.suffix else None
    n_top10k = sum(1 for v in cmap.values() if v <= 10000)
    primary, method = None, ""
    if cc_tld:
        primary, method = cc_tld, "ccTLD"
    elif cmap:
        # estimated traffic share ~ internet users / rank bucket
        scored = sorted(cmap.items(), key=lambda kv: (-USERS.get(kv[0], 1.0) / kv[1], tie_rank.get(kv[0], 999)))
        primary = scored[0][0]
        method = "CrUX country ranks (weighted by internet users)"
    out.append(dict(origin=origin, host=host, registered_domain=reg, crux_bucket=rk,
                    country=(primary or "").upper(), country_method=method,
                    countries_top10k=n_top10k,
                    global_reach=("Global" if n_top10k >= 40 else "Multi-country" if n_top10k >= 5 else "Local"),
                    country_buckets=json.dumps(dict(sorted(cmap.items(), key=lambda kv: kv[1])))))
df = pd.DataFrame(out)
df.to_csv(f"{BASE}/sites.csv", index=False)
print(df.crux_bucket.value_counts())
print(df.country.value_counts().head(25))
print(df.country_method.str.split(" \\(").str[0].value_counts())
