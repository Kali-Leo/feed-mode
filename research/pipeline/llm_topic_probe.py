"""LLM 顺带出主题与情绪的可行性实测（E31）。

问题：脚本已在把标题发给 LLM 做四分类，若让同一次调用顺带给出 48 主题与 9 情绪，
能否替掉嵌入模型？本脚本测 qwen-flash 在这两轴上的准确率与额外 token 成本。

金标取 research/data/{topics,emotions}.jsonl.gz（deepseek-v4-flash 所标，
与被逼近的对象同源，因此这是「LLM 能否复现 LLM」的上界测量，不是绝对精度）。

用法: BENCH_KEY_dashscope=xxx python3 llm_topic_probe.py --n 400
"""
import argparse, gzip, json, os, statistics, sys, time, urllib.request
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO = os.path.dirname(ROOT)
URL = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
MODEL = "qwen-flash"


def load():
    tax = json.load(open(os.path.join(REPO, "interest-model", "taxonomy.json")))
    leaves = [l for g in tax["groups"].values() for l in g]
    emo = [e["name"] for e in json.load(open(os.path.join(REPO, "interest-model", "emotions.json")))["emotions"]]
    topics, emos, corpus = {}, {}, {}
    with gzip.open(os.path.join(ROOT, "data", "topics.jsonl.gz"), "rt", encoding="utf-8") as f:
        for line in f:
            d = json.loads(line); topics[d["b"]] = d["tid"]
    with gzip.open(os.path.join(ROOT, "data", "emotions.jsonl.gz"), "rt", encoding="utf-8") as f:
        for line in f:
            d = json.loads(line); emos[d["b"]] = d["tid"]
    with gzip.open(os.path.join(ROOT, "data", "corpus.jsonl.gz"), "rt", encoding="utf-8") as f:
        for line in f:
            d = json.loads(line)
            if d["b"] in topics and d["b"] in emos:
                corpus[d["b"]] = (d.get("t", ""), d.get("u", ""))
    ids = sorted(corpus)
    return leaves, emo, [(b, *corpus[b], topics[b], emos[b]) for b in ids]


def build_prompt(leaves, emo):
    return ("你是视频标注器。输入每行一个视频，格式：序号|标题|UP主。\n"
            "为每行给出主题编号与情绪编号。\n\n"
            "主题（编号:名称）：\n" + "，".join(f"{i+1}:{n}" for i, n in enumerate(leaves)) + "\n\n"
            "情绪（编号:名称）：\n" + "，".join(f"{i+1}:{n}" for i, n in enumerate(emo)) + "\n\n"
            '输出 JSON：{"r":{"1":"12,5","2":"3,1"}}，键为行号，值为「主题编号,情绪编号」，'
            "覆盖所有行，不要输出其他内容。")


def call(key, sysp, batch):
    payload = "\n".join(f"{i+1}|{t[:80]}|{u}" for i, (_, t, u, _, _) in enumerate(batch))
    body = {"model": MODEL, "max_tokens": 800, "response_format": {"type": "json_object"},
            "messages": [{"role": "system", "content": sysp}, {"role": "user", "content": payload}]}
    req = urllib.request.Request(URL, data=json.dumps(body).encode(),
        headers={"content-type": "application/json", "authorization": "Bearer " + key})
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=120) as r:
        d = json.load(r)
    out = json.loads(d["choices"][0]["message"]["content"])
    raw = out.get("r", out)
    res = {}
    for k, v in (raw.items() if isinstance(raw, dict) else enumerate(raw)):
        try:
            idx = int(k) - 1
            a, b = str(v).split(",")[:2]
            if 0 <= idx < len(batch):
                res[batch[idx][0]] = (int(a), int(b))
        except Exception:
            pass
    return res, d.get("usage", {}), time.time() - t0


if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("--n", type=int, default=400)
    ap.add_argument("--bs", type=int, default=25)
    a = ap.parse_args()
    key = os.environ.get("BENCH_KEY_dashscope")
    if not key:
        sys.exit("需要 BENCH_KEY_dashscope")
    leaves, emo, rows = load()
    rows = rows[:a.n]
    sysp = build_prompt(leaves, emo)
    batches = [rows[i:i + a.bs] for i in range(0, len(rows), a.bs)]
    print(f"{len(rows)} 条，{len(leaves)} 主题 / {len(emo)} 情绪，提示词 {len(sysp)} 字符\n")

    preds, usage, lat = {}, [], []
    def run(b):
        try: return call(key, sysp, b)
        except Exception as e:
            print("  err:", str(e)[:90], file=sys.stderr); return {}, {}, None
    with ThreadPoolExecutor(3) as ex:
        for r, u, dt in ex.map(run, batches):
            preds.update(r); usage.append(u)
            if dt: lat.append(dt)

    tok_hit = emo_hit = grp_hit = n = 0
    group_of = {}
    tax = json.load(open(os.path.join(REPO, "interest-model", "taxonomy.json")))
    for gname, ls in tax["groups"].items():
        for l in ls: group_of[leaves.index(l)] = gname
    for b, t, u, gt, ge in rows:
        p = preds.get(b)
        if not p: continue
        n += 1
        pt, pe = p[0] - 1, p[1] - 1
        tok_hit += pt == gt - 1
        emo_hit += pe == ge - 1
        grp_hit += group_of.get(pt) == group_of.get(gt - 1)
    tin = sum(x.get("prompt_tokens", 0) for x in usage)
    tout = sum(x.get("completion_tokens", 0) for x in usage)
    res = {"n": n, "covered": len(preds),
           "topic_top1": round(tok_hit / n, 4) if n else 0,
           "topic_group": round(grp_hit / n, 4) if n else 0,
           "emotion_top1": round(emo_hit / n, 4) if n else 0,
           "tok_in_per_item": round(tin / max(n, 1), 1), "tok_out_per_item": round(tout / max(n, 1), 1),
           "cost_per_1k_cny": round((tin * 0.15 + tout * 1.5) / 1e6 / max(n, 1) * 1000, 5),
           "latency_p50_s": round(statistics.median(lat), 2) if lat else None}
    print(json.dumps(res, ensure_ascii=False, indent=1))
    json.dump(res, open(os.path.join(ROOT, "results", "llm_topic_probe.json"), "w"),
              ensure_ascii=False, indent=1)
