"""候选 LLM 四分类对比评测（E27）。

与既有打标脚本的区别：直连各家 OpenAI 兼容端点（服务端无 CORS 限制），
不再走 browser_server.py 的浏览器通道，因此不需要浏览器停在 bilibili.com。

提示词从 user.js 动态提取（同 evidence.py 的做法，保证测的就是产品行为）。
评测集：splits.json 的 test 集中 src=="v4pro_eval" 的子集，从未参与训练。
标签是 pro/neg 二元轴，四分类输出按 p→pro=1、g/e/j→pro=0 映射后比对。

用法:
  export BENCH_KEY_zhipu=xxx BENCH_KEY_dashscope=xxx
  python3 model_bench.py --vendors zhipu,dashscope --n 400
  python3 model_bench.py --vendors deepseek --n 400 --model deepseek-v4-pro
"""
import argparse, gzip, json, os, re, statistics, sys, time, urllib.request
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO = os.path.dirname(ROOT)

VENDORS = {
    # key: (endpoint, 默认模型, 输入元/百万, 输出元/百万)
    "deepseek":   ("https://api.deepseek.com/chat/completions", "deepseek-v4-flash", 1.58, 4.75),
    "dashscope":  ("https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions", "qwen-flash", 0.15, 1.50),
    "zhipu":      ("https://open.bigmodel.cn/api/paas/v4/chat/completions", "glm-4.7-flash", 0.0, 0.0),
    "ark":        ("https://ark.cn-beijing.volces.com/api/v3/chat/completions", "doubao-lite-32k", 0.30, 2.40),
    "siliconflow": ("https://api.siliconflow.cn/v1/chat/completions", "Qwen/Qwen3-8B", 0.0, 0.0),
}

CODE = {"p": "pro", "g": "good", "e": "ent", "j": "junk", "?": "?"}


def load_prompt():
    src = open(os.path.join(REPO, "bilibili-feed-mode.user.js"), encoding="utf-8").read()
    i = src.index("const SYSTEM_PROMPT = `") + len("const SYSTEM_PROMPT = `")
    return src[i:src.index("`;", i)]


def load_eval_set(n):
    """返回 [(bvid, 标题, up主, gold_pro)]，只取从未参与训练的 v4pro_eval 子集。"""
    splits = json.load(open(os.path.join(ROOT, "data", "splits.json")))
    test = set(splits["test"])
    labels = {}
    with gzip.open(os.path.join(ROOT, "data", "labels_clean.jsonl.gz"), "rt", encoding="utf-8") as f:
        for line in f:
            d = json.loads(line)
            if d["b"] in test and d.get("src") == "v4pro_eval":
                labels[d["b"]] = d["pro"]
    corpus = {}
    with gzip.open(os.path.join(ROOT, "data", "corpus.jsonl.gz"), "rt", encoding="utf-8") as f:
        for line in f:
            d = json.loads(line)
            if d["b"] in labels:
                corpus[d["b"]] = (d.get("t", ""), d.get("u", ""))
    items = [(b, corpus[b][0], corpus[b][1], labels[b]) for b in sorted(labels) if b in corpus]
    return items[:n] if n else items


def call(endpoint, model, key, sys_prompt, batch, timeout=120):
    payload = "\n".join(
        f"{i+1}|{str(t)[:80].replace('|',' ')}|{str(u).replace('|',' ')}|"
        for i, (_, t, u, _) in enumerate(batch))
    body = {
        "model": model, "max_tokens": 500,
        "response_format": {"type": "json_object"},
        "messages": [{"role": "system", "content": sys_prompt},
                     {"role": "user", "content": payload}],
    }
    if model.startswith("deepseek"):
        body["thinking"] = {"type": "disabled"}   # 否则思考 token 按输出计费
    req = urllib.request.Request(
        endpoint, data=json.dumps(body).encode(),
        headers={"content-type": "application/json", "authorization": "Bearer " + key})
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=timeout) as r:
        d = json.load(r)
    out = json.loads(d["choices"][0]["message"]["content"])
    raw = out.get("r", out)
    entries = (list(enumerate(raw)) if isinstance(raw, list)
               else [(int(k) - 1, v) for k, v in raw.items()])
    res = {}
    for idx, v in entries:
        c = CODE.get(str(v.get("c") if isinstance(v, dict) else v).strip())
        if c and 0 <= idx < len(batch):
            res[batch[idx][0]] = c
    return res, d.get("usage", {}), time.time() - t0


def bench(vendor, model, key, items, bs=40, workers=3):
    endpoint, defmodel, pin, pout = VENDORS[vendor]
    model = model or defmodel
    sys_prompt = load_prompt()
    batches = [items[i:i + bs] for i in range(0, len(items), bs)]
    preds, usage, lat, errs = {}, [], [], 0

    def run(b):
        try:
            return call(endpoint, model, key, sys_prompt, b)
        except Exception as e:
            print("  err:", str(e)[:100], file=sys.stderr)
            return {}, {}, None

    with ThreadPoolExecutor(workers) as ex:
        for res, u, dt in ex.map(run, batches):
            if not res:
                errs += 1
                continue
            preds.update(res)
            usage.append(u)
            if dt:
                lat.append(dt)

    tp = fp = fn = tn = 0
    for b, _, _, gold in items:
        c = preds.get(b)
        if c is None:
            continue
        pred = 1 if c == "pro" else 0
        tp += pred == 1 and gold == 1
        fp += pred == 1 and gold == 0
        fn += pred == 0 and gold == 1
        tn += pred == 0 and gold == 0
    n = tp + fp + fn + tn
    prec = tp / (tp + fp) if tp + fp else 0.0
    rec = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
    tin = sum(u.get("prompt_tokens", 0) for u in usage)
    tout = sum(u.get("completion_tokens", 0) for u in usage)
    cost1k = (tin * pin + tout * pout) / 1e6 / max(n, 1) * 1000
    dist = {}
    for c in preds.values():
        dist[c] = dist.get(c, 0) + 1
    return {
        "vendor": vendor, "model": model, "n": n, "covered": len(preds), "batch_errs": errs,
        "acc": round((tp + tn) / n, 4) if n else 0, "precision": round(prec, 4),
        "recall": round(rec, 4), "f1": round(f1, 4),
        "tok_in": tin, "tok_out": tout, "cost_per_1k_cny": round(cost1k, 5),
        "latency_p50_s": round(statistics.median(lat), 2) if lat else None,
        "class_dist": dist,
    }


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--vendors", required=True, help="逗号分隔，见 VENDORS")
    ap.add_argument("--model", default=None, help="覆盖默认模型 id（只在单厂商时用）")
    ap.add_argument("--n", type=int, default=400)
    ap.add_argument("--out", default=os.path.join(ROOT, "results", "model_bench.json"))
    args = ap.parse_args()

    items = load_eval_set(args.n)
    print(f"评测集 {len(items)} 条（test ∩ v4pro_eval，正例率 "
          f"{sum(i[3] for i in items) / len(items):.1%}）\n")
    out = []
    for v in args.vendors.split(","):
        key = os.environ.get("BENCH_KEY_" + v)
        if not key:
            print(f"跳过 {v}：未设 BENCH_KEY_{v}")
            continue
        print(f"跑 {v} …")
        r = bench(v, args.model, key, items)
        out.append(r)
        print("  " + json.dumps(r, ensure_ascii=False))
    if out:
        prev = []
        if os.path.exists(args.out):
            prev = json.load(open(args.out))
        json.dump(prev + out, open(args.out, "w"), ensure_ascii=False, indent=1)
        print("\n写入", args.out)
