"""E13 主题打标：分层抽样 -> v4-flash 标 48 类主题编号，断点续跑"""
import json, time, random, urllib.request, urllib.parse

BASE = "http://127.0.0.1:8765"
SCRATCH = "/tmp/claude-1000/-home-leo----bilibili/7ae81ed2-efb1-446d-95dc-6901201fe793/scratchpad"
TAX = json.load(open("/home/leo/桌面/bilibili/interest-model/taxonomy.json"))
LEAVES = [l for g in TAX["groups"].values() for l in g]

def js(code, timeout=60):
    req = urllib.request.Request(BASE + "/js", data=code.encode(), method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        out = json.loads(r.read())
        if "error" in out:
            raise RuntimeError(out["error"][:200])
        return out["result"]

def get(path, timeout=60):
    with urllib.request.urlopen(BASE + path, timeout=timeout) as r:
        return r.read().decode()

corpus = [json.loads(l) for l in open(SCRATCH + "/corpus.jsonl")]
random.seed(7)
done = set()
try:
    done = {json.loads(l)["b"] for l in open(SCRATCH + "/topics.jsonl")}
except FileNotFoundError:
    pass
# 分层：rcmd/rank 全收，weekly/new/popular 抽样补到 6000
keep, rest = [], []
for r in corpus:
    (keep if r["s"] == "rcmd" or r["s"].startswith("rank") else rest).append(r)
random.shuffle(rest)
sel = keep + rest[:max(0, 99999 - len(keep))]
items = [r for r in sel if r["b"] not in done]
print(f"selected={len(sel)} to-label={len(items)}", flush=True)
if not items:
    print("DONE topics"); raise SystemExit

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

menu = "\n".join(f"{i+1}={t}" for i, t in enumerate(LEAVES))
SYS = ("你是B站视频主题分类器。主题表（编号=名称）：\n" + menu +
       "\n\n输入为列表，每行一个视频：序号|标题|UP主。为每行选出最贴切的一个主题编号（1-48）。"
       "\n输出 JSON：{\"r\":{\"1\":17,\"2\":33,...}}，键为行号，值为主题编号，覆盖所有行，不要输出其他内容。")

RUN = r'''
window.__tp = {state:"running", out:[], done:0, total:0, usage:{i:0,o:0,h:0}, errs:0, lastErr:null};
(async () => {
  const L = window.__tp;
  const items = ITEMS_JSON;
  const SYS = SYS_JSON;
  L.total = items.length;
  const key = (localStorage.getItem("bfm_api_key")||"").trim();
  const chunks = [];
  for (let off=0; off<items.length; off+=80) chunks.push(items.slice(off, off+80));
  let ci = 0;
  const worker = async () => {
    while (ci < chunks.length) {
      const chunk = chunks[ci++];
      const payload = chunk.map((it,i)=> (i+1)+"|"+String(it.t||"").replace(/[|\n]/g," ").slice(0,70)+"|"+String(it.u||"").slice(0,20)).join("\n");
      for (let att=0; att<3; att++) {
        try {
          const r = await fetch("https://api.deepseek.com/chat/completions", {method:"POST",
            headers:{"content-type":"application/json","authorization":"Bearer "+key},
            body: JSON.stringify({model:"deepseek-v4-flash", thinking:{type:"disabled"}, max_tokens:1500,
              response_format:{type:"json_object"},
              messages:[{role:"system",content:SYS},{role:"user",content:payload}]})});
          const d = await r.json();
          if (d.usage) { L.usage.i+=d.usage.prompt_tokens||0; L.usage.o+=d.usage.completion_tokens||0; L.usage.h+=d.usage.prompt_cache_hit_tokens||0; }
          if (!d.choices) throw new Error("api:"+JSON.stringify(d).slice(0,80));
          const out = JSON.parse(d.choices[0].message.content);
          for (const [k,v] of Object.entries(out.r||{})) {
            const idx = parseInt(k,10)-1, tid = parseInt(v,10);
            if (idx>=0 && idx<chunk.length && tid>=1 && tid<=48) L.out.push({b: chunk[idx].b, tid});
          }
          break;
        } catch(e) { L.errs++; L.lastErr = String(e).slice(0,120); await new Promise(r=>setTimeout(r,3000)); }
      }
      L.done += chunk.length;
    }
  };
  await Promise.all([worker(), worker(), worker()]);
  L.state = "done";
})();
return "started";
'''
RUN = RUN.replace("ITEMS_JSON", json.dumps(items, ensure_ascii=False)).replace("SYS_JSON", json.dumps(SYS, ensure_ascii=False))
print(js(RUN, 120), flush=True)

f = open(SCRATCH + "/topics.jsonl", "a")
t0 = time.time()
while True:
    time.sleep(12)
    try:
        d = json.loads(js('const L=window.__tp; const o=L.out.splice(0); return JSON.stringify({s:L.state,d:L.done,t:L.total,e:L.errs,le:L.lastErr,u:L.usage,out:o})', 90))
    except Exception as e:
        print("poll-err", e, flush=True)
        continue
    for r in d["out"]:
        f.write(json.dumps(r) + "\n")
    f.flush()
    u = d["u"]
    cost = ((u["i"] - u["h"]) * 1.58 + u["h"] * 0.05 + u["o"] * 4.75) / 1e6
    print(f"{d['d']}/{d['t']} errs={d['e']} cost=Y{cost:.3f} elapsed={int(time.time()-t0)}s le={d['le']}", flush=True)
    if d["s"] != "running":
        break
f.close()
print("DONE topics", flush=True)
