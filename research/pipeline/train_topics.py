"""E13：48 类主题分类器。维度扫描（轻量轨体积敏感），分组切分，导出两种规格。"""
import json
import numpy as np
from sklearn.feature_extraction.text import HashingVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import GroupShuffleSplit
from sklearn.metrics import accuracy_score

SCRATCH = "/tmp/claude-1000/-home-leo----bilibili/7ae81ed2-efb1-446d-95dc-6901201fe793/scratchpad"
TAX = json.load(open("/home/leo/桌面/bilibili/interest-model/taxonomy.json"))
LEAVES = [l for g in TAX["groups"].values() for l in g]
GROUP_OF = {}
gi = 0
for gname, ls in TAX["groups"].items():
    for l in ls:
        GROUP_OF[LEAVES.index(l) + 1] = gi
    gi += 1

corpus = {r["b"]: r for l in open(SCRATCH + "/corpus.jsonl") for r in [json.loads(l)]}
topics = {}
for l in open(SCRATCH + "/topics.jsonl"):
    r = json.loads(l)
    topics[r["b"]] = r["tid"]
rows = [{**corpus[b], "tid": t} for b, t in topics.items() if b in corpus]
print(f"topic-labeled samples: {len(rows)}")
from collections import Counter
cnt = Counter(r["tid"] for r in rows)
print("最多的5类:", [(LEAVES[t-1], n) for t, n in cnt.most_common(5)])
print("最少的5类:", [(LEAVES[t-1], n) for t, n in cnt.most_common()[-5:]])

texts = [r["t"] + " \x01 " + r["u"] for r in rows]
y = np.array([r["tid"] - 1 for r in rows])
groups = np.array([r["u"] if r["u"] else r["b"] for r in rows])
tr, te = next(GroupShuffleSplit(1, test_size=0.15, random_state=42).split(texts, y, groups))
print(f"train={len(tr)} test={len(te)}")

results = {}
for dims in [2**12, 2**13, 2**15]:
    vec = HashingVectorizer(analyzer="char", ngram_range=(1, 3), n_features=dims, alternate_sign=False, norm="l2")
    Xtr, Xte = vec.transform([texts[i] for i in tr]), vec.transform([texts[i] for i in te])
    m = LogisticRegression(C=2.0, max_iter=2000).fit(Xtr, y[tr])
    proba = m.predict_proba(Xte)
    top1 = accuracy_score(y[te], proba.argmax(1))
    top3 = np.mean([y[te][i] in np.argsort(proba[i])[-3:] for i in range(len(te))])
    gacc = np.mean([GROUP_OF[y[te][i] + 1] == GROUP_OF[proba[i].argmax() + 1] for i in range(len(te))])
    size_kb = 48 * dims / 1024
    print(f"dims=2^{dims.bit_length()-1}: top1={top1:.3f} top3={top3:.3f} 大类acc={gacc:.3f} int8体积={size_kb:.0f}KB")
    results[dims] = dict(top1=top1, top3=top3, gacc=gacc, size_kb=size_kb)
    # 导出
    tag = "lite" if dims == 2**13 else ("daemon" if dims == 2**15 else None)
    if tag:
        mf = LogisticRegression(C=2.0, max_iter=2000).fit(vec.transform(texts), y)
        np.savez(SCRATCH + f"/topic_model_{tag}.npz", w=mf.coef_.astype(np.float32), b=mf.intercept_.astype(np.float32), dims=dims)
json.dump({str(k): v for k, v in results.items()}, open(SCRATCH + "/topic_eval.json", "w"), indent=1)
print("saved topic_model_lite.npz topic_model_daemon.npz")
