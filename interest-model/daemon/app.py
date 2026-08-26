"""个人兴趣模型 · 本地服务（完整轨）

运行: python3 app.py [--port 21456]
安全: 只绑 127.0.0.1；写接口需令牌（首次运行自动生成，存 ~/.interest-model/token）；
     跨域仅放行 bilibili/youtube 来源；读接口不发 CORS 头（外站页面拿不到响应）。
事件: 插件 POST /events，头带 X-IM-Token。事件字段:
     {t:标题, u:作者, type:"expose"|"click"|"watch", dwell:秒, dur:视频总长秒, id:视频id, pic:封面url, site, ts}
仪表盘: 浏览器打开 http://127.0.0.1:<port>/
"""
import argparse, json, os, re, secrets, sqlite3, time, threading
from urllib.parse import urlparse, parse_qs
import numpy as np

BASE_DIR = os.path.expanduser("~/.interest-model")
os.makedirs(BASE_DIR, exist_ok=True)
TOKEN_PATH = os.path.join(BASE_DIR, "token")
DB_PATH = os.path.join(BASE_DIR, "events.db")
HERE = os.path.dirname(os.path.abspath(__file__))
TAX = json.load(open(os.path.join(HERE, "..", "taxonomy.json")))
EMO = json.load(open(os.path.join(HERE, "..", "emotions.json")))
LEAVES = [l for g in TAX["groups"].values() for l in g]
E_NAMES = [e["name"] for e in EMO["emotions"]]
E_VAL = np.array([e["valence"] for e in EMO["emotions"]])
N = len(LEAVES)
PRO_GROUPS = {"科技数码", "知识学习", "财经商业", "纪实深度"}
PRO_TOPICS = {LEAVES.index(l) for g in PRO_GROUPS for l in TAX["groups"][g]}
ALLOWED_ORIGINS = {"https://www.bilibili.com", "https://www.youtube.com"}

if os.path.exists(TOKEN_PATH):
    TOKEN = open(TOKEN_PATH).read().strip()
else:
    TOKEN = secrets.token_urlsafe(24)
    open(TOKEN_PATH, "w").write(TOKEN)

try:
    WORD_VAL = json.load(open(os.path.join(HERE, "models", "word_valence.json")))
except Exception:
    WORD_VAL = {}


class Classifier:
    """编码一次，主题/情绪两个头共享嵌入；缺依赖时回落 n-gram（无情绪头）。"""

    def __init__(self):
        model_dir = os.path.join(HERE, "models")
        self.emo_clf = None
        try:
            os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
            for k in ["http_proxy", "https_proxy", "all_proxy", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"]:
                os.environ.pop(k, None)
            from sentence_transformers import SentenceTransformer
            import joblib
            self.enc = SentenceTransformer("BAAI/bge-small-zh-v1.5",
                                           device="cuda" if self._has_cuda() else "cpu")
            self.clf = joblib.load(os.path.join(model_dir, "topic_clf_emb.joblib"))
            try:
                self.emo_clf = joblib.load(os.path.join(model_dir, "emotion_clf_emb.joblib"))
            except Exception:
                pass
            self.mode = "embedding"
            try:
                yt_t = os.path.join(model_dir, "yt_topic_clf.joblib")
                yt_e = os.path.join(model_dir, "yt_emotion_clf.joblib")
                if os.path.exists(yt_t):
                    self.yt_enc = SentenceTransformer("sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
                                                      device="cuda" if self._has_cuda() else "cpu")
                    self.yt_clf = joblib.load(yt_t)
                    self.yt_emo = joblib.load(yt_e) if os.path.exists(yt_e) else None
                    self.yt = True
                    print("[classifier] youtube 多语言双头已加载")
                else:
                    self.yt = False
            except Exception as e2:
                print("[warn] youtube 模型加载失败:", str(e2)[:100])
                self.yt = False
        except Exception as e:
            print("[warn] 嵌入分类不可用，回落 n-gram（无情绪功能）:", str(e)[:100])
            from sklearn.feature_extraction.text import HashingVectorizer
            d = np.load(os.path.join(model_dir, "topic_model_daemon.npz"))
            self.W, self.B, dims = d["w"], d["b"], int(d["dims"])
            self.vec = HashingVectorizer(analyzer="char", ngram_range=(1, 3),
                                         n_features=dims, alternate_sign=False, norm="l2")
            self.mode = "ngram"
        print(f"[classifier] mode={self.mode} emotion={'on' if self.emo_clf is not None else 'off'}")

    @staticmethod
    def _has_cuda():
        try:
            import torch
            return torch.cuda.is_available()
        except Exception:
            return False

    def both(self, texts, sites=None):
        """返回 (主题proba, 情绪proba或None)；youtube 事件路由到多语言模型"""
        if self.mode == "embedding":
            n = len(texts)
            yt_idx = [i for i in range(n) if sites and getattr(self, "yt", False) and sites[i] == "youtube"]
            zh_idx = [i for i in range(n) if i not in set(yt_idx)]
            tp = np.zeros((n, N)); ep = np.zeros((n, len(E_NAMES)))
            if zh_idx:
                X = self.enc.encode([texts[i] for i in zh_idx], batch_size=64, normalize_embeddings=True, show_progress_bar=False)
                tp[zh_idx] = self.clf.predict_proba(X)
                if self.emo_clf is not None:
                    ep[zh_idx] = self.emo_clf.predict_proba(X)
            if yt_idx:
                Xy = self.yt_enc.encode([texts[i] for i in yt_idx], batch_size=64, normalize_embeddings=True, show_progress_bar=False)
                tp[yt_idx] = self.yt_clf.predict_proba(Xy)
                if self.yt_emo is not None:
                    ep[yt_idx] = self.yt_emo.predict_proba(Xy)
            return tp, (ep if self.emo_clf is not None else None)
        z = (self.vec.transform(texts) @ self.W.T) + self.B
        z = np.asarray(z)
        e = np.exp(z - z.max(axis=1, keepdims=True))
        return e / e.sum(axis=1, keepdims=True), None


HL_SHORT, HL_LONG = 7 * 86400.0, 90 * 86400.0


class State:
    def __init__(self):
        self.lock = threading.Lock()
        self.short = np.zeros(N); self.long = np.zeros(N); self.expose = np.zeros(N)
        self.ts = None
        self.prefs = {}
        self.db = sqlite3.connect(DB_PATH, check_same_thread=False)
        self.db.execute("""CREATE TABLE IF NOT EXISTS events(
            ts REAL, site TEXT, vid TEXT, title TEXT, up TEXT, etype TEXT,
            dwell REAL, dur REAL, topic INT, emo INT, valence REAL, pic TEXT)""")
        try:
            self.db.execute("ALTER TABLE events ADD COLUMN pic TEXT")
        except Exception:
            pass
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
        self.ts = max(self.ts or 0, now)

    def update(self, tp, ep, ev):
        now = float(ev.get("ts", time.time()))
        etype = ev.get("type", "expose")
        dwell = float(ev.get("dwell", 0))
        with self.lock:
            self._decay(now)
            w = 1.0 if etype == "expose" else (5.0 if etype == "click" else 5.0 + min(dwell / 60.0, 10.0))
            if etype == "expose":
                self.expose += tp
            else:
                self.short += w * tp
                self.long += w * tp
            emo = int(ep.argmax()) if ep is not None else -1
            val = float(ep @ E_VAL) if ep is not None else None
            self.db.execute("INSERT INTO events VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                            (now, ev.get("site", "?"), str(ev.get("id", ""))[:30],
                             str(ev.get("t", ""))[:120], str(ev.get("u", ""))[:40], etype,
                             dwell, float(ev.get("dur", 0)), int(tp.argmax()), emo, val,
                             str(ev.get("pic", ""))[:200]))

    def flush(self):
        with self.lock:
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

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def q_days(query, default=30):
    try:
        return max(1, min(3650, int(query.get("days", [default])[0])))
    except Exception:
        return default


PRO_SQL = "(" + ",".join(str(t) for t in sorted(PRO_TOPICS)) + ")"
CAT_SQL = {
    "all": "1=1",
    "pro": f"topic IN {PRO_SQL}",
    "ent": f"topic NOT IN {PRO_SQL}",
    "gent": f"topic NOT IN {PRO_SQL} AND valence >= 0.5",
}


def emotion_series(days, cat="all"):
    """按天聚合：投喂(曝光) vs 选择(点击/观看) 的平均效价与情绪构成，可按内容类别过滤。"""
    since = time.time() - days * 86400
    cat_cond = CAT_SQL.get(cat, "1=1")
    out = {}
    for label, cond in [("expose", "etype='expose'"), ("engage", "etype!='expose'")]:
        rows = ST.db.execute(
            f"SELECT CAST(ts/86400 AS INT)*86400 AS day, AVG(valence), COUNT(*), emo "
            f"FROM events WHERE ts>=? AND valence IS NOT NULL AND {cond} AND {cat_cond} GROUP BY day, emo",
            (since,)).fetchall()
        days_map = {}
        for day, avgv, n, emo in rows:
            d = days_map.setdefault(day, {"n": 0, "vsum": 0.0, "mix": [0] * len(E_NAMES)})
            d["n"] += n
            d["vsum"] += avgv * n
            if 0 <= emo < len(E_NAMES):
                d["mix"][emo] += n
        out[label] = [
            {"day": day, "valence": round(d["vsum"] / d["n"], 3), "n": d["n"],
             "mix": [round(x / d["n"], 3) for x in d["mix"]]}
            for day, d in sorted(days_map.items())]
    return {"emotions": E_NAMES, "valences": E_VAL.tolist(), **out}


_STOP = set("的 了 我 你 他 她 它 是 在 有 和 与 就 都 也 又 还 这 那 什么 怎么 为什么 一个 我们 你们 他们 自己 没有 不是 可以 这个 那个 到底 竟然 居然 直接 真的 到底 如何 这样 那样 但是 因为 所以 如果 已经 现在 开始 最后 第一 第二 up 主 UP".split())


def wordcloud(days, source):
    since = time.time() - days * 86400
    cond = "etype!='expose'" if source == "engage" else "etype='expose'"
    rows = ST.db.execute(f"SELECT title, valence FROM events WHERE ts>=? AND {cond}", (since,)).fetchall()
    import jieba
    cnt, vals = {}, {}
    for title, val in rows:
        for w in set(jieba.lcut(title)):
            if len(w) < 2 or w in _STOP or re.match(r"^[\d\W_a-zA-Z]+$", w):
                continue
            cnt[w] = cnt.get(w, 0) + 1
            if val is not None:
                vals.setdefault(w, []).append(val)
    top = sorted(cnt.items(), key=lambda x: -x[1])[:80]
    return {"days": days, "source": source, "words": [
        {"w": w, "n": n,
         "valence": round(WORD_VAL.get(w, float(np.mean(vals[w])) if w in vals else 0.0), 2)}
        for w, n in top]}


def pro_content(days):
    """浏览过的专业内容：看完(≥80%或观看≥10分钟) / 未看完。"""
    since = time.time() - days * 86400
    rows = ST.db.execute(
        "SELECT ts, vid, title, up, dwell, dur, topic, site, pic FROM events "
        "WHERE ts>=? AND etype!='expose' ORDER BY ts DESC LIMIT 2000", (since,)).fetchall()
    fin, unfin = [], []
    seen = set()
    group_of = {}
    for gname, ls in TAX["groups"].items():
        for l in ls:
            group_of[LEAVES.index(l)] = gname
    for ts, vid, title, up, dwell, dur, topic, site, pic in rows:
        if topic not in PRO_TOPICS or (vid, title) in seen:
            continue
        seen.add((vid, title))
        item = {"ts": ts, "id": vid, "title": title, "up": up, "topic": LEAVES[topic],
                "group": group_of.get(topic, ""), "pic": pic or "",
                "dwell": round(dwell), "dur": round(dur),
                "site": site}
        if dur > 0:
            # 有时长信息：完成度 ≥80% 算看完；<80% 且确实看过（≥30s）算未看完
            if dwell / dur >= 0.8:
                fin.append(item)
            elif dwell >= 30:
                unfin.append(item)
        elif dwell >= 600:
            fin.append(item)  # 无时长信息但看了10分钟以上，视为认真看过
        # 无时长且短观看：无法判断是否看完，不列入（避免"看了2/0分钟"式的误报）
    return {"days": days, "finished": fin[:100], "unfinished": unfin[:100]}


def new_interests():
    """新的兴趣：近期占比显著且相对长期明显上升的主题，附最近点开的内容。"""
    d = ST.dists()
    out = []
    for i in range(N):
        s, l = d["short"][i], d["long"][i]
        if s >= 0.03 and s >= 2.0 * max(l, 0.005):
            rows = ST.db.execute(
                "SELECT title, up, vid, site FROM events WHERE topic=? AND etype!='expose' "
                "AND ts>=? ORDER BY ts DESC LIMIT 3",
                (i, time.time() - 14 * 86400)).fetchall()
            out.append({"topic": LEAVES[i], "share": round(s, 3), "before": round(l, 3),
                        "items": [{"title": r[0], "up": r[1], "id": r[2], "site": r[3]} for r in rows]})
    out.sort(key=lambda x: -x["share"])
    return {"interests": out[:6]}


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
        u = urlparse(self.path)
        query = parse_qs(u.query)
        if u.path == "/":
            body = open(os.path.join(HERE, "dashboard.html"), encoding="utf-8").read().encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(body)
        elif u.path == "/profile":
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
                        "classifier": CLF.mode, "emotion_on": CLF.emo_clf is not None})
        elif u.path == "/emotion_series":
            self._json(emotion_series(q_days(query, 60), query.get("cat", ["all"])[0]))
        elif u.path == "/new_interests":
            self._json(new_interests())
        elif u.path == "/wordcloud":
            self._json(wordcloud(q_days(query, 30), query.get("source", ["engage"])[0]))
        elif u.path == "/pro_content":
            self._json(pro_content(q_days(query, 30)))
        elif u.path == "/export":
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
            evs = (data if isinstance(data, list) else [data])[:1000]
            texts = [str(e.get("t", ""))[:120] + " " + str(e.get("u", ""))[:40] for e in evs]
            tps, eps = CLF.both(texts, [e.get("site", "") for e in evs])
            for i, e in enumerate(evs):
                ST.update(tps[i], eps[i] if eps is not None else None, e)
            ST.flush()
            self._json({"ok": True, "n": len(evs)}, cors=True)
        elif self.path == "/prefs":
            for k, v in data.items():
                if k in LEAVES:
                    ST.prefs[k] = max(-2, min(2, float(v)))
            ST.flush()
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
