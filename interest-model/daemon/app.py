"""个人兴趣模型 · 本地服务（完整轨）

运行: python3 app.py [--port 21456]
安全: 只绑 127.0.0.1；写接口需令牌（首次运行自动生成，存 ~/.interest-model/token）；
     跨域仅放行 bilibili/youtube 来源；读接口不发 CORS 头（外站页面拿不到响应）。
事件: 插件 POST /events，头带 X-IM-Token。事件字段:
     {t:标题, u:作者, type:"expose"|"click"|"watch", dwell:秒, dur:视频总长秒, id:视频id, pic:封面url, site, ts}
仪表盘: 浏览器打开 http://127.0.0.1:<port>/
"""
import argparse, json, os, re, secrets, sqlite3, sys, time, threading
from urllib.parse import urlparse, parse_qs
import numpy as np

BASE_DIR = os.path.expanduser("~/.interest-model")
os.makedirs(BASE_DIR, exist_ok=True)
# 无控制台打包（--windowed）下 stdout/stderr 为 None，统一落日志文件
if sys.stdout is None or sys.stderr is None:
    _log = open(os.path.join(BASE_DIR, "daemon.log"), "a", buffering=1, encoding="utf-8")
    sys.stdout = sys.stdout or _log
    sys.stderr = sys.stderr or _log
TOKEN_PATH = os.path.join(BASE_DIR, "token")
DB_PATH = os.path.join(BASE_DIR, "events.db")
# 打包发行版（PyInstaller）里资源在解包目录，保持 daemon/.. 的相对布局不变
HERE = os.path.join(sys._MEIPASS, "daemon") if getattr(sys, "frozen", False) \
    else os.path.dirname(os.path.abspath(__file__))
TAX = json.load(open(os.path.join(HERE, "..", "taxonomy.json")))
EMO = json.load(open(os.path.join(HERE, "..", "emotions.json")))
LEAVES = [l for g in TAX["groups"].values() for l in g]
E_NAMES = [e["name"] for e in EMO["emotions"]]
E_VAL = np.array([e["valence"] for e in EMO["emotions"]])
N = len(LEAVES)
PRO_GROUPS = {"科技数码", "知识学习", "财经商业", "纪实深度"}
PRO_TOPICS = {LEAVES.index(l) for g in PRO_GROUPS for l in TAX["groups"][g]}
ALLOWED_ORIGINS = {"https://www.bilibili.com", "https://www.youtube.com"}

VERSION = "2.1.0"
# v2：/pro_content 条目的 dwell 改为窗口内累计值（原为单次事件值），公告见 ../research/LOG.md E25
API_VERSION = 2
UPDATE = {"latest": None}   # 后台对比 Releases 最新 tag，仪表盘据此提示


def _check_update():
    import urllib.request
    try:
        with urllib.request.urlopen(
                "https://api.github.com/repos/Kali-Leo/feed-mode/releases/latest", timeout=10) as r:
            tag = json.load(r).get("tag_name", "").lstrip("v")

        def key(v):
            return [int(x) for x in re.findall(r"\d+", v)][:3]
        if tag and key(tag) > key(VERSION):
            UPDATE["latest"] = tag
    except Exception:
        pass

if os.path.exists(TOKEN_PATH):
    TOKEN = open(TOKEN_PATH).read().strip()
else:
    TOKEN = secrets.token_urlsafe(24)
    open(TOKEN_PATH, "w").write(TOKEN)

try:
    WORD_VAL = json.load(open(os.path.join(HERE, "models", "word_valence.json")))
except Exception:
    WORD_VAL = {}

# ---- 一次性配对码：让本机程序把令牌交给浏览器脚本，用户不必手抄 ----
# 申请配对码需要令牌（只有能读本机令牌文件的程序做得到）；兑换需要浏览器自带的 Origin。
# 令牌本身仍是唯一凭证，安全模型不降级。
PAIR_TTL = 120.0
_pairs = {}          # nonce -> 过期时间
_pairs_lock = threading.Lock()

def pair_new():
    now = time.time()
    with _pairs_lock:
        for k in [k for k, exp in _pairs.items() if exp < now]:
            del _pairs[k]
        nonce = secrets.token_urlsafe(18)
        _pairs[nonce] = now + PAIR_TTL
    return nonce

def pair_exchange(nonce):
    """一次性：兑换成功即作废。返回令牌或 None。"""
    with _pairs_lock:
        exp = _pairs.pop(nonce, None)
    return TOKEN if exp and exp >= time.time() else None


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
        self.db.execute("CREATE INDEX IF NOT EXISTS idx_events_ts ON events(ts)")
        self.db.execute("CREATE INDEX IF NOT EXISTS idx_events_topic ON events(topic, etype, ts)")
        self.db.execute("CREATE INDEX IF NOT EXISTS idx_events_etype ON events(etype)")
        self.db.execute("CREATE TABLE IF NOT EXISTS kv(k TEXT PRIMARY KEY, v TEXT)")
        row = self.db.execute("SELECT v FROM kv WHERE k='profile'").fetchone()
        if row:
            d = json.loads(row[0])
            self.short = np.array(d["short"]); self.long = np.array(d["long"])
            self.expose = np.array(d["expose"]); self.ts = d["ts"]; self.prefs = d.get("prefs", {})

    def _decay(self, now):
        # 衰减只由服务端时钟推进：浏览器时钟快一年曾能一次抹平整个画像且不可恢复。
        # 事件自带的 ts 只用于记录与"迟到折扣"（见 update），不再推动 self.ts。
        if self.ts is not None:
            dt = max(0.0, now - self.ts)
            self.short *= 0.5 ** (dt / HL_SHORT)
            self.long *= 0.5 ** (dt / HL_LONG)
            self.expose *= 0.5 ** (dt / HL_LONG)
        self.ts = max(self.ts or 0, now)

    @staticmethod
    def event_weight(etype, dwell):
        return 1.0 if etype == "expose" else (5.0 if etype == "click" else 5.0 + min(dwell / 60.0, 10.0))

    def _apply(self, tp, etype, w, age):
        """把一个发生在 age 秒前的事件按"先衰减后入账"计入向量——
        退避重投的旧事件从此按其真实年龄折扣，而不是按全权重入账。"""
        if etype == "expose":
            self.expose += w * tp * 0.5 ** (age / HL_LONG)
        else:
            self.short += w * tp * 0.5 ** (age / HL_SHORT)
            self.long += w * tp * 0.5 ** (age / HL_LONG)

    def update(self, tp, ep, ev):
        now = time.time()
        ev_ts = float(ev.get("ts", now))
        # 客户端时钟只在合理窗口内被信任：未来或早于 30 天的时间戳按"现在"处理
        if not (now - 30 * 86400 <= ev_ts <= now + 60):
            ev_ts = now
        etype = ev.get("type", "expose")
        dwell = float(ev.get("dwell", 0))
        vid = str(ev.get("id", ""))[:30]
        with self.lock:
            # 同一 (vid, etype, ts) 的重复投递（脚本退避重试）只入账一次
            if self.db.execute("SELECT 1 FROM events WHERE ts=? AND vid=? AND etype=? LIMIT 1",
                               (ev_ts, vid, etype)).fetchone():
                return
            self._decay(now)
            self._apply(tp, etype, self.event_weight(etype, dwell), now - ev_ts)
            emo = int(ep.argmax()) if ep is not None else -1
            val = float(ep @ E_VAL) if ep is not None else None
            self.db.execute("INSERT INTO events VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                            (ev_ts, ev.get("site", "?"), vid,
                             str(ev.get("t", ""))[:120], str(ev.get("u", ""))[:40], etype,
                             dwell, float(ev.get("dur", 0)), int(tp.argmax()), emo, val,
                             str(ev.get("pic", ""))[:200]))

    def rebuild_profile(self):
        """从 events 表重算三个向量——时钟事故的恢复出口。事件只存了 top-1 主题
        （完整概率分布未落库），重放时按 one-hot 近似，画像会略比在线累积的"硬"。"""
        with self.lock:
            now = time.time()
            self.short = np.zeros(N); self.long = np.zeros(N); self.expose = np.zeros(N)
            self.ts = now
            rows = self.db.execute(
                "SELECT ts, etype, dwell, topic FROM events WHERE topic IS NOT NULL").fetchall()
            for ev_ts, etype, dwell, topic in rows:
                if not 0 <= topic < N:
                    continue
                tp = np.zeros(N); tp[topic] = 1.0
                self._apply(tp, etype, self.event_weight(etype, dwell or 0.0),
                            max(0.0, now - ev_ts))
            return len(rows)

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


CLF = None
ST = None


def _load_models():
    global CLF, ST
    print("[interest-daemon] 正在加载分类模型；首次运行需下载语义模型（约600MB），请稍候…")
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
    return {"emotions": E_NAMES, "emotions_en": [e.get("name_en", e["name"]) for e in EMO["emotions"]],
            "valences": E_VAL.tolist(), **out}


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
    """浏览过的专业内容：看完(≥80%或观看≥10分钟) / 未看完。

    同一个视频按窗口内**累计**观看时长判定（脚本每次切后台就结算一段，一个视频常拆成
    多条 watch 事件）：只看最新一条会把"看完后又点开 20 秒"记成没看过、把分段看完的
    记成未看完（2026-08-30 审查发现）。标题等元数据取最新一条。"""
    since = time.time() - days * 86400
    rows = ST.db.execute(
        "SELECT ts, vid, title, up, dwell, dur, topic, site, pic FROM events "
        "WHERE ts>=? AND etype!='expose' ORDER BY ts DESC LIMIT 2000", (since,)).fetchall()
    fin, unfin = [], []
    agg = {}          # key -> item（元数据来自最新事件，dwell 累计、dur 取最大）
    order = []        # 保持"最近优先"的输出顺序
    group_of = {}
    for gname, ls in TAX["groups"].items():
        for l in ls:
            group_of[LEAVES.index(l)] = gname
    for ts, vid, title, up, dwell, dur, topic, site, pic in rows:
        if topic not in PRO_TOPICS:
            continue
        key = vid or title
        a = agg.get(key)
        if a is None:
            agg[key] = {"ts": ts, "id": vid, "title": title, "up": up, "topic": LEAVES[topic],
                        "topic_en": TAX.get("leaves_en", {}).get(LEAVES[topic], LEAVES[topic]),
                        "group": group_of.get(topic, ""),
                        "group_en": TAX.get("groups_en", {}).get(group_of.get(topic, ""), group_of.get(topic, "")),
                        "pic": pic or "",
                        "dwell": dwell or 0.0, "dur": dur or 0.0,
                        "site": site}
            order.append(key)
        else:
            a["dwell"] += dwell or 0.0
            a["dur"] = max(a["dur"], dur or 0.0)
    for key in order:
        item = agg[key]
        dwell, dur = item["dwell"], item["dur"]
        item["dwell"] = round(dwell); item["dur"] = round(dur)
        if dur > 0:
            # 有时长信息：累计完成度 ≥80% 算看完；<80% 且确实看过（≥30s）算未看完
            if dwell / dur >= 0.8:
                fin.append(item)
            elif dwell >= 30:
                unfin.append(item)
        elif dwell >= 600:
            fin.append(item)  # 无时长信息但累计看了10分钟以上，视为认真看过
        # 无时长且短观看：无法判断是否看完，不列入（避免"看了2/0分钟"式的误报）
    return {"days": days, "finished": fin[:100], "unfinished": unfin[:100]}


def new_interests():
    """新的兴趣：近期占比显著且相对长期明显上升的主题，附最近点开的内容。"""
    # 数据太少时不判：总共只点开过二十几条时，一次点击就能把偶然宣布成"新的兴趣"。
    n_engaged = ST.db.execute("SELECT COUNT(*) FROM events WHERE etype!='expose'").fetchone()[0]
    if n_engaged < 50:
        return {"interests": []}
    d = ST.dists()
    out = []
    for i in range(N):
        s, l = d["short"][i], d["long"][i]
        if s >= 0.03 and s >= 2.0 * max(l, 0.005):
            # 同一视频的 click+watch 会占两个名额，按 vid 去重、留最新一条
            rows = ST.db.execute(
                "SELECT title, up, vid, site, MAX(ts) FROM events WHERE topic=? AND etype!='expose' "
                "AND ts>=? GROUP BY COALESCE(NULLIF(vid,''), title) ORDER BY MAX(ts) DESC LIMIT 3",
                (i, time.time() - 14 * 86400)).fetchall()
            out.append({"topic": LEAVES[i],
                        "topic_en": TAX.get("leaves_en", {}).get(LEAVES[i], LEAVES[i]),
                        "share": round(s, 3), "before": round(l, 3),
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
            # 主动行为（点开/观看）的条数——判断"证据够不够"该用它而不是含曝光的总数
            n_engaged = ST.db.execute("SELECT COUNT(*) FROM events WHERE etype!='expose'").fetchone()[0]
            # 曝光纠偏：主动选择占比 / 被投喂占比。>1 = 兴趣高于投喂量，<1 = 主要是被喂的。
            # 平台推荐什么就"兴趣"什么的退化闭环，靠这一路信号才能被消费方拆开。
            lift = [round(s / max(e, 0.005), 2) for s, e in zip(d["short"], d["expose"])]
            self._json({"api_version": API_VERSION, "version": VERSION, "update": UPDATE["latest"],
                        "topics": LEAVES, "topics_en": [TAX.get("leaves_en", {}).get(l, l) for l in LEAVES],
                        "groups": TAX["groups"], "groups_en": TAX.get("groups_en", {}), **d,
                        "lift": lift,
                        "prefs": ST.prefs, "drivers": drivers, "n_events": n_events,
                        "n_engaged": n_engaged,
                        "classifier": CLF.mode, "emotion_on": CLF.emo_clf is not None})
        elif u.path == "/emotion_series":
            self._json(emotion_series(q_days(query, 60), query.get("cat", ["all"])[0]))
        elif u.path == "/new_interests":
            self._json(new_interests())
        elif u.path == "/wordcloud":
            self._json(wordcloud(q_days(query, 30), query.get("source", ["engage"])[0]))
        elif u.path == "/pro_content":
            self._json(pro_content(q_days(query, 30)))
        elif u.path == "/pair":
            # 配对发起端：本机浏览器点开即现场生成一次性配对码并跳到目标站点，
            # 脚本监听 #im-pair= 完成兑换。daemon 只绑 127.0.0.1，且码单次有效 120s。
            site = query.get("site", [""])[0]
            targets = {"bilibili": "https://www.bilibili.com/?p=1#im-pair=",
                       "youtube": "https://www.youtube.com/#im-pair="}
            if site in targets:
                self.send_response(302)
                self.send_header("Location", targets[site] + pair_new())
                self.end_headers()
            else:
                body = ('<meta charset="utf-8"><title>连接插件 Connect</title>'
                        '<body style="font:16px/2 system-ui;padding:40px">'
                        '<a href="/pair?site=bilibili">连接 B站 脚本</a><br>'
                        '<a href="/pair?site=youtube">Connect YouTube script</a>').encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(body)
        elif u.path == "/export":
            row = ST.db.execute("SELECT v FROM kv WHERE k='profile'").fetchone()
            self._json({"taxonomy_version": TAX["version"], "profile": json.loads(row[0]) if row else None})
        else:
            self._json({"error": "not found"}, 404)

    def do_POST(self):
        # 配对兑换不需要令牌（本来就是为了取令牌），但必须来自白名单 Origin 且持有有效配对码
        if self.path == "/pair/exchange":
            body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
            # 网页发起的跨源 POST 必带 Origin，白名单只对它们有意义；脚本管理器后台
            # （GM_xmlhttpRequest，为绕开浏览器的本地网络权限门而走的通道）可能不带
            # Origin——没有 Origin 即不是网页发的，放行；带了但不在白名单，仍然拒绝。
            # 配对码单次有效 120 秒，始终是真正的门槛。
            origin = self.headers.get("Origin")
            if origin is not None and origin not in ALLOWED_ORIGINS:
                self._json({"error": "origin not allowed"}, 403, cors=True)
                return
            try:
                nonce = json.loads(body).get("nonce", "")
            except Exception:
                nonce = ""
            tok = pair_exchange(str(nonce))
            if tok:
                self._json({"token": tok}, cors=True)
            else:
                self._json({"error": "invalid or expired pairing code"}, 403, cors=True)
            return
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
        elif self.path == "/pair/new":
            # 本机程序调用：换一个一次性配对码，附到浏览器 URL 的 fragment 里
            self._json({"nonce": pair_new(), "expires_in": int(PAIR_TTL)}, cors=True)
        elif self.path == "/rebuild_profile":
            # 时钟事故的恢复出口：从 events 表整体重算画像（见 State.rebuild_profile）
            n = ST.rebuild_profile()
            ST.flush()
            self._json({"ok": True, "replayed": n}, cors=True)
        elif self.path == "/prefs":
            for k, v in data.items():
                if k in LEAVES:
                    ST.prefs[k] = max(-2, min(2, float(v)))
            ST.flush()
            self._json({"ok": True}, cors=True)
        else:
            self._json({"error": "not found"}, 404, cors=True)


# ---- 开机自启：注册后每次开机静默运行；--autostart off 移除 ----
AUTOSTART_OFF = os.path.join(BASE_DIR, "autostart.off")


def _launch_cmd(port):
    cmd = [sys.executable] if getattr(sys, "frozen", False) \
        else [sys.executable, os.path.abspath(__file__)]
    return cmd + ["--no-browser", "--port", str(port)]


def autostart_register(port):
    cmd = _launch_cmd(port)
    if sys.platform == "win32":
        import winreg, subprocess
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                             r"Software\Microsoft\Windows\CurrentVersion\Run", 0, winreg.KEY_SET_VALUE)
        winreg.SetValueEx(key, "interest-model", 0, winreg.REG_SZ, subprocess.list2cmdline(cmd))
        winreg.CloseKey(key)
    elif sys.platform == "darwin":
        import plistlib
        d = os.path.expanduser("~/Library/LaunchAgents")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "com.interest-model.daemon.plist"), "wb") as f:
            plistlib.dump({"Label": "com.interest-model.daemon",
                           "ProgramArguments": cmd, "RunAtLoad": True}, f)
    else:
        import shlex
        d = os.path.expanduser("~/.config/autostart")
        os.makedirs(d, exist_ok=True)
        open(os.path.join(d, "interest-model.desktop"), "w").write(
            "[Desktop Entry]\nType=Application\nName=interest-model\n"
            f"Exec={shlex.join(cmd)}\nX-GNOME-Autostart-enabled=true\n")


def autostart_remove():
    try:
        if sys.platform == "win32":
            import winreg
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                 r"Software\Microsoft\Windows\CurrentVersion\Run", 0, winreg.KEY_SET_VALUE)
            winreg.DeleteValue(key, "interest-model")
            winreg.CloseKey(key)
        elif sys.platform == "darwin":
            os.remove(os.path.expanduser("~/Library/LaunchAgents/com.interest-model.daemon.plist"))
        else:
            os.remove(os.path.expanduser("~/.config/autostart/interest-model.desktop"))
    except OSError:
        pass


def _already_running(port):
    import urllib.request
    try:
        urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=1.5)
        return True
    except Exception:
        return False


def _open_loading_page(port):
    """先开一个本地过渡页；模型加载完、端口就绪后它自动跳进仪表盘。"""
    import webbrowser
    url = f"http://127.0.0.1:{port}/"
    page = os.path.join(BASE_DIR, "loading.html")
    open(page, "w", encoding="utf-8").write(
        '<!doctype html><meta charset="utf-8"><title>兴趣模型启动中</title>'
        '<body style="font-family:system-ui;display:flex;height:90vh;'
        'align-items:center;justify-content:center;text-align:center"><div>'
        '正在启动。首次运行会下载语义模型，约 600MB；就绪后自动进入仪表盘。'
        f'<br><br><a href="{url}">如未自动跳转，点这里</a></div>'
        f'<script>setInterval(()=>fetch("{url}",{{mode:"no-cors"}})'
        f'.then(()=>location="{url}").catch(()=>0),1500)</script>')
    webbrowser.open("file://" + page)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=21456)
    ap.add_argument("--no-browser", action="store_true", help="启动时不自动打开浏览器")
    ap.add_argument("--autostart", choices=["on", "off"], help="注册/移除开机自启，然后退出")
    args = ap.parse_args()

    if args.autostart:
        if args.autostart == "off":
            open(AUTOSTART_OFF, "w").close()
            autostart_remove()
            print("[interest-daemon] 已移除开机自启")
        else:
            try:
                os.remove(AUTOSTART_OFF)
            except OSError:
                pass
            autostart_register(args.port)
            print("[interest-daemon] 已注册开机自启")
        sys.exit(0)

    if _already_running(args.port):
        print(f"[interest-daemon] 已在运行，打开仪表盘 http://127.0.0.1:{args.port}/")
        if not args.no_browser:
            import webbrowser
            webbrowser.open(f"http://127.0.0.1:{args.port}/")
        sys.exit(0)

    if not args.no_browser:
        _open_loading_page(args.port)

    if not os.path.exists(AUTOSTART_OFF):
        try:
            autostart_register(args.port)
            print("[interest-daemon] 已注册开机自启，移除: --autostart off")
        except Exception as e:
            print("[warn] 开机自启注册失败:", str(e)[:100])

    threading.Thread(target=_check_update, daemon=True).start()
    _load_models()
    print(f"[interest-daemon] 仪表盘: http://127.0.0.1:{args.port}/  分类器={CLF.mode}")
    print(f"[interest-daemon] 连接插件: 浏览器打开 http://127.0.0.1:{args.port}/pair")
    ThreadingHTTPServer(("127.0.0.1", args.port), H).serve_forever()
