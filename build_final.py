import sys, glob, gzip, json, re, collections, html
import numpy as np, pandas as pd, scipy.sparse as sp
sys.path.insert(0, '/home/claude/robots-txt-crawl')
sys.path.insert(0, '/tmp/claude-0/-home-claude/6c55c4bd-efa3-5ed9-a3f2-bd0d0dd5339b/scratchpad')
from robots_eval import parse, evaluate, CRAWLERS, looks_like_html
from labtools import load_labels, load_emb, SP, R
import tldextract

ext = tldextract.TLDExtract(suffix_list_urls=())
sites = pd.read_csv(f'{SP}/sites.csv')

# ---------- load crawl data ----------
live = {}
for p in glob.glob(f'{R}/robots_*.jsonl.gz'):
    for l in gzip.open(p, 'rt'):
        r = json.loads(l); live[r['origin']] = r
cc = {}
for p in glob.glob(f'{R}/cc/cc_*.jsonl.gz'):
    for l in gzip.open(p, 'rt'):
        r = json.loads(l); cc[r['origin']] = r
print('live', len(live), 'cc', len(cc))

CHAL = re.compile(r"just a moment|access denied|attention required|captcha|ddos|forbidden|verificati|cloudflare|not acceptable|security check|blocked|robot check|are you a robot|incapsula|perimeterx|request rejected", re.I)
BLOCKY = {401, 403, 405, 406, 407, 429}

def robots_text(o):
    """Return (text or None, source label). text '' means 'no robots.txt => everything allowed'."""
    r = live.get(o, {})
    s = r.get('robots_status')
    body = r.get('robots') or ''
    if s and 200 <= s < 300:
        if not looks_like_html(body):
            return body, 'Live fetch'
        if not CHAL.search(body[:3000]):
            return '', 'Live fetch (no robots.txt: HTML page returned)'
    elif s and 400 <= s < 500 and s not in BLOCKY:
        return '', f'Live fetch (no robots.txt: HTTP {s})'
    c = cc.get(o, {})
    cs = c.get('cc_robots_status')
    if c.get('cc_robots') is not None and cs == 200:
        b = c['cc_robots']
        if looks_like_html(b):
            return '', f"Common Crawl {c.get('cc_crawl','')} (no robots.txt: HTML page)"
        return b, f"Common Crawl {c.get('cc_crawl','')}"
    if cs in (404, 410):
        return '', f"Common Crawl {c.get('cc_crawl','')} (no robots.txt: HTTP {cs})"
    why = f'HTTP {s}' if s and s > 0 else (r.get('robots_error', 'error').split(':')[0] if r else 'not fetched')
    return None, f'No data (live: {why}; Common Crawl: {cs if cs else "no capture"})'

cols = [c for c, _, _ in CRAWLERS]
rows = []
for o in sites.origin:
    txt, src = robots_text(o)
    rec = {'origin': o, 'robots_source': src}
    if txt is None:
        for c in cols: rec[c] = None
        rec['All bots (*)'] = None
        rec['named_tokens'] = ''
    else:
        g = parse(txt)
        for c, co, toks in CRAWLERS:
            rec[c] = int(evaluate(g, toks)[0])
        rec['All bots (*)'] = int(evaluate(g, [])[0])
        rec['named_tokens'] = ','.join(sorted(k for k in g if k != '*'))[:300]
    rows.append(rec)
rob = pd.DataFrame(rows)
print(rob.robots_source.str.split(' \\(').str[0].str.split(' CC').str[0].value_counts().head(10))

# ---------- Tranco ----------
tr = pd.read_csv(f'{R}/tranco_top1m.csv.gz', header=None, names=['rank', 'domain'])
trank = dict(zip(tr.domain, tr['rank']))
def tranco(host, reg):
    h = host[4:] if host.startswith('www.') else host
    return trank.get(h) or trank.get(reg)
sites['tranco_rank'] = [tranco(h, r) for h, r in zip(sites.host, sites.registered_domain)]

# ---------- country (Chrome-user weighted) ----------
USERS = dict(in_=900, us=310, id=220, br=180, ru=130, jp=115, ng=110, mx=100, bd=90, pk=90, de=78, ph=85, vn=80, tr=75, eg=80, ir=75, gb=66, fr=60, th=60, it=52, kr=50, es=45, co=40, ar=40, pl=33, ca=36, ua=30, sa=35, za=40, ma=33, dz=30, my=30, ke=25, au=25, pe=25, tw=22, iq=30, ve=20, et=25, uz=25, tz=20, cl=17, nl=17, sd=15, gh=18, ro=17, kz=18, np=15, af=10, mm=25, lk=10, ec=13, cm=12, sy=10, be=11, cz=10, gr=9, pt=9, se=10, hu=9, ae=10, il=9, ch=8, at=8, by=8, hk=7, sg=5.5, dk=5.8, fi=5.3, no=5.4, nz=4.9, ie=4.8, rs=6, jo=9, tn=8, ye=8, bo=8, gt=10, do_=9, cu=8, hn=6, py=6, sv=4, ni=4, cr=4.5, pa=3.5, uy=3, az=8, ao=12, ug=12, zm=6, zw=5, sn=10, ci=10, mz=8, mg=6, kh=13, la=4, mn=2.6, kg=5, tj=5, tm=2, ge=3, am=2.5, lb=5, kw=4.5, qa=2.9, om=4.5, bh=1.6, ps=4, ly=5, bg=5.5, hr=3.5, sk=5, si=1.9, lt=2.6, lv=1.7, ee=1.3, ba=2.8, mk=1.7, al=2.3, me=0.55, md=2.3, xk=1.7, cy=1.1, is_=0.38, cn=1050)
CHROME_SHARE = dict(cn=0.06, kr=0.45, jp=0.5, ru=0.45, us=0.55, ir=0.5, vn=0.6)
W = {k.rstrip('_'): v * CHROME_SHARE.get(k.rstrip('_'), 0.68) for k, v in USERS.items()}
GENERIC_CCTLD = {"io", "co", "tv", "me", "ai", "ly", "fm", "gg", "to", "cc", "ws", "la", "sh", "so", "vc", "gd", "am", "su", "nu", "tk", "ml", "ga", "cf", "gq", "pw", "cx", "ms", "st", "bz", "eu", "is", "lol", "ph"[:0]}
ISO = {}
try:
    import pycountry
    ISO = {c.alpha_2.lower(): c.name for c in pycountry.countries}
except Exception:
    pass
ISO.update({'gb': 'United Kingdom', 'xk': 'Kosovo', 'kr': 'South Korea', 'ru': 'Russia', 'ir': 'Iran', 'tw': 'Taiwan', 'vn': 'Vietnam', 'bo': 'Bolivia', 've': 'Venezuela', 'tz': 'Tanzania', 'sy': 'Syria', 'md': 'Moldova', 'la': 'Laos', 'kp': 'North Korea', 'cd': 'DR Congo', 'ps': 'Palestine'})
cmaps = [json.loads(x) for x in sites.country_buckets]
country, method, top3 = [], [], []
for h, cm in zip(sites.host, cmaps):
    e = ext(h); last = e.suffix.split('.')[-1].lower() if e.suffix else ''
    cc_tld = ('gb' if last == 'uk' else last) if (len(last) == 2 and last not in GENERIC_CCTLD) else None
    scored = sorted(cm.items(), key=lambda kv: -W.get(kv[0], 0.7) / kv[1])
    t3 = ', '.join(k.upper() for k, _ in scored[:3])
    top3.append(t3)
    if cc_tld:
        country.append(cc_tld); method.append('Country-code domain')
    elif scored:
        country.append(scored[0][0]); method.append('Chrome traffic (CrUX country lists)')
    else:
        country.append(''); method.append('')
sites['country_code'] = [c.upper() for c in country]
sites['country'] = [ISO.get(c, c.upper()) for c in country]
sites['country_method'] = method
sites['top_markets'] = top3

# ---------- categories ----------
CODES = {'NW': 'News', 'TE': 'Technology', 'AI': 'AI Tools & Chatbots', 'ED': 'Education', 'SH': 'Shopping', 'GA': 'Gaming', 'GV': 'Government',
         'FI': 'Personal Finance', 'AD': 'Adult', 'VS': 'Video & Streaming', 'EN': 'Entertainment', 'AM': 'Anime, Manga & Comics', 'CM': 'Communication',
         'TR': 'Travel', 'RF': 'Reference', 'HE': 'Health', 'SP': 'Sports', 'SM': 'Social Media', 'AU': 'Automotive', 'AR': 'Art & Design', 'MU': 'Music',
         'FD': 'Food & Drink', 'SE': 'Search', 'EV': 'Events', 'JO': 'Jobs', 'RE': 'Real Estate', 'DI': 'DIY & Home Improvement', 'HT': 'How-To & Tutorials',
         'PA': 'Parenting', 'GB': 'Gambling & Lottery', 'DT': 'Dating', 'BS': 'Business & Professional Services', 'PR': 'Productivity & Workplace Tools',
         'FS': 'File Sharing & Downloads', 'RL': 'Religion', 'WE': 'Weather', 'BK': 'Books & Literature', 'LF': 'Lifestyle & Fashion', 'SC': 'Science',
         'UT': 'Utilities & Telecom', 'XX': 'Unclassified / Parked'}
lab = load_labels()
E, O = load_emb(); eidx = {o: i for i, o in enumerate(O)}

def text_of(o):
    r = live.get(o, {}); c = cc.get(o, {})
    t = ' '.join([r.get('title', '') or '', r.get('og_site_name', '') or '', r.get('description', '') or r.get('og_description', '') or '',
                  (r.get('keywords', '') or '')[:200], c.get('cc_title', '') or '', c.get('cc_description', '') or '', c.get('cc_site_name', '') or ''])
    if len(t.strip()) < 20:
        t += ' ' + (r.get('snippet', '') or '')[:300]
    return html.unescape(t)

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.svm import LinearSVC
allo = list(sites.origin)
hosts = [o.split('://')[1] for o in allo]
Hv = TfidfVectorizer(analyzer='char_wb', ngram_range=(3, 5), min_df=2, sublinear_tf=True).fit(hosts)
Tv = TfidfVectorizer(analyzer='word', ngram_range=(1, 2), min_df=2, max_features=150000, sublinear_tf=True).fit([text_of(o) for o in allo])
def feats(os_):
    em = np.stack([E[eidx[o]] if o in eidx else np.zeros(E.shape[1], dtype=np.float32) for o in os_])
    return sp.hstack([sp.csr_matrix(em * 2), Hv.transform([o.split('://')[1] for o in os_]), Tv.transform([text_of(o) for o in os_])]).tocsr()
train = [o for o in allo if o in lab]
clf = LinearSVC(C=0.5).fit(feats(train), [lab[o] for o in train])
rest = [o for o in allo if o not in lab]
Xr = feats(rest)
dec = clf.decision_function(Xr)
pred = clf.classes_[dec.argmax(1)]
srt = np.sort(dec, 1); margin = srt[:, -1] - srt[:, -2]

# UT1 + TLD overrides for model-predicted rows
ut1 = json.load(open(f'{SP}/ut1_labels.json'))
NAME2CODE = {v: k for k, v in CODES.items()}
NAME2CODE.update({'Gambling': 'GB', 'Anime, Manga & Comics': 'AM'})
GOV = re.compile(r'(^|\.)(gov|gob|gouv|go|govt|gc|mil|gv|admin|nic)\.[a-z.]+$|\.gov$|\.mil$|\.gob\.|\.gov\.|\.gouv\.')
EDU = re.compile(r'\.edu$|\.edu\.[a-z]{2}$|\.ac\.[a-z]{2}$|\.k12\.|instructure\.com$|schoology\.com$')
cat, csrc = {}, {}
for o in allo:
    if o in lab:
        cat[o] = lab[o]; csrc[o] = 'Manual review'
for o, p_, m in zip(rest, pred, margin):
    h = o.split('://')[1]
    u = ut1.get(o, [])
    if 'Adult' in u:
        cat[o], csrc[o] = 'AD', 'Blocklist (UT1)'
    elif GOV.search(h) and p_ not in ('ED',):
        cat[o], csrc[o] = 'GV', 'Domain rule (.gov/.gob/.gouv)'
    elif EDU.search(h):
        cat[o], csrc[o] = 'ED', 'Domain rule (.edu/.ac)'
    elif len(u) == 1 and u[0] in NAME2CODE and m < 0.5:
        cat[o], csrc[o] = NAME2CODE[u[0]], 'Blocklist (UT1)'
    else:
        cat[o] = p_
        csrc[o] = 'Model (high confidence)' if m >= 0.5 else ('Model (medium confidence)' if m >= 0.2 else 'Model (low confidence)')
sites['category'] = [CODES[cat[o]] for o in allo]
sites['category_source'] = [csrc[o] for o in allo]
sites['page_title'] = [html.unescape((live.get(o, {}).get('title') or cc.get(o, {}).get('cc_title') or ''))[:120] for o in allo]

df = sites.merge(rob, on='origin')
# overall popularity rank: CrUX bucket, then Tranco rank (unknown last)
df['_t'] = df.tranco_rank.fillna(10**7)
df = df.sort_values(['crux_bucket', '_t', 'origin']).reset_index(drop=True)
df['popularity_rank'] = np.arange(1, len(df) + 1)
df.drop(columns=['_t']).to_pickle(f'{SP}/final.pkl')
print(df.category.value_counts().to_string())
print(df.category_source.value_counts().to_string())
print(df.country.value_counts().head(15).to_string())
print('robots data coverage', df['Googlebot'].notna().mean())
for c in cols + ['All bots (*)']:
    print(f'{c:28s} blocked {1 - df[c].mean():.3f}')
