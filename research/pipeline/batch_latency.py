"""批量大小对响应速度与成本的影响（E32）。

线上 BATCH_SIZE=40 是 E1 为省 token 定的，从未按延迟调过。本脚本测各批量下
「一批多久回来」（用户看到卡片的等待）与「每条多少钱」，找同时满足快与省的工作点。

用法: BENCH_KEY_dashscope=xxx BENCH_KEY_deepseek=xxx python3 batch_latency.py
"""
import argparse, json, os, statistics, sys, time, urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from model_bench import VENDORS, load_prompt, load_eval_set, call

SIZES = [5, 10, 20, 40]
REPS = 4


def measure(vendor, key, items, bs):
    ep, model, pin, pout, _ = VENDORS[vendor]
    sysp = load_prompt()
    lat, tin, tout, ok = [], 0, 0, 0
    for r in range(REPS):
        batch = items[r * bs:(r + 1) * bs]
        if len(batch) < bs:
            break
        try:
            res, u, dt = call(ep, model, key, sysp, batch, timeout=120)
        except Exception as e:
            print("   err:", str(e)[:70], file=sys.stderr)
            continue
        lat.append(dt); ok += len(res)
        tin += u.get("prompt_tokens", 0); tout += u.get("completion_tokens", 0)
    if not lat:
        return None
    n = REPS * bs
    return {
        "batch": bs,
        "wait_s": round(statistics.median(lat), 2),          # 用户等一批的时间
        "ms_per_item": round(statistics.median(lat) / bs * 1000, 1),
        "cost_per_1k": round((tin * pin + tout * pout) / 1e6 / max(ok, 1) * 1000, 5),
        "tok_in_per_item": round(tin / max(ok, 1), 1),
        "covered": ok,
    }


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--vendors", default="dashscope,deepseek")
    a = ap.parse_args()
    items = load_eval_set(200)
    for v in a.vendors.split(","):
        key = os.environ.get("BENCH_KEY_" + v)
        if not key:
            print(f"跳过 {v}"); continue
        print(f"\n=== {v} / {VENDORS[v][1]}")
        print(f"{'批量':>5}{'一批等待':>10}{'每条':>9}{'每千条':>11}{'输入tok/条':>11}")
        rows = []
        for bs in SIZES:
            r = measure(v, key, items, bs)
            if r:
                rows.append(r)
                print(f"{r['batch']:>5}{r['wait_s']:>9.2f}s{r['ms_per_item']:>8.0f}ms"
                      f"{'¥%.4f' % r['cost_per_1k']:>11}{r['tok_in_per_item']:>11.1f}")
        json.dump(rows, open(os.path.join(ROOT, "results", f"batch_latency_{v}.json"), "w"),
                  ensure_ascii=False, indent=1)
