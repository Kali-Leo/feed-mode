"""E15：嵌入特征主题分类（完整轨）。bge-small-zh 编码 -> 逻辑回归。
产物：topic_eval 对比、topic_probas_emb.npz（全量样本预计算概率，供回放评估）、daemon 用模型。"""
import json, os
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
for k in ["http_proxy", "https_proxy", "all_proxy", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"]:
    os.environ.pop(k, None)
import numpy as np
from sentence_transformers import SentenceTransformer
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import GroupShuffleSplit
from sklearn.metrics import accuracy_score
import joblib

SCRATCH = "/tmp/claude-1000/-home-leo----bilibili/7ae81ed2-efb1-446d-95dc-6901201fe793/scratchpad"
TAX = json.load(open("/home/leo/桌面/bilibili/interest-model/taxonomy.json"))
LEAVES = [l for g in TAX["groups"].values() for l in g]
GROUP_OF = {}
gi = 0
for gname, ls in TAX["groups"].items():
    for l in ls:
        GROUP_OF[LEAVES.index(l)] = gi
    gi += 1

corpus = {r["b"]: r for l in open(SCRATCH + "/corpus.jsonl") for r in [json.loads(l)]}
seen = set()
rows = []
for l in open(SCRATCH + "/topics.jsonl"):
    r = json.loads(l)
    if r["b"] in seen or r["b"] not in corpus:
        continue
    seen.add(r["b"])
    rows.append({**corpus[r["b"]], "tid": r["tid"] - 1})
print(f"samples: {len(rows)}", flush=True)

texts = [r["t"] + " " + r["u"] for r in rows]
y = np.array([r["tid"] for r in rows])
groups = np.array([r["u"] if r["u"] else r["b"] for r in rows])

model = SentenceTransformer("BAAI/bge-small-zh-v1.5", device="cuda")
X = model.encode(texts, batch_size=256, show_progress_bar=False, normalize_embeddings=True)
print("embeddings:", X.shape, flush=True)

tr, te = next(GroupShuffleSplit(1, test_size=0.15, random_state=42).split(texts, y, groups))
clf = LogisticRegression(C=4.0, max_iter=3000).fit(X[tr], y[tr])
proba_te = clf.predict_proba(X[te])
top1 = accuracy_score(y[te], proba_te.argmax(1))
top3 = np.mean([y[te][i] in np.argsort(proba_te[i])[-3:] for i in range(len(te))])
gacc = np.mean([GROUP_OF[y[te][i]] == GROUP_OF[proba_te[i].argmax()] for i in range(len(te))])
print(f"[嵌入] top1={top1:.3f} top3={top3:.3f} 大类acc={gacc:.3f}", flush=True)

# 全量重训 + 全语料预计算概率（供回放评估：模拟 daemon 的分类行为）
clf_full = LogisticRegression(C=4.0, max_iter=3000).fit(X, y)
# 注意：评估集条目也在训练里会乐观——回放评估里改用 5 折外折概率
from sklearn.model_selection import cross_val_predict, GroupKFold
proba_oof = cross_val_predict(LogisticRegression(C=4.0, max_iter=3000), X, y,
                              cv=GroupKFold(5), groups=groups, method="predict_proba")
np.savez(SCRATCH + "/topic_probas_emb.npz", bs=np.array([r["b"] for r in rows]), proba=proba_oof.astype(np.float32))
joblib.dump(clf_full, SCRATCH + "/topic_clf_emb.joblib")
json.dump({"top1": top1, "top3": top3, "gacc": gacc}, open(SCRATCH + "/topic_eval_emb.json", "w"))
print("saved topic_probas_emb.npz topic_clf_emb.joblib", flush=True)
