"""导出 int8 量化模型为自包含 JS + 生成 node 侧推理器；配套 parity_test.py 校验一致性。"""
import json, base64
import numpy as np

SCRATCH = "/tmp/claude-1000/-home-leo----bilibili/7ae81ed2-efb1-446d-95dc-6901201fe793/scratchpad"

models = {}
for task in ["pro", "neg"]:
    d = np.load(SCRATCH + f"/model_{task}.npz")
    w = d["w"].astype(np.float32)
    scale = float(np.abs(w).max() / 127.0) or 1.0
    q = np.clip(np.round(w / scale), -127, 127).astype(np.int8)
    models[task] = {
        "dims": int(d["dims"]), "ng": [int(d["ng_lo"]), int(d["ng_hi"])],
        "scale": scale, "b": float(d["b"]),
        "w_b64": base64.b64encode(q.tobytes()).decode(),
    }
    nz = int((q != 0).sum())
    print(f"{task}: dims={models[task]['dims']} ngram={models[task]['ng']} int8 {len(q)/1024:.0f}KB (nonzero {nz})")

js = """// 自动生成：字符n-gram哈希线性分类器（与训练侧 sklearn HashingVectorizer+LogisticRegression 位级对齐）
// murmurhash3_32 (x86, seed=0)，UTF-8 字节输入，与 sklearn.utils.murmurhash3_32 一致
function mmh3(bytes) {
  const c1 = 0xcc9e2d51, c2 = 0x1b873593;
  let h = 0;
  const n = bytes.length - (bytes.length % 4);
  for (let i = 0; i < n; i += 4) {
    let k = (bytes[i] | (bytes[i+1] << 8) | (bytes[i+2] << 16) | (bytes[i+3] << 24)) >>> 0;
    k = Math.imul(k, c1); k = (k << 15) | (k >>> 17); k = Math.imul(k, c2);
    h ^= k; h = (h << 13) | (h >>> 19); h = (Math.imul(h, 5) + 0xe6546b64) >>> 0;
  }
  let k = 0;
  const tail = bytes.length % 4;
  if (tail >= 3) k ^= bytes[n+2] << 16;
  if (tail >= 2) k ^= bytes[n+1] << 8;
  if (tail >= 1) {
    k ^= bytes[n];
    k = Math.imul(k >>> 0, c1); k = (k << 15) | (k >>> 17); k = Math.imul(k, c2);
    h ^= k;
  }
  h ^= bytes.length;
  h ^= h >>> 16; h = Math.imul(h, 0x85ebca6b);
  h ^= h >>> 13; h = Math.imul(h, 0xc2b2ae35);
  h ^= h >>> 16;
  return h | 0; // 有符号 int32
}
const _enc = new TextEncoder();
function _features(text, ngLo, ngHi, dims) {
  // 与 sklearn char 分析器对齐：先小写，再把连续(≥2)空白折叠为单个空格
  const s = text.toLowerCase().replace(/\s\s+/g, " ");
  const chars = Array.from(s); // 按 Unicode 码点切分（emoji 等非 BMP 字符与 Python 对齐）
  const counts = new Map();
  for (let n = ngLo; n <= ngHi; n++) {
    for (let i = 0; i + n <= chars.length; i++) {
      const tok = chars.slice(i, i + n).join("");
      const h = mmh3(_enc.encode(tok));
      const idx = Math.abs(h) % dims;
      counts.set(idx, (counts.get(idx) || 0) + 1);
    }
  }
  let norm = 0;
  for (const v of counts.values()) norm += v * v;
  norm = Math.sqrt(norm) || 1;
  return { counts, norm };
}
function _decodeW(b64) {
  const bin = (typeof atob === "function") ? atob(b64) : Buffer.from(b64, "base64").toString("binary");
  const w = new Int8Array(bin.length);
  for (let i = 0; i < bin.length; i++) w[i] = (bin.charCodeAt(i) << 24) >> 24;
  return w;
}
const FM_MODELS = MODELS_JSON;
for (const m of Object.values(FM_MODELS)) m.w = _decodeW(m.w_b64);
// 返回 {pro:{p,score}, neg:{p,score}}；p 为 sigmoid 概率
function fmClassify(title, up) {
  const text = String(title || "") + " \\x01 " + String(up || "");
  const out = {};
  for (const [task, m] of Object.entries(FM_MODELS)) {
    const { counts, norm } = _features(text, m.ng[0], m.ng[1], m.dims);
    let s = 0;
    for (const [idx, v] of counts) s += m.w[idx] * v;
    s = (s * m.scale) / norm + m.b;
    out[task] = { score: s, p: 1 / (1 + Math.exp(-s)) };
  }
  return out;
}
if (typeof module !== "undefined") module.exports = { fmClassify, mmh3 };
"""
js = js.replace("MODELS_JSON", json.dumps(models))
open(SCRATCH + "/classifier.js", "w").write(js)
print("wrote classifier.js", len(js) // 1024, "KB")
