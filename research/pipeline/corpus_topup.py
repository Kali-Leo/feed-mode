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

tasks = []
ZONES = [1, 3, 4, 5, 36, 119, 129, 155, 160, 168, 177, 181, 188, 211, 217, 223, 234]
for typ in ["origin", "rookie"]:
    for rid in ZONES:
        tasks.append({"u": f"https://api.bilibili.com/x/web-interface/ranking/v2?rid={rid}&type={typ}", "s": f"rank{typ}_{rid}", "f": "list", "fam": "rank2"})
tasks.append({"u": "https://api.bilibili.com/x/web-interface/popular/precious?page_size=100&page=1", "s": "precious", "f": "list", "fam": "precious"})
for n in range(101, 388):
    tasks.append({"u": f"https://api.bilibili.com/x/web-interface/popular/series/one?number={n}", "s": "weekly", "f": "list", "fam": "weekly"})
print(f"topup tasks: {len(tasks)}", flush=True)

RUN = r'''
window.__c3 = {state:"running", items:[], log:[], done:0, total:0, risk:0};
(async () => {
  const C = window.__c3;
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
        C.risk++; dead.add(t.fam);
        C.log.push("RISK " + t.fam + " code=" + d.code + " -> 弃源");
        if (C.risk >= 2) { C.state = "aborted-risk"; return; }
        await sleep(180000);
        C.done++; continue;
      }
      const arr = (d.code === 0 && d.data) ? (d.data.list || []) : [];
      for (const x of arr) {
        if (!x || !x.bvid) continue;
        C.items.push({b: x.bvid, t: x.title || "", u: String(x.owner ? x.owner.name : ""), s: t.s});
      }
    } catch(e) { C.log.push("err " + t.s); }
    C.done++;
    await sleep(3500 + Math.random() * 1000);
  }
  C.state = "done";
})();
return "started";
'''
print(js(RUN.replace("TASKS_JSON", json.dumps(tasks)), 60), flush=True)

seen = {json.loads(l)["b"] for l in open(OUT)}
f = open(OUT, "a")
n_new = 0
while True:
    time.sleep(20)
    try:
        d = json.loads(js('const c=window.__c3; const it=c.items.splice(0); const lg=c.log.splice(0); return JSON.stringify({s:c.state, d:c.done, t:c.total, risk:c.risk, items:it, log:lg})', 60))
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
    print(f"topup {d['d']}/{d['t']} new={n_new} total={len(seen)} risk={d['risk']}", flush=True)
    if d["s"] != "running":
        print("END:", d["s"], flush=True)
        break
f.close()
print("TOPUP-DONE", flush=True)
