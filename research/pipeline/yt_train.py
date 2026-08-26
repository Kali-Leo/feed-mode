"""E20 训练：YouTube 三套模型。
1) 专业二元 字符n-gram int8 -> 插件嵌入（配置扫描选最优）
2) 主题48类 / 情绪9类 多语言嵌入 -> daemon（按站点路由）"""
import json, base64, os
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
for k in ["http_proxy", "https_proxy", "all_proxy", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"]:
    os.environ.pop(k, None)
import numpy as np
from sklearn.feature_extraction.text import HashingVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import GroupShuffleSplit
from sklearn.metrics import f1_score, precision_score, recall_score, accuracy_score
import joblib

S = "/tmp/claude-1000/-home-leo----bilibili/7ae81ed2-efb1-446d-95dc-6901201fe793/scratchpad"
EMO = json.load(open("/home/leo/桌面/bilibili/interest-model/emotions.json"))
E_VAL = np.array([e["valence"] for e in EMO["emotions"]])

corpus = {r["b"]: r for l in open(S + "/yt_corpus.jsonl") for r in [json.loads(l)]}
rows = []
seen = set()
for l in open(S + "/yt_labels.jsonl"):
    r = json.loads(l)
    if r["b"] in seen or r["b"] not in corpus:
        continue
    seen.add(r["b"])
    rows.append({**corpus[r["b"]], **r})
print(f"YT labeled: {len(rows)}  pro率: {np.mean([r['pro'] for r in rows]):.1%}")

# 跨语言联合训练：并入 B站语料（pro 轴 + 主题 + 情绪），多语言嵌入共享语义空间
zh_corpus = {r["b"]: r for l in open(S + "/corpus.jsonl") for r in [json.loads(l)]}
zh_pro = {r["b"]: r["pro"] for l in open(S + "/labels.jsonl") for r in [json.loads(l)]}
zh_top = {}
for l in open(S + "/topics.jsonl"):
    r = json.loads(l)
    zh_top.setdefault(r["b"], r["tid"])
zh_emo = {}
for l in open(S + "/emotions.jsonl"):
    r = json.loads(l)
    zh_emo.setdefault(r["b"], r["tid"])
zh_rows = [{**zh_corpus[b], "pro": zh_pro[b], "tid": zh_top.get(b), "eid": zh_emo.get(b)}
           for b in zh_pro if b in zh_corpus and b in zh_top and b in zh_emo]
print(f"B站并入: {len(zh_rows)}")

texts = [r["t"] + " \x01 " + r["u"] for r in rows]
groups = np.array([r["u"] if r["u"] else r["b"] for r in rows])
ypro = np.array([r["pro"] for r in rows])
tr, te = next(GroupShuffleSplit(1, test_size=0.25, random_state=42).split(texts, ypro, groups))
zh_texts = [r["t"] + " \x01 " + r["u"] for r in zh_rows]
zh_ypro = np.array([r["pro"] for r in zh_rows])

# ---- 1) 专业二元（插件用） ----
best = None
for ng in [(1, 3), (2, 4), (1, 4)]:
    for dims in [2**13, 2**14]:
        vec = HashingVectorizer(analyzer="char", ngram_range=ng, n_features=dims, alternate_sign=False, norm="l2")
        m = LogisticRegression(C=1.0, max_iter=3000, class_weight="balanced").fit(
            vec.transform([texts[i] for i in tr] + zh_texts), np.concatenate([ypro[tr], zh_ypro]))
        pred = m.predict(vec.transform([texts[i] for i in te]))
        f1 = f1_score(ypro[te], pred)
        print(f"pro ngram={ng} dims=2^{dims.bit_length()-1}: F1={f1:.3f} P={precision_score(ypro[te],pred):.3f} R={recall_score(ypro[te],pred):.3f}")
        if best is None or f1 > best[0]:
            best = (f1, ng, dims)
f1b, ng, dims = best
print(f"best: ngram={ng} dims=2^{dims.bit_length()-1} F1={f1b:.3f}")
vec = HashingVectorizer(analyzer="char", ngram_range=ng, n_features=dims, alternate_sign=False, norm="l2")
mf = LogisticRegression(C=1.0, max_iter=3000, class_weight="balanced").fit(
    vec.transform(texts + zh_texts), np.concatenate([ypro, zh_ypro]))
w = mf.coef_.ravel().astype(np.float32)
scale = float(np.abs(w).max() / 127.0)
q = np.clip(np.round(w / scale), -127, 127).astype(np.int8)
json.dump({"dims": dims, "ngLo": ng[0], "ngHi": ng[1], "scale": scale,
           "bias": float(mf.intercept_[0]), "b64": base64.b64encode(q.tobytes()).decode(),
           "test_f1": f1b},
          open(S + "/yt_pro_embed.json", "w"))
np.savez(S + "/yt_pro_model.npz", w=w, b=np.float32(mf.intercept_[0]), dims=dims, ng_lo=ng[0], ng_hi=ng[1])
print(f"插件模型: {q.nbytes//1024}KB int8")

# ---- 2) 主题 + 情绪（daemon 用，多语言嵌入） ----
from sentence_transformers import SentenceTransformer
enc = SentenceTransformer("sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2", device="cuda")
X = enc.encode([r["t"] + " " + r["u"] for r in rows], batch_size=256, normalize_embeddings=True, show_progress_bar=False)
Xzh = enc.encode([r["t"] + " " + r["u"] for r in zh_rows], batch_size=256, normalize_embeddings=True, show_progress_bar=False)
ytop = np.array([r["tid"] - 1 for r in rows])
yemo = np.array([r["eid"] - 1 for r in rows])
zh_ytop = np.array([r["tid"] - 1 for r in zh_rows])
zh_yemo = np.array([r["eid"] - 1 for r in zh_rows])
Xj_tr = np.vstack([X[tr], Xzh])
top_clf = LogisticRegression(C=4.0, max_iter=3000).fit(Xj_tr, np.concatenate([ytop[tr], zh_ytop]))
p = top_clf.predict_proba(X[te])
top1 = accuracy_score(ytop[te], p.argmax(1))
top3 = np.mean([ytop[te][i] in np.argsort(p[i])[-3:] for i in range(len(te))])
print(f"[YT主题] top1={top1:.3f} top3={top3:.3f}")
emo_clf = LogisticRegression(C=4.0, max_iter=3000).fit(Xj_tr, np.concatenate([yemo[tr], zh_yemo]))
pe = emo_clf.predict_proba(X[te])
e_top1 = accuracy_score(yemo[te], pe.argmax(1))
val_corr = float(np.corrcoef(pe @ E_VAL, E_VAL[yemo[te]])[0, 1])
print(f"[YT情绪] top1={e_top1:.3f} 效价corr={val_corr:.3f}")
D = "/home/leo/桌面/bilibili/interest-model/daemon/models"
Xall = np.vstack([X, Xzh])
joblib.dump(LogisticRegression(C=4.0, max_iter=3000).fit(Xall, np.concatenate([ytop, zh_ytop])), D + "/yt_topic_clf.joblib")
joblib.dump(LogisticRegression(C=4.0, max_iter=3000).fit(Xall, np.concatenate([yemo, zh_yemo])), D + "/yt_emotion_clf.joblib")
json.dump({"pro_f1": f1b, "topic_top1": top1, "topic_top3": top3,
           "emo_top1": e_top1, "emo_val_corr": val_corr, "n": len(rows)},
          open(S + "/yt_eval.json", "w"))
print("YT-TRAIN-DONE")
