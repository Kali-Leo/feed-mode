"""E14/E15：合成用户回放评估。

用法: personas.py <topic_model.npz> <结果标签>
从已标注语料构造已知兴趣配比的虚拟用户，生成带互动偏好的事件流，
回放给画像引擎，度量画像恢复精度 / 收敛速度 / 漂移响应。
分类误差被真实包含在回放中（画像用分类器预测，真值用 LLM 标签）。
"""
import json, sys
import numpy as np
from sklearn.feature_extraction.text import HashingVectorizer
from profile_engine import N_TOPICS
import profile_engine

class Profile(profile_engine.Profile):
    def __init__(self):
        super().__init__()
        import os as _os
        if _os.environ.get("IM_GROUPS") == "1":
            self.short = np.zeros(13); self.long = np.zeros(13); self.expose = np.zeros(13)

SCRATCH = "/tmp/claude-1000/-home-leo----bilibili/7ae81ed2-efb1-446d-95dc-6901201fe793/scratchpad"
TAX = json.load(open(__file__.rsplit("/", 2)[0] + "/taxonomy.json"))
LEAVES = [l for g in TAX["groups"].values() for l in g]

MODEL_PATH = sys.argv[1] if len(sys.argv) > 1 else SCRATCH + "/topic_model_lite.npz"
TAG = sys.argv[2] if len(sys.argv) > 2 else "lite"

d = np.load(MODEL_PATH, allow_pickle=True)
if "proba" in d:  # 预计算概率表（嵌入模型等重特征走离线预计算）
    LOOKUP = {b: p for b, p in zip(d["bs"], d["proba"])}
    W = B = vec = None
else:
    LOOKUP = None
    W, B, DIMS = d["w"], d["b"], int(d["dims"])
    vec = HashingVectorizer(analyzer="char", ngram_range=(1, 3), n_features=DIMS, alternate_sign=False, norm="l2")

corpus = {r["b"]: r for l in open(SCRATCH + "/corpus.jsonl") for r in [json.loads(l)]}
items_by_topic = {t: [] for t in range(N_TOPICS)}
all_items = []
for l in open(SCRATCH + "/topics.jsonl"):
    r = json.loads(l)
    c = corpus.get(r["b"])
    if c:
        it = {"b": r["b"], "t": c["t"], "u": c["u"], "tid": r["tid"] - 1}
        items_by_topic[r["tid"] - 1].append(it)
        all_items.append(it)

import os
GROUP_LEVEL = os.environ.get("IM_GROUPS") == "1"
if GROUP_LEVEL:
    GMAP = np.zeros((48, 13))
    gi = 0
    for gname, ls in TAX["groups"].items():
        for l in ls:
            GMAP[LEAVES.index(l), gi] = 1
        gi += 1

def fold(v):
    return v @ GMAP if GROUP_LEVEL else v

def predict_proba(title, up, b=None):
    if LOOKUP is not None:
        return fold(LOOKUP[b])
    x = vec.transform([title + " \x01 " + up])
    z = (x @ W.T).toarray().ravel() if hasattr(x @ W.T, "toarray") else np.asarray(x @ W.T).ravel()
    z = z + B
    e = np.exp(z - z.max())
    return fold(e / e.sum())

# 8 个虚拟用户：不同集中度的兴趣配比（选样本充足的主题）
PERSONAS = [
    {"编程与软件开发": 0.5, "历史人文": 0.3, "萌宠动物": 0.2},
    {"宏观经济与投资": 0.6, "科学科普": 0.4},
    {"单机与主机游戏": 0.4, "网游与电竞": 0.3, "搞笑段子": 0.3},
    {"美食制作": 0.35, "旅行户外": 0.35, "生活Vlog": 0.3},
    {"番剧与动漫": 0.5, "演奏与翻唱": 0.3, "舞蹈": 0.2},
    {"人工智能": 0.4, "硬件与数码评测": 0.3, "科技产业资讯": 0.3},
    {"健身与运动教学": 0.5, "体育赛事": 0.5},
    {"纪录片": 0.4, "社会观察": 0.3, "时事资讯": 0.3},
]

def true_mix(persona):
    v = np.zeros(N_TOPICS)
    for name, w in persona.items():
        v[LEAVES.index(name)] = w
    return fold(v / v.sum())

def gen_events(persona, n, rng):
    """信息流仿真：60% 按兴趣采样、40% 随机（模拟推荐流的探索混合）；
    兴趣主题的内容 55% 概率观看（时长30-600s）、15% 点击；非兴趣 4% 误点。"""
    names, ws = zip(*persona.items())
    tids = [LEAVES.index(nm) for nm in names]
    ws = np.array(ws) / sum(ws)
    out = []
    for i in range(n):
        if rng.rand() < 0.6:
            tid = tids[rng.choice(len(tids), p=ws)]
            pool = items_by_topic[tid]
            it = pool[rng.randint(len(pool))] if pool else all_items[rng.randint(len(all_items))]
            interested = True
        else:
            it = all_items[rng.randint(len(all_items))]
            interested = it["tid"] in tids
        r = rng.rand()
        if interested and r < 0.55:
            ev = ("watch", 30 + rng.rand() * 570)
        elif interested and r < 0.70:
            ev = ("click", 0)
        elif not interested and r < 0.04:
            ev = ("click", 0)
        else:
            ev = ("expose", 0)
        out.append((it, ev))
    return out

def cos(a, b):
    na, nb = np.linalg.norm(a), np.linalg.norm(b)
    return float(a @ b / (na * nb)) if na > 0 and nb > 0 else 0.0

def topk_recall(profile_dist, mix, k=3):
    top_p = set(np.argsort(profile_dist)[-k:])
    top_t = set(np.argsort(mix)[-min(k, (mix > 0).sum()):])
    return len(top_p & top_t) / len(top_t)

results = {"convergence": [], "final": [], "drift": []}
CHECKPOINTS = [50, 100, 200, 400, 800, 1500]
for pi, persona in enumerate(PERSONAS):
    mix = true_mix(persona)
    for seed in range(3):
        rng = np.random.RandomState(pi * 10 + seed)
        prof = Profile()
        now = 0.0
        events = gen_events(persona, 1500, rng)
        curve = []
        for i, (it, (etype, dwell)) in enumerate(events, 1):
            now += 120  # 每 2 分钟一个事件
            prof.update(predict_proba(it["t"], it["u"], it["b"]), etype, dwell, now)
            if i in CHECKPOINTS:
                curve.append((i, cos(prof.dist("long"), mix)))
        results["convergence"].append(curve)
        results["final"].append({"persona": pi, "seed": seed,
                                 "cos_long": cos(prof.dist("long"), mix),
                                 "top3": topk_recall(prof.dist("long"), mix)})
        # 漂移测试：切换到"错位"新兴趣，看短期画像多快跟上
        new_persona = PERSONAS[(pi + 3) % len(PERSONAS)]
        new_mix = true_mix(new_persona)
        lag67 = lag100 = None
        for j, (it, (etype, dwell)) in enumerate(gen_events(new_persona, 800, rng), 1):
            now += 120
            prof.update(predict_proba(it["t"], it["u"], it["b"]), etype, dwell, now)
            rec = topk_recall(prof.dist("short"), new_mix)
            if lag67 is None and rec >= 0.66:
                lag67 = j
            if lag100 is None and rec >= 0.99:
                lag100 = j
        results["drift"].append({"persona": pi, "seed": seed, "lag67": lag67, "lag100": lag100})

fin = results["final"]
print(f"[{TAG}] 画像恢复(1500事件, 长期画像): cos={np.mean([r['cos_long'] for r in fin]):.3f}±{np.std([r['cos_long'] for r in fin]):.3f}  top3命中={np.mean([r['top3'] for r in fin]):.3f}")
avg_curve = {}
for curve in results["convergence"]:
    for n, c in curve:
        avg_curve.setdefault(n, []).append(c)
print(f"[{TAG}] 收敛曲线 (事件数 -> 长期画像 cos):")
for n in CHECKPOINTS:
    print(f"  {n}: {np.mean(avg_curve[n]):.3f}")
for crit, key in [("2/3主题跟上", "lag67"), ("全部主题跟上", "lag100")]:
    lags = [r[key] for r in results["drift"] if r[key]]
    cov = len(lags) / len(results["drift"])
    print(f"[{TAG}] 漂移-{crit}: {cov:.0%} 在800事件内达成" + (f", 平均滞后 {np.mean(lags):.0f} 事件" if lags else ""))
json.dump(results, open(SCRATCH + f"/persona_eval_{TAG}.json", "w"))
