"""标签净化合并：优先级 evalclean(v4-pro) > arb(v4-pro) > flash 两遍共识 > flash 单遍。
原 labels.jsonl 备份为 labels_flash1.jsonl，合并结果写回 labels.jsonl。"""
import json, shutil
from collections import Counter

S = "/tmp/claude-1000/-home-leo----bilibili/7ae81ed2-efb1-446d-95dc-6901201fe793/scratchpad"

def load(name):
    try:
        return {json.loads(l)["b"]: json.loads(l) for l in open(S + name)}
    except FileNotFoundError:
        return {}

flash1 = load("/labels.jsonl")
second = load("/labels_second.jsonl")
arb = load("/labels_arb.jsonl")
ev = load("/labels_eval.jsonl")
shutil.copy(S + "/labels.jsonl", S + "/labels_flash1.jsonl")

src_cnt = Counter()
out = []
for b, g in flash1.items():
    if b in ev:
        r, src = ev[b], "v4pro_eval"
    elif b in arb:
        r, src = arb[b], "v4pro_arb"
    elif b in second and second[b]["pro"] == g["pro"] and second[b]["neg"] == g["neg"]:
        r, src = g, "consensus"
    elif b in second:
        r, src = g, "flash_disagree_unarbed"  # 仲裁失败批次的兜底
    else:
        r, src = g, "flash_single"
    src_cnt[src] += 1
    out.append({"b": b, "pro": r["pro"], "neg": r["neg"], "src": src})
with open(S + "/labels.jsonl", "w") as f:
    for r in out:
        f.write(json.dumps(r) + "\n")
print("merged:", dict(src_cnt))

# 一致性统计：flash两遍、flash vs v4-pro
both = [b for b in flash1 if b in second]
ap = sum(flash1[b]["pro"] == second[b]["pro"] for b in both) / len(both)
an = sum(flash1[b]["neg"] == second[b]["neg"] for b in both) / len(both)
print(f"flash 两遍一致率 (n={len(both)}): pro {ap:.1%}  neg {an:.1%}")
evb = [b for b in ev if b in flash1]
if evb:
    ap = sum(flash1[b]["pro"] == ev[b]["pro"] for b in evb) / len(evb)
    an = sum(flash1[b]["neg"] == ev[b]["neg"] for b in evb) / len(evb)
    print(f"flash vs v4-pro (评测集 n={len(evb)}): pro {ap:.1%}  neg {an:.1%}")
