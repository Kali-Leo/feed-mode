"""E20 采集：YouTube 标题语料（首页个性化 + 热门 + 跨领域搜索）。"""
import json, time, urllib.parse, urllib.request

BASE = "http://127.0.0.1:8765"
S = "/tmp/claude-1000/-home-leo----bilibili/7ae81ed2-efb1-446d-95dc-6901201fe793/scratchpad"

def js(code, timeout=40):
    req = urllib.request.Request(BASE + "/js", data=code.encode(), method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        out = json.loads(r.read())
        if "error" in out:
            raise RuntimeError(out["error"][:150])
        return out["result"]

def goto(url):
    with urllib.request.urlopen(BASE + "/goto?url=" + urllib.parse.quote(url, safe=""), timeout=90) as r:
        r.read()

SCRAPE = '''
const seen = new Set();
const out = [];
const sels = "a#video-title, a#video-title-link, yt-lockup-view-model .yt-lockup-metadata-view-model__title, yt-lockup-view-model h3 a";
for (const a of document.querySelectorAll(sels)) {
  if (a.closest("ytd-macro-markers-list-item-renderer")) continue;
  const href = a.getAttribute("href") || (a.closest("yt-lockup-view-model")?.querySelector("a[href*='watch?v=']")||{getAttribute:()=>""}).getAttribute("href") || "";
  const m = href.match(/[?&]v=([\\w-]{11})/);
  if (!m || seen.has(m[1])) continue;
  const t = (a.getAttribute("title") || a.getAttribute("aria-label") || a.textContent || "").trim().replace(/\\s+/g, " ").slice(0, 150);
  if (!t || t.length < 4) continue;
  const root = a.closest("ytd-rich-item-renderer, ytd-video-renderer, ytd-compact-video-renderer, yt-lockup-view-model");
  const ch = root ? (root.querySelector("ytd-channel-name a, ytd-channel-name #text, .yt-content-metadata-view-model__metadata-row a")||{}).textContent : "";
  seen.add(m[1]);
  out.push({b: m[1], t, u: (ch||"").trim().slice(0,50)});
}
return JSON.stringify(out);
'''

COUNT = 'return String(document.querySelectorAll("a#video-title, a#video-title-link, yt-lockup-view-model h3 a").length)'

def wait_loaded(min_n=12, timeout=25):
    last = -1
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            n_now = int(js(COUNT))
        except Exception:
            n_now = 0
        if n_now >= min_n and n_now == last:
            return n_now
        last = n_now
        time.sleep(2.5)
    return last

seen = set()
try:
    for l in open(S + "/yt_corpus.jsonl"):
        seen.add(json.loads(l)["b"])
except FileNotFoundError:
    pass
f = open(S + "/yt_corpus.jsonl", "a")
n = len(seen)
print(f"resume with {n}", flush=True)

def harvest(src):
    global n
    try:
        items = json.loads(js(SCRAPE, 60))
    except Exception as e:
        print("scrape-err", str(e)[:80], flush=True)
        return
    fresh = 0
    for it in items:
        if it["b"] in seen or not it["t"]:
            continue
        seen.add(it["b"])
        f.write(json.dumps({**it, "s": src}, ensure_ascii=False) + "\n")
        fresh += 1
        n += 1
    f.flush()
    print(f"{src}: +{fresh} total={n}", flush=True)

# 1) 个性化首页：2 轮刷新 × 3 次滚动
for r in range(2):
    goto("https://www.youtube.com/")
    wait_loaded(12, 25)
    for k in range(3):
        js('window.scrollTo(0, document.documentElement.scrollHeight); return "s"')
        time.sleep(3.5)
    harvest("home")

# 2) 热门
for url in ["https://www.youtube.com/feed/trending",
            "https://www.youtube.com/feed/trending?bp=4gINGgt5dG1hX2NoYXJ0cw%3D%3D",
            "https://www.youtube.com/feed/trending?bp=4gIcGhpnYW1pbmdfY29ycHVzX21vc3RfcG9wdWxhcg%3D%3D"]:
    goto(url)
    wait_loaded(10, 25)
    js('window.scrollTo(0, document.documentElement.scrollHeight); return "s"')
    time.sleep(4)
    harvest("trending")

# 3) 跨领域搜索
QUERIES = ["programming tutorial", "machine learning explained", "physics lecture", "math proof",
           "history documentary", "economics explained", "investing basics", "startup business",
           "cooking recipe", "street food", "travel vlog", "hiking outdoors", "home diy",
           "fashion haul", "car review", "cute pets", "nature wildlife", "workout at home",
           "football highlights", "nba highlights", "gaming walkthrough", "esports finals",
           "minecraft build", "anime review", "music cover", "original song", "dance tutorial",
           "movie trailer reaction", "standup comedy", "asmr sleep", "news analysis",
           "true crime", "productivity tips", "language learning", "chemistry experiment",
           "科技评测", "编程教学", "纪录片 中文", "理财 投资", "搞笑 集锦", "美食 探店",
           "英语学习", "健身教学", "游戏实况", "音乐 翻唱"]
for q in QUERIES:
    goto("https://www.youtube.com/results?search_query=" + urllib.parse.quote(q))
    wait_loaded(10, 25)
    js('window.scrollTo(0, document.documentElement.scrollHeight); return "s"')
    time.sleep(4)
    harvest("search:" + q.split(" ")[0])

f.close()
print(f"YT-COLLECT-DONE total={n}", flush=True)
