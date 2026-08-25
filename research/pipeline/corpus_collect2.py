import json, time, urllib.request, urllib.parse

BASE = "http://127.0.0.1:8765"
SCRATCH = "/tmp/claude-1000/-home-leo----bilibili/7ae81ed2-efb1-446d-95dc-6901201fe793/scratchpad"
OUT = SCRATCH + "/corpus.jsonl"

def js(code, timeout=40):
    req = urllib.request.Request(BASE + "/js", data=code.encode(), method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        out = json.loads(r.read())
        if "error" in out:
            raise RuntimeError(out["error"][:200])
        return out["result"]

def get(path, timeout=60):
    with urllib.request.urlopen(BASE + path, timeout=timeout) as r:
        return r.read().decode()

for _ in range(40):
    try:
        if '"url"' in get("/info", 5):
            break
    except Exception:
        pass
    time.sleep(2)
if "bilibili.com" not in get("/info"):
    get("/goto?url=" + urllib.parse.quote("https://www.bilibili.com/", safe=""))
    time.sleep(6)

tasks = []
ZONES = [1, 3, 4, 5, 36, 119, 129, 155, 160, 168, 177, 181, 188, 211, 217, 223, 234]
for rid in [0] + ZONES:
    tasks.append({"u": f"https://api.bilibili.com/x/web-interface/ranking/v2?rid={rid}&type=all", "s": f"rank_{rid}", "f": "list", "fam": "rank"})
for rid in ZONES:
    for pn in range(1, 13):
        tasks.append({"u": f"https://api.bilibili.com/x/web-interface/newlist?rid={rid}&type=0&pn={pn}&ps=50", "s": f"new_{rid}", "f": "archives", "fam": "newlist"})
for pn in range(1, 41):
    tasks.append({"u": f"https://api.bilibili.com/x/web-interface/popular?pn={pn}&ps=20", "s": "popular", "f": "list", "fam": "popular"})
for i in range(300, 320):
    tasks.append({"u": f"https://api.bilibili.com/x/web-interface/wbi/index/top/feed/rcmd?ps=30&fresh_type=4&fresh_idx={i}&fresh_idx_1h={i}&brush={i}", "s": "rcmd", "f": "item", "fam": "rcmd"})
print(f"tasks: {len(tasks)}", flush=True)

COLLECT = r'''
window.__c2 = {state:"running", items:[], log:[], done:0, total:0, risk:0, deadFam:[]};
(async () => {
  const C = window.__c2;
  const tasks = TASKS_JSON;
  C.total = tasks.length;
  const dead = new Set();
  const sleep = ms => new Promise(r=>setTimeout(r,ms));
  const RISK = new Set([-352, -412, -799]);
  for (const t of tasks) {
    if (dead.has(t.fam)) { C.done++; continue; }
    try {
      const r = await fetch(t.u, {credentials:"include"});
      const d = await r.json();
      if (RISK.has(d.code)) {
        C.risk++; dead.add(t.fam); C.deadFam = [...dead];
        C.log.push("RISK " + t.fam + " code=" + d.code + " -> 弃源+暂停180s");
        if (C.risk >= 2) { C.state = "aborted-risk"; return; }
        await sleep(180000);
        C.done++; continue;
      }
      let arr = [];
      if (d.code === 0 && d.data) {
        if (t.f === "archives") arr = d.data.archives || [];
        else if (t.f === "item") arr = (d.data.item || []).filter(x => x.goto === "av");
        else arr = d.data.list || [];
      }
      for (const x of arr) {
        if (!x || !x.bvid) continue;
        const up = x.owner ? x.owner.name : (x.author ? (x.author.name || x.author) : "");
        C.items.push({b: x.bvid, t: x.title || "", u: String(up || ""), s: t.s});
      }
    } catch(e) { C.log.push("err " + t.s + " " + String(e).slice(0,50)); }
    C.done++;
    await sleep(2500 + Math.random() * 1500);
  }
  C.state = "done";
})();
return "started";
'''
COLLECT = COLLECT.replace("TASKS_JSON", json.dumps(tasks))
print(js(COLLECT, 60), flush=True)

seen = set()
try:
    for l in open(OUT):
        seen.add(json.loads(l)["b"])
except FileNotFoundError:
    pass
print(f"resume with {len(seen)} existing", flush=True)
f = open(OUT, "a")
n_new = 0
t0 = time.time()
while True:
    time.sleep(15)
    try:
        d = json.loads(js('const c=window.__c2; const it=c.items.splice(0); const lg=c.log.splice(0); return JSON.stringify({s:c.state, d:c.done, t:c.total, risk:c.risk, items:it, log:lg})', 60))
    except Exception as e:
        print("poll-err", e, flush=True)
        continue
    for it in d["items"]:
        if it["b"] in seen or not it["t"]:
            continue
        seen.add(it["b"])
        f.write(json.dumps(it, ensure_ascii=False) + "\n")
        n_new += 1
    f.flush()
    for l in d["log"]:
        print(l, flush=True)
    print(f"progress {d['d']}/{d['t']} total-unique={len(seen)} new={n_new} risk={d['risk']} elapsed={int(time.time()-t0)}s", flush=True)
    if d["s"] != "running":
        print("END-STATE:", d["s"], flush=True)
        break
f.close()
from collections import Counter
cnt = Counter(json.loads(l)["s"].split("_")[0] for l in open(OUT))
print("BY-FAMILY:", dict(cnt.most_common()), flush=True)
print("DONE", flush=True)
