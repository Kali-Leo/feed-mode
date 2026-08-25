"""一致性校验：JS 推理 vs sklearn。三层：
1) mmh3 哈希逐 token 对齐  2) JS(int8) vs numpy(int8) 概率对齐  3) int8 vs float32 的判决翻转率"""
import json, subprocess, random
import numpy as np
from sklearn.feature_extraction.text import HashingVectorizer
from sklearn.utils import murmurhash3_32

SCRATCH = "/tmp/claude-1000/-home-leo----bilibili/7ae81ed2-efb1-446d-95dc-6901201fe793/scratchpad"

# 1) 哈希对齐
toks = ["a", "ab", "深", "深度", "度学", "Rust", " \x01 ", "猫🐱", "x" * 7]
node_out = subprocess.run(["node", "-e", f'''
const {{ mmh3 }} = require("{SCRATCH}/classifier.js");
const enc = new TextEncoder();
console.log(JSON.stringify({json.dumps(toks, ensure_ascii=False)}.map(t => mmh3(enc.encode(t)))));'''],
    capture_output=True, text=True)
js_hashes = json.loads(node_out.stdout)
py_hashes = [int(murmurhash3_32(t.encode("utf-8"), seed=0, positive=False)) for t in toks]
assert js_hashes == py_hashes, f"HASH MISMATCH\njs={js_hashes}\npy={py_hashes}"
print("1) mmh3 对齐: OK", flush=True)

# 2+3) 模型概率对齐
corpus = [json.loads(l) for l in open(SCRATCH + "/corpus.jsonl")]
random.seed(7)
sample = random.sample(corpus, 300)
texts = [(r["t"] + " \x01 " + r["u"]) for r in sample]

node_in = json.dumps([[r["t"], r["u"]] for r in sample], ensure_ascii=False)
node_out = subprocess.run(["node", "-e", f'''
const {{ fmClassify }} = require("{SCRATCH}/classifier.js");
const rows = {node_in};
console.log(JSON.stringify(rows.map(([t,u]) => {{ const r = fmClassify(t,u); return [r.pro.p, r.neg.p]; }})));'''],
    capture_output=True, text=True)
js_probs = np.array(json.loads(node_out.stdout))

for ti, task in enumerate(["pro", "neg"]):
    d = np.load(SCRATCH + f"/model_{task}.npz")
    w = d["w"].astype(np.float32)
    scale = float(np.abs(w).max() / 127.0) or 1.0
    q = np.clip(np.round(w / scale), -127, 127).astype(np.float32) * scale
    vec = HashingVectorizer(analyzer="char", ngram_range=(int(d["ng_lo"]), int(d["ng_hi"])),
                            n_features=int(d["dims"]), alternate_sign=False, norm="l2")
    X = vec.transform(texts)
    s_float = X @ w + float(d["b"])
    s_quant = X @ q + float(d["b"])
    p_float = 1 / (1 + np.exp(-s_float))
    p_quant = 1 / (1 + np.exp(-s_quant))
    max_dp = float(np.abs(js_probs[:, ti] - p_quant).max())
    flips = int(((p_quant > 0.5) != (p_float > 0.5)).sum())
    print(f"{task}: JS-vs-numpy(int8) 最大概率差={max_dp:.2e}  int8-vs-float 判决翻转 {flips}/300", flush=True)
    assert max_dp < 1e-4, "JS 与训练侧不一致！"
print("PARITY OK", flush=True)
