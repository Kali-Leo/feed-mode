"""E18：情绪分类器（嵌入特征）+ 词效价表（词云着色用）。"""
import json, os
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
for k in ["http_proxy", "https_proxy", "all_proxy", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"]:
    os.environ.pop(k, None)
import numpy as np
from sentence_transformers import SentenceTransformer
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import GroupShuffleSplit
from sklearn.metrics import accuracy_score, f1_score
import joblib

SCRATCH = "/tmp/claude-1000/-home-leo----bilibili/7ae81ed2-efb1-446d-95dc-6901201fe793/scratchpad"
EMO = json.load(open("/home/leo/桌面/bilibili/interest-model/emotions.json"))
NAMES = [e["name"] for e in EMO["emotions"]]
VAL = np.array([e["valence"] for e in EMO["emotions"]])

corpus = {r["b"]: r for l in open(SCRATCH + "/corpus.jsonl") for r in [json.loads(l)]}
seen, rows = set(), []
for l in open(SCRATCH + "/emotions.jsonl"):
    r = json.loads(l)
    if r["b"] in seen or r["b"] not in corpus:
        continue
    seen.add(r["b"])
    rows.append({**corpus[r["b"]], "eid": r["tid"] - 1})
print(f"emotion-labeled: {len(rows)}")
from collections import Counter
for eid, n in Counter(r["eid"] for r in rows).most_common():
    print(f"  {NAMES[eid]}: {n} ({n/len(rows):.0%})")

texts = [r["t"] + " " + r["u"] for r in rows]
y = np.array([r["eid"] for r in rows])
groups = np.array([r["u"] if r["u"] else r["b"] for r in rows])
enc = SentenceTransformer("BAAI/bge-small-zh-v1.5", device="cuda")
X = enc.encode(texts, batch_size=256, normalize_embeddings=True, show_progress_bar=False)
tr, te = next(GroupShuffleSplit(1, test_size=0.15, random_state=42).split(texts, y, groups))
clf = LogisticRegression(C=4.0, max_iter=3000).fit(X[tr], y[tr])
proba = clf.predict_proba(X[te])
top1 = accuracy_score(y[te], proba.argmax(1))
mf1 = f1_score(y[te], proba.argmax(1), average="macro")
# 效价保真：预测效价（proba 加权）与标注效价的相关/误差——曲线用的是效价聚合，这才是关键指标
val_pred = proba @ VAL
val_true = VAL[y[te]]
corr = float(np.corrcoef(val_pred, val_true)[0, 1])
mae = float(np.abs(val_pred - val_true).mean())
print(f"[情绪] top1={top1:.3f} macroF1={mf1:.3f}  效价: corr={corr:.3f} MAE={mae:.2f} (效价范围4.0)")
clf_full = LogisticRegression(C=4.0, max_iter=3000).fit(X, y)
joblib.dump(clf_full, SCRATCH + "/emotion_clf_emb.joblib")
json.dump({"top1": top1, "macroF1": mf1, "val_corr": corr, "val_mae": mae},
          open(SCRATCH + "/emotion_eval.json", "w"))

# 词效价表：词 -> 含该词标题的平均标注效价（jieba 分词，用于词云着色）
import jieba, re
word_vals, word_cnt = {}, {}
for r in rows:
    v = VAL[r["eid"]]
    for w in set(jieba.lcut(r["t"])):
        if len(w) < 2 or re.match(r"^[\d\W_]+$", w):
            continue
        word_vals[w] = word_vals.get(w, 0.0) + v
        word_cnt[w] = word_cnt.get(w, 0) + 1
wv = {w: round(word_vals[w] / word_cnt[w], 3) for w in word_vals if word_cnt[w] >= 5}
json.dump(wv, open("/home/leo/桌面/bilibili/interest-model/daemon/models/word_valence.json", "w"), ensure_ascii=False)
print(f"词效价表: {len(wv)} 词 (出现≥5次)")
print("最负10词:", sorted(wv, key=wv.get)[:10])
print("最正10词:", sorted(wv, key=wv.get, reverse=True)[:10])
