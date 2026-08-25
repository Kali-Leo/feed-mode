"""线性主模型训练+验证。用法: train_full.py [--silver]  (--silver 时加入 BERT 银标数据)"""
import json, sys
import numpy as np
from sklearn.feature_extraction.text import HashingVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import GroupShuffleSplit
from sklearn.metrics import f1_score, precision_score, recall_score, accuracy_score

SCRATCH = "/tmp/claude-1000/-home-leo----bilibili/7ae81ed2-efb1-446d-95dc-6901201fe793/scratchpad"
USE_SILVER = "--silver" in sys.argv

corpus = {r["b"]: r for l in open(SCRATCH + "/corpus.jsonl") for r in [json.loads(l)]}
labels = {}
for l in open(SCRATCH + "/labels.jsonl"):
    r = json.loads(l)
    labels[r["b"]] = r  # 重复以最后一次为准

rows = []
seen_titles = set()
for b, lab in labels.items():
    c = corpus.get(b)
    if not c or c["t"] in seen_titles:
        continue
    seen_titles.add(c["t"])
    rows.append({**c, "pro": lab["pro"], "neg": lab["neg"]})
print(f"gold samples (title-dedup): {len(rows)}")

groups = np.array([r["u"] if r["u"] else r["b"] for r in rows])
texts = [(r["t"] + " \x01 " + r["u"]) for r in rows]
Ypro = np.array([r["pro"] for r in rows])
Yneg = np.array([r["neg"] for r in rows])
srcs = np.array([r["s"] for r in rows])

# 按 UP 分组切分 80/10/10，防同 UP 泄漏
gss = GroupShuffleSplit(1, test_size=0.2, random_state=42)
tr, rest = next(gss.split(texts, Ypro, groups))
gss2 = GroupShuffleSplit(1, test_size=0.5, random_state=43)
va_i, te_i = next(gss2.split([texts[i] for i in rest], Ypro[rest], groups[rest]))
va, te = rest[va_i], rest[te_i]
json.dump({"train": [rows[i]["b"] for i in tr], "val": [rows[i]["b"] for i in va],
           "test": [rows[i]["b"] for i in te]}, open(SCRATCH + "/splits.json", "w"))
print(f"split: train={len(tr)} val={len(va)} test={len(te)}")

silver_texts, silver_pro, silver_neg = [], [], []
if USE_SILVER:
    gold_b = set(labels)
    for l in open(SCRATCH + "/silver.jsonl"):
        r = json.loads(l)
        if r["b"] in gold_b:
            continue
        c = corpus.get(r["b"])
        if not c or c["t"] in seen_titles:
            continue
        seen_titles.add(c["t"])
        silver_texts.append(c["t"] + " \x01 " + c["u"])
        silver_pro.append(r["pro"]); silver_neg.append(r["neg"])
    print(f"silver added: {len(silver_texts)}")

def vec_of(dims, ng):
    return HashingVectorizer(analyzer="char", ngram_range=ng, n_features=dims,
                             alternate_sign=False, norm="l2")

report = {}
for task, Y in [("pro", Ypro), ("neg", Yneg)]:
    print(f"\n======= 任务 {task} (正例率 {Y.mean():.1%}) =======")
    best = None
    for dims in [2**14, 2**15, 2**16]:
        for ng in [(1, 3), (1, 4), (2, 4)]:
            v = vec_of(dims, ng)
            Xtr = v.transform([texts[i] for i in tr] + silver_texts)
            ytr = np.concatenate([Y[tr], np.array(silver_pro if task == "pro" else silver_neg, dtype=int)]) if silver_texts else Y[tr]
            Xva = v.transform([texts[i] for i in va])
            for C in [0.5, 1.0, 2.0]:
                m = LogisticRegression(C=C, max_iter=3000, class_weight="balanced").fit(Xtr, ytr)
                f1 = f1_score(Y[va], m.predict(Xva))
                if best is None or f1 > best[0]:
                    best = (f1, dims, ng, C)
    f1v, dims, ng, C = best
    print(f"best cfg: dims=2^{dims.bit_length()-1} ngram={ng} C={C}  val F1={f1v:.3f}")
    v = vec_of(dims, ng)
    Xtr = v.transform([texts[i] for i in tr] + silver_texts)
    ytr = np.concatenate([Y[tr], np.array(silver_pro if task == "pro" else silver_neg, dtype=int)]) if silver_texts else Y[tr]
    m = LogisticRegression(C=C, max_iter=3000, class_weight="balanced").fit(Xtr, ytr)
    Xte = v.transform([texts[i] for i in te])
    proba = m.predict_proba(Xte)[:, 1]
    pred = (proba > 0.5).astype(int)
    res = {"acc": accuracy_score(Y[te], pred), "P": precision_score(Y[te], pred, zero_division=0),
           "R": recall_score(Y[te], pred, zero_division=0), "F1": f1_score(Y[te], pred, zero_division=0)}
    print("TEST:", {k: round(x, 3) for k, x in res.items()})
    # 按来源细分（外推能力：rcmd 是部署分布）
    for s in sorted(set(srcs[te])):
        mask = srcs[te] == s
        if mask.sum() < 20:
            continue
        print(f"  test[{s}] n={mask.sum()} F1={f1_score(Y[te][mask], pred[mask], zero_division=0):.3f} acc={accuracy_score(Y[te][mask], pred[mask]):.3f}")
    # 分流曲线
    conf = np.abs(proba - 0.5) * 2
    order = np.argsort(conf)
    print("  送LLM比例 -> 本地保留 acc / F1:")
    esc_tab = []
    for esc in [0.05, 0.10, 0.15, 0.20, 0.30]:
        k = int(len(te) * esc)
        keep = order[k:]
        a = accuracy_score(Y[te][keep], pred[keep])
        f = f1_score(Y[te][keep], pred[keep], zero_division=0)
        thr = conf[order[k]] if k < len(order) else 1.0
        esc_tab.append({"esc": esc, "acc": a, "F1": f, "conf_thr": float(thr)})
        print(f"    {esc:.0%} -> acc={a:.3f} F1={f:.3f} (置信阈值 {thr:.3f})")
    # 学习曲线
    rng = np.random.RandomState(0)
    perm = rng.permutation(len(tr))
    print("  学习曲线 (train n -> test F1):")
    for n in [2000, 5000, 10000, len(tr)]:
        if n > len(tr):
            break
        sub = tr[perm[:n]]
        Xs = v.transform([texts[i] for i in sub])
        ms = LogisticRegression(C=C, max_iter=3000, class_weight="balanced").fit(Xs, Y[sub])
        print(f"    n={n}: F1={f1_score(Y[te], ms.predict(Xte), zero_division=0):.3f}")
    # 保存全量重训模型（train+val+test 全部数据，供导出；指标以上面的 held-out 为准）
    Xall = v.transform(texts + silver_texts)
    yall = np.concatenate([Y, np.array(silver_pro if task == "pro" else silver_neg, dtype=int)]) if silver_texts else Y
    mf = LogisticRegression(C=C, max_iter=3000, class_weight="balanced").fit(Xall, yall)
    np.savez(SCRATCH + f"/model_{task}.npz", w=mf.coef_.ravel().astype(np.float32),
             b=np.float32(mf.intercept_[0]), dims=dims, ng_lo=ng[0], ng_hi=ng[1])
    report[task] = {"cfg": {"dims": dims, "ngram": ng, "C": C}, "val_F1": f1v, "test": res, "escalation": esc_tab}

json.dump(report, open(SCRATCH + "/report_linear.json", "w"), indent=1)
print("\nsaved: model_pro.npz model_neg.npz splits.json report_linear.json")
