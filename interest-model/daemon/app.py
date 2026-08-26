"""个人兴趣模型 · 本地服务（完整轨）

运行: python3 app.py [--port 21456]
安全: 只绑 127.0.0.1；写接口需令牌（首次运行自动生成，打印在控制台并存 ~/.interest-model/token）；
     跨域仅放行 bilibili/youtube 来源；读接口不发 CORS 头（外站页面拿不到响应）。
浏览器端用法: 插件把事件 POST 到 http://127.0.0.1:<port>/events，头带 X-IM-Token。
仪表盘: 浏览器打开 http://127.0.0.1:<port>/
"""
import argparse, json, os, secrets, sqlite3, time, threading
import numpy as np

BASE_DIR = os.path.expanduser("~/.interest-model")
os.makedirs(BASE_DIR, exist_ok=True)
TOKEN_PATH = os.path.join(BASE_DIR, "token")
DB_PATH = os.path.join(BASE_DIR, "events.db")
HERE = os.path.dirname(os.path.abspath(__file__))
TAX = json.load(open(os.path.join(HERE, "..", "taxonomy.json")))
LEAVES = [l for g in TAX["groups"].values() for l in g]
N = len(LEAVES)
ALLOWED_ORIGINS = {"https://www.bilibili.com", "https://www.youtube.com"}

if os.path.exists(TOKEN_PATH):
    TOKEN = open(TOKEN_PATH).read().strip()
else:
    TOKEN = secrets.token_urlsafe(24)
    open(TOKEN_PATH, "w").write(TOKEN)

# ---------- 分类器：优先语义嵌入，缺依赖时回落字符 n-gram ----------
class Classifier:
    def __init__(self):
        self.mode = None
        model_dir = os.path.join(HERE, "models")
        try:
            os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
            for k in ["http_proxy", "https_proxy", "all_proxy", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"]:
                os.environ.pop(k, None)
            from sentence_transformers import SentenceTransformer
            import joblib
            self.enc = SentenceTransformer("BAAI/bge-small-zh-v1.5",
                                           device="cuda" if self._has_cuda() else "cpu")
            self.clf = joblib.load(os.path.join(model_dir, "topic_clf_emb.joblib"))
            self.mode = "embedding"
        except Exception as e:
            print("[warn] 嵌入分类不可用，回落 n-gram:", str(e)[:100])
            from sklearn.feature_extraction.text import HashingVectorizer
            d = np.load(os.path.join(model_dir, "topic_model_daemon.npz"))
            self.W, self.B, dims = d["w"], d["b"], int(d["dims"])
            self.vec = HashingVectorizer(analyzer="char", ngram_range=(1, 3),
                                         n_features=dims, alternate_sign=False, norm="l2")
            self.mode = "ngram"
        print(f"[classifier] mode={self.mode}")

    @staticmethod
    def _has_cuda():
        try:
            import torch
            return torch.cuda.is_available()
        except Exception:
            return False

    def proba(self, texts):
        if self.mode == "embedding":
            X = self.enc.encode(texts, batch_size=64, normalize_embeddings=True, show_progress_bar=False)
            return self.clf.predict_proba(X)
        z = (self.vec.transform(texts) @ self.W.T) + self.B
        z = np.asarray(z)
        e = np.exp(z - z.max(axis=1, keepdims=True))
        return e / e.sum(axis=1, keepdims=True)

# ---------- 画像状态（数学与 eval/profile_engine.py 一致） ----------
HL_SHORT, HL_LONG = 7 * 86400.0, 90 * 86400.0

class State:
    def __init__(self):
        self.lock = threading.Lock()
        self.short = np.zeros(N); self.long = np.zeros(N); self.expose = np.zeros(N)
        self.ts = None
        self.prefs = {}  # topic -> -2..2 申明偏好
        self.db = sqlite3.connect(DB_PATH, check_same_thread=False)
        self.db.execute("CREATE TABLE IF NOT EXISTS events(ts REAL, site TEXT, title TEXT, up TEXT, etype TEXT, dwell REAL, topic INT)")
        self.db.execute("CREATE TABLE IF NOT EXISTS kv(k TEXT PRIMARY KEY, v TEXT)")
        row = self.db.execute("SELECT v FROM kv WHERE k='profile'").fetchone()
        if row:
            d = json.loads(row[0])
            self.short = np.array(d["short"]); self.long = np.array(d["long"])
            self.expose = np.array(d["expose"]); self.ts = d["ts"]; self.prefs = d.get("prefs", {})

    def _decay(self, now):
        if self.ts is not None:
            dt = max(0.0, now - self.ts)
            self.short *= 0.5 ** (dt / HL_SHORT)
            self.long *= 0.5 ** (dt / HL_LONG)
            self.expose *= 0.5 ** (dt / HL_LONG)
        self.ts = now

    def update(self, proba, etype, dwell, now, site, title, up):
        with self.lock:
            self._decay(now)
            w = 1.0 if etype == "expose" else (5.0 if etype == "click" else 5.0 + min(dwell / 60.0, 10.0))
            if etype == "expose":
                self.expose += proba
            else:
                self.short += w * proba
                self.long += w * proba
            self.db.execute("INSERT INTO events VALUES(?,?,?,?,?,?,?)",
                            (now, site, title[:120], up[:40], etype, dwell, int(proba.argmax())))
            self.db.execute("REPLACE INTO kv VALUES('profile',?)", (json.dumps(
                {"short": self.short.tolist(), "long": self.long.tolist(),
                 "expose": self.expose.tolist(), "ts": self.ts, "prefs": self.prefs}),))
            self.db.commit()

    def dists(self):
        def nz(v):
            s = v.sum()
            return (v / s if s > 0 else v).tolist()
        return {"short": nz(self.short), "long": nz(self.long), "expose": nz(self.expose)}

CLF = Classifier()
ST = State()

# ---------- HTTP ----------
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

def dashboard_html():
    return open(os.path.join(HERE, "dashboard.html"), encoding="utf-8").read()

class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _cors(self):
        origin = self.headers.get("Origin", "")
        if origin in ALLOWED_ORIGINS:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Access-Control-Allow-Headers", "content-type, x-im-token")
            self.send_header("Access-Control-Allow-Private-Network", "true")

    def _json(self, obj, code=200, cors=False):
        data = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        if cors:
            self._cors()
        self.end_headers()
        self.wfile.write(data)

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS")
        self.end_headers()

    def do_GET(self):
        if self.path == "/":
            body = dashboard_html().encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/profile":
            # 只有本机同源（仪表盘）能读：不发 CORS 头，外站页面读不到响应
            d = ST.dists()
            top = np.argsort(d["long"])[::-1][:10]
            drivers = {}
            for t in top[:5]:
                rows = ST.db.execute(
                    "SELECT title, up FROM events WHERE topic=? AND etype!='expose' ORDER BY ts DESC LIMIT 3",
                    (int(t),)).fetchall()
                if rows:
                    drivers[LEAVES[t]] = [{"title": r[0], "up": r[1]} for r in rows]
            n_events = ST.db.execute("SELECT COUNT(*) FROM events").fetchone()[0]
            self._json({"topics": LEAVES, "groups": TAX["groups"], **d,
                        "prefs": ST.prefs, "drivers": drivers, "n_events": n_events,
                        "classifier": CLF.mode})
        elif self.path == "/export":
            row = ST.db.execute("SELECT v FROM kv WHERE k='profile'").fetchone()
            self._json({"taxonomy_version": TAX["version"], "profile": json.loads(row[0]) if row else None})
        else:
            self._json({"error": "not found"}, 404)

    def do_POST(self):
        if self.headers.get("X-IM-Token", "") != TOKEN:
            self._json({"error": "bad token"}, 403, cors=True)
            return
        body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        try:
            data = json.loads(body)
        except Exception:
            self._json({"error": "bad json"}, 400, cors=True)
            return
        if self.path == "/events":
            evs = data if isinstance(data, list) else [data]
            evs = evs[:500]
            texts = [str(e.get("t", ""))[:120] + " " + str(e.get("u", ""))[:40] for e in evs]
            probas = CLF.proba(texts)
            now = time.time()
            for e, p in zip(evs, probas):
                ts = float(e.get("ts", now))
                ST.update(p, e.get("type", "expose"), float(e.get("dwell", 0)), ts,
                          e.get("site", "?"), str(e.get("t", "")), str(e.get("u", "")))
            self._json({"ok": True, "n": len(evs)}, cors=True)
        elif self.path == "/prefs":
            for k, v in data.items():
                if k in LEAVES:
                    ST.prefs[k] = max(-2, min(2, float(v)))
            with ST.lock:
                ST.db.execute("REPLACE INTO kv VALUES('profile',?)", (json.dumps(
                    {"short": ST.short.tolist(), "long": ST.long.tolist(),
                     "expose": ST.expose.tolist(), "ts": ST.ts, "prefs": ST.prefs}),))
                ST.db.commit()
            self._json({"ok": True}, cors=True)
        else:
            self._json({"error": "not found"}, 404, cors=True)

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=21456)
    args = ap.parse_args()
    print(f"[interest-daemon] http://127.0.0.1:{args.port}/  分类器={CLF.mode}")
    print(f"[interest-daemon] 令牌（插件里配置）: {TOKEN}")
    ThreadingHTTPServer(("127.0.0.1", args.port), H).serve_forever()
