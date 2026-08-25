"""E5 缩放实验：n x 3种子，固定配置（全量数据在 val 上选出），冻结 test。
输出 results/scaling.jsonl + 汇总表。需先跑 train_full.py 生成 splits.json 与 report_linear.json。"""
import json
import numpy as np
from sklearn.feature_extraction.text import HashingVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import f1_score, accuracy_score

SCRATCH = "/tmp/claude-1000/-home-leo----bilibili/7ae81ed2-efb1-446d-95dc-6901201fe793/scratchpad"
RESULTS = "/home/leo/桌面/bilibili/research/results"
import os
os.makedirs(RESULTS, exist_ok=True)

corpus = {r["b"]: r for l in open(SCRATCH + "/corpus.jsonl") for r in [json.loads(l)]}
labels = {r["b"]: r for l in open(SCRATCH + "/labels.jsonl") for r in [json.loads(l)]}
splits = json.load(open(SCRATCH + "/splits.json"))
best = json.load(open(SCRATCH + "/report_linear.json"))

def mk(bs, task):
    X, y = [], []
    for b in bs:
        c, lab = corpus.get(b), labels.get(b)
        if c and lab:
            X.append(c["t"] + " \x01 " + c["u"])
            y.append(lab[task])
    return X, np.array(y)

out = open(RESULTS + "/scaling.jsonl", "w")
summary = {}
for task in ["pro", "neg"]:
    cfg = best[task]["cfg"]
    vec = HashingVectorizer(analyzer="char", ngram_range=tuple(cfg["ngram"]),
                            n_features=cfg["dims"], alternate_sign=False, norm="l2")
    Xtr_t, ytr = mk(splits["train"], task)
    Xte_t, yte = mk(splits["test"], task)
    Xte = vec.transform(Xte_t)
    grid = [n for n in [500, 1000, 2000, 5000, 10000] if n < len(ytr)] + [len(ytr)]
    summary[task] = []
    for n in grid:
        f1s, accs = [], []
        for seed in [0, 1, 2]:
            idx = np.random.RandomState(seed).permutation(len(ytr))[:n]
            # 抽样后若单类缺失则跳过该种子
            if len(set(ytr[idx])) < 2:
                continue
            m = LogisticRegression(C=cfg["C"], max_iter=3000, class_weight="balanced")
            m.fit(vec.transform([Xtr_t[i] for i in idx]), ytr[idx])
            pred = m.predict(Xte)
            f1s.append(f1_score(yte, pred, zero_division=0))
            accs.append(accuracy_score(yte, pred))
            out.write(json.dumps({"task": task, "n": int(n), "seed": seed,
                                  "F1": f1s[-1], "acc": accs[-1], "cfg": cfg}) + "\n")
        row = {"n": int(n), "F1_mean": float(np.mean(f1s)), "F1_std": float(np.std(f1s)),
               "acc_mean": float(np.mean(accs))}
        summary[task].append(row)
        print(f"{task} n={n}: F1={row['F1_mean']:.3f}±{row['F1_std']:.3f} acc={row['acc_mean']:.3f}", flush=True)
out.close()
json.dump(summary, open(RESULTS + "/scaling_summary.json", "w"), indent=1)

# 生成 LOG.md 回填用的 markdown 表
lines = []
for task in ["pro", "neg"]:
    lines.append(f"\n**{task}**（test n={len(mk(splits['test'], task)[1])}，3 种子均值±std）：\n")
    lines.append("| 训练样本数 | F1 | acc |")
    lines.append("|---|---|---|")
    for row in summary[task]:
        lines.append(f"| {row['n']} | {row['F1_mean']:.3f}±{row['F1_std']:.3f} | {row['acc_mean']:.3f} |")
open(RESULTS + "/scaling_table.md", "w").write("\n".join(lines))
print("saved results/scaling.jsonl scaling_summary.json scaling_table.md")
