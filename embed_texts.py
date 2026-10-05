"""Embed category prototype texts with the same model used for sites."""
import json
import numpy as np
from sentence_transformers import SentenceTransformer
cats = json.load(open("categories.json"))
labels, texts = [], []
for c, ts in cats.items():
    for t in ts:
        labels.append(c); texts.append("query: " + t)
m = SentenceTransformer("intfloat/multilingual-e5-small", device="cpu")
e = m.encode(texts, normalize_embeddings=True)
np.save("results/category_proto.npy", e.astype(np.float32))
json.dump(labels, open("results/category_proto_labels.json", "w"))
