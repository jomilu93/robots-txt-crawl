"""Embed homepage title/description text for categorization (multilingual-e5-small)."""
import glob, gzip, json
import numpy as np
from sentence_transformers import SentenceTransformer

recs = []
for p in sorted(glob.glob("results/robots_*.jsonl.gz")):
    with gzip.open(p, "rt") as f:
        for line in f:
            r = json.loads(line)
            host = r["origin"].split("://", 1)[1]
            parts = [host, r.get("og_site_name", ""), r.get("title", ""), r.get("description", "") or r.get("og_description", ""),
                     r.get("keywords", "")[:200]]
            txt = " | ".join(p for p in parts if p)
            if len(txt) < len(host) + 40:
                txt += " | " + r.get("snippet", "")[:300]
            recs.append((r["origin"], txt[:700]))
model = SentenceTransformer("intfloat/multilingual-e5-small", device="cpu")
emb = model.encode(["query: " + t for _, t in recs], batch_size=128, show_progress_bar=True, normalize_embeddings=True)
np.save("results/embeddings.npy", emb.astype(np.float16))
with open("results/embedding_origins.txt", "w") as f:
    f.write("\n".join(o for o, _ in recs))
print(emb.shape)
