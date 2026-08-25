"""BERT 天花板基准：hfl/rbt3 多标签微调（pro+neg 双头），复用 splits.json。
--silver: 训练后给全语料打银标 -> silver.jsonl"""
import json, sys, os
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")  # socks 代理 transformers 不支持，改走国内镜像
for _k in ["http_proxy", "https_proxy", "all_proxy", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"]:
    os.environ.pop(_k, None)
import numpy as np
import torch
from torch.utils.data import DataLoader, Dataset
from transformers import AutoTokenizer, AutoModelForSequenceClassification
from sklearn.metrics import f1_score, accuracy_score, precision_score, recall_score

SCRATCH = "/tmp/claude-1000/-home-leo----bilibili/7ae81ed2-efb1-446d-95dc-6901201fe793/scratchpad"
DEV = "cuda" if torch.cuda.is_available() else "cpu"
corpus = {r["b"]: r for l in open(SCRATCH + "/corpus.jsonl") for r in [json.loads(l)]}
labels = {r["b"]: r for l in open(SCRATCH + "/labels.jsonl") for r in [json.loads(l)]}
splits = json.load(open(SCRATCH + "/splits.json"))

def mk(bs):
    out = []
    for b in bs:
        c, lab = corpus.get(b), labels.get(b)
        if c and lab:
            out.append((c["t"] + " [SEP] " + c["u"], [float(lab["pro"]), float(lab["neg"])]))
    return out

tr, va, te = mk(splits["train"]), mk(splits["val"]), mk(splits["test"])
print(f"train={len(tr)} val={len(va)} test={len(te)} dev={DEV}")

tok = AutoTokenizer.from_pretrained("hfl/rbt3")
model = AutoModelForSequenceClassification.from_pretrained(
    "hfl/rbt3", num_labels=2, problem_type="multi_label_classification").to(DEV)

class DS(Dataset):
    def __init__(self, data): self.data = data
    def __len__(self): return len(self.data)
    def __getitem__(self, i): return self.data[i]

def collate(batch):
    texts, ys = zip(*batch)
    enc = tok(list(texts), padding=True, truncation=True, max_length=48, return_tensors="pt")
    enc["labels"] = torch.tensor(ys)
    return enc

def evaluate(data):
    model.eval()
    ps, ys = [], []
    with torch.no_grad():
        for enc in DataLoader(DS(data), batch_size=128, collate_fn=collate):
            y = enc.pop("labels")
            enc = {k: v.to(DEV) for k, v in enc.items()}
            logits = model(**enc).logits.sigmoid().cpu().numpy()
            ps.append(logits); ys.append(y.numpy())
    return np.vstack(ps), np.vstack(ys)

opt = torch.optim.AdamW(model.parameters(), lr=3e-5)
scaler = torch.amp.GradScaler()
loader = DataLoader(DS(tr), batch_size=64, shuffle=True, collate_fn=collate)
for ep in range(3):
    model.train()
    tot = 0.0
    for enc in loader:
        enc = {k: v.to(DEV) for k, v in enc.items()}
        opt.zero_grad()
        with torch.amp.autocast(DEV):
            loss = model(**enc).loss
        scaler.scale(loss).backward()
        scaler.step(opt); scaler.update()
        tot += loss.item()
    p, y = evaluate(va)
    print(f"ep{ep} loss={tot/len(loader):.4f} val F1 pro={f1_score(y[:,0],(p[:,0]>.5)):.3f} neg={f1_score(y[:,1],(p[:,1]>.5)):.3f}", flush=True)

# val 上调阈值，test 上报告
p_va, y_va = evaluate(va)
p_te, y_te = evaluate(te)
rep = {}
for i, task in enumerate(["pro", "neg"]):
    thrs = np.linspace(0.2, 0.8, 25)
    thr = max(thrs, key=lambda t: f1_score(y_va[:, i], (p_va[:, i] > t), zero_division=0))
    pred = (p_te[:, i] > thr).astype(int)
    rep[task] = {"thr": float(thr), "acc": accuracy_score(y_te[:, i], pred),
                 "P": precision_score(y_te[:, i], pred, zero_division=0),
                 "R": recall_score(y_te[:, i], pred, zero_division=0),
                 "F1": f1_score(y_te[:, i], pred, zero_division=0)}
    print(f"BERT TEST {task}: {{k: round(v,3) for k,v in rep[task].items()}}", rep[task], flush=True)
json.dump(rep, open(SCRATCH + "/report_bert.json", "w"), indent=1)

if "--silver" in sys.argv:
    gold = set(labels)
    todo = [(b, c["t"] + " [SEP] " + c["u"]) for b, c in corpus.items() if b not in gold]
    print(f"silver-labeling {len(todo)}", flush=True)
    model.eval()
    with open(SCRATCH + "/silver.jsonl", "w") as f:
        with torch.no_grad():
            for off in range(0, len(todo), 256):
                chunk = todo[off:off + 256]
                enc = tok([t for _, t in chunk], padding=True, truncation=True, max_length=48, return_tensors="pt")
                enc = {k: v.to(DEV) for k, v in enc.items()}
                p = model(**enc).logits.sigmoid().cpu().numpy()
                for (b, _), row in zip(chunk, p):
                    # 银标只收高置信样本，避免教师噪声污染学生
                    pro = 1 if row[0] > 0.8 else (0 if row[0] < 0.2 else -1)
                    neg = 1 if row[1] > 0.8 else (0 if row[1] < 0.2 else -1)
                    if pro != -1 and neg != -1:
                        f.write(json.dumps({"b": b, "pro": pro, "neg": neg}) + "\n")
    print("silver done", flush=True)
torch.save(model.state_dict(), SCRATCH + "/bert_heads.pt")
print("DONE", flush=True)
