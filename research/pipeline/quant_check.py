"""q8 量化对本任务精度的影响（E31）。

E30 的精度是 fp32 测的，部署用的却是 q8 ONNX。这里用同一份切分、同一个分类头，
把两者放在一起测，回答「量化到底掉多少」。

用法: python3 quant_check.py
"""
import gzip, json, os, time
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
for _k in ["http_proxy", "https_proxy", "all_proxy", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"]:
    os.environ.pop(_k, None)

MODEL = "intfloat/multilingual-e5-small"
ONNX_REPO = "Xenova/multilingual-e5-small"     # 浏览器实际加载的那一份
PREFIX = "query: "


def load_data():
    import sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from embed_compare import load_data as ld
    return ld()


def fp32_vectors(texts):
    from sentence_transformers import SentenceTransformer
    m = SentenceTransformer(MODEL, device="cuda")
    return m.encode([PREFIX + t for t in texts], batch_size=128,
                    normalize_embeddings=True, show_progress_bar=False, convert_to_numpy=True)


def q8_vectors(texts):
    """用 onnxruntime 跑与浏览器同一份 q8 权重。"""
    import onnxruntime as ort
    from huggingface_hub import hf_hub_download
    from transformers import AutoTokenizer
    path = hf_hub_download(ONNX_REPO, "onnx/model_quantized.onnx")
    tok = AutoTokenizer.from_pretrained(MODEL)
    sess = ort.InferenceSession(path, providers=["CPUExecutionProvider"])
    names = {i.name for i in sess.get_inputs()}
    out = []
    B = 64
    for i in range(0, len(texts), B):
        enc = tok([PREFIX + t for t in texts[i:i + B]], padding=True, truncation=True,
                  max_length=128, return_tensors="np")
        feed = {k: v for k, v in enc.items() if k in names}
        if "token_type_ids" in names and "token_type_ids" not in feed:
            feed["token_type_ids"] = np.zeros_like(enc["input_ids"])
        last = sess.run(None, feed)[0]
        mask = enc["attention_mask"][..., None].astype(last.dtype)
        vec = (last * mask).sum(1) / np.clip(mask.sum(1), 1e-9, None)
        vec /= np.clip(np.linalg.norm(vec, axis=1, keepdims=True), 1e-9, None)
        out.append(vec)
    return np.vstack(out)


def score(Xtr, ytr, Xte, yte):
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import accuracy_score, f1_score, precision_score, recall_score
    clf = LogisticRegression(max_iter=2000, class_weight="balanced").fit(Xtr, ytr)
    p = clf.predict(Xte)
    return {"acc": round(accuracy_score(yte, p), 4), "f1": round(f1_score(yte, p, zero_division=0), 4),
            "precision": round(precision_score(yte, p, zero_division=0), 4),
            "recall": round(recall_score(yte, p, zero_division=0), 4)}


if __name__ == "__main__":
    train, test = load_data()
    ttr = [t for _, t, _ in train]; tte = [t for _, t, _ in test]
    ytr = np.array([p for _, _, p in train]); yte = np.array([p for _, _, p in test])
    print(f"训练 {len(ttr)} 条，测试 {len(tte)} 条\n")

    t0 = time.time(); A_tr, A_te = fp32_vectors(ttr), fp32_vectors(tte)
    print(f"fp32 编码完成 {time.time()-t0:.0f}s")
    t0 = time.time(); B_tr, B_te = q8_vectors(ttr), q8_vectors(tte)
    print(f"q8   编码完成 {time.time()-t0:.0f}s")

    cos = float(np.mean(np.sum(A_te * B_te, axis=1)))
    r = {"fp32": score(A_tr, ytr, A_te, yte), "q8": score(B_tr, ytr, B_te, yte),
         "vec_cos_fp32_vs_q8": round(cos, 4)}
    print("\n" + json.dumps(r, ensure_ascii=False, indent=1))
    json.dump(r, open(os.path.join(ROOT, "results", "quant_check.json"), "w"),
              ensure_ascii=False, indent=1)
