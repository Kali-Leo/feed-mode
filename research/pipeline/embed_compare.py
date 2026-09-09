"""候选嵌入模型对比（E30）：同一语料、同一分类头、同一冻结切分。

回答两件事：换掉当前双模型（bge-small-zh + MiniLM）是否掉精度，以及各自体积。
评测口径沿用 E5：按 UP 主分组的冻结切分，test 集标签取 v4-pro 提纯的 pro 轴。

用法:
  python3 embed_compare.py                      # 跑全部候选
  python3 embed_compare.py --models e5,granite  # 只跑指定
"""
import argparse, gzip, json, os, time
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
# 与 daemon/app.py:72-74 同样处理：httpx 不认 socks:// 这种 scheme，
# 且走镜像不需要代理，直接清掉
for _k in ["http_proxy", "https_proxy", "all_proxy", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"]:
    os.environ.pop(_k, None)

CANDIDATES = {
    "bge":      ("BAAI/bge-small-zh-v1.5", None, "当前 B站侧"),
    "minilm":   ("sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2", None, "当前 YouTube 侧"),
    "e5":       ("intfloat/multilingual-e5-small", "query: ", "Breadcrumb 所用"),
    "granite":  ("ibm-granite/granite-embedding-107m-multilingual", None, "MTEB 100M 以下领先"),
}


def load_data():
    splits = json.load(open(os.path.join(ROOT, "data", "splits.json")))
    lab = {}
    with gzip.open(os.path.join(ROOT, "data", "labels_clean.jsonl.gz"), "rt", encoding="utf-8") as f:
        for line in f:
            d = json.loads(line)
            lab[d["b"]] = (d["pro"], d.get("src", ""))
    corpus = {}
    with gzip.open(os.path.join(ROOT, "data", "corpus.jsonl.gz"), "rt", encoding="utf-8") as f:
        for line in f:
            d = json.loads(line)
            corpus[d["b"]] = f"{d.get('t','')} {d.get('u','')}".strip()

    def take(ids, pure_only=False):
        out = []
        for b in ids:
            if b in lab and b in corpus:
                pro, src = lab[b]
                if pure_only and src != "v4pro_eval":
                    continue
                out.append((b, corpus[b], pro))
        return out

    return take(splits["train"]), take(splits["test"], pure_only=True)


def dir_size_mb(model_id):
    import glob
    pat = os.path.expanduser("~/.cache/huggingface/hub/models--" + model_id.replace("/", "--"))
    tot = 0
    for p in glob.glob(pat + "/**/*", recursive=True):
        if os.path.isfile(p) and not os.path.islink(p):
            tot += os.path.getsize(p)
    return tot / 1048576


def run(key, train, test):
    from sentence_transformers import SentenceTransformer
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import f1_score, accuracy_score, precision_score, recall_score
    model_id, prefix, note = CANDIDATES[key]
    t0 = time.time()
    m = SentenceTransformer(model_id, device="cuda")
    load_s = time.time() - t0

    def enc(rows):
        txt = [(prefix or "") + t for _, t, _ in rows]
        return m.encode(txt, batch_size=128, normalize_embeddings=True,
                        show_progress_bar=False, convert_to_numpy=True)

    t1 = time.time()
    Xtr = enc(train)
    enc_s = time.time() - t1
    Xte = enc(test)
    ytr = np.array([p for _, _, p in train])
    yte = np.array([p for _, _, p in test])

    clf = LogisticRegression(max_iter=2000, class_weight="balanced", C=1.0)
    clf.fit(Xtr, ytr)
    pred = clf.predict(Xte)
    return {
        "key": key, "model": model_id, "note": note,
        "dims": int(Xtr.shape[1]), "cache_mb": round(dir_size_mb(model_id), 1),
        "load_s": round(load_s, 1),
        "encode_ms_per_item": round(enc_s / len(train) * 1000, 2),
        "acc": round(accuracy_score(yte, pred), 4),
        "precision": round(precision_score(yte, pred, zero_division=0), 4),
        "recall": round(recall_score(yte, pred, zero_division=0), 4),
        "f1": round(f1_score(yte, pred, zero_division=0), 4),
    }


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", default=",".join(CANDIDATES))
    ap.add_argument("--out", default=os.path.join(ROOT, "results", "embed_compare.json"))
    args = ap.parse_args()
    train, test = load_data()
    print(f"训练 {len(train)} 条，测试 {len(test)} 条（test ∩ v4pro_eval，正例率 "
          f"{sum(p for _, _, p in test)/len(test):.1%}）\n")
    out = []
    for k in args.models.split(","):
        if k not in CANDIDATES:
            print("跳过未知候选", k); continue
        try:
            r = run(k, train, test)
            out.append(r)
            print(json.dumps(r, ensure_ascii=False))
        except Exception as e:
            print(f"{k} 失败: {str(e)[:200]}")
    if out:
        json.dump(out, open(args.out, "w"), ensure_ascii=False, indent=1)
        print("\n写入", args.out)
