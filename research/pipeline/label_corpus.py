"""大规模打标：分层抽样 -> deepseek-chat 金标（3并发、断点续跑）
audit 模式：--audit self 自一致性复标 / --audit strong deepseek-reasoner 强审计"""
import json, time, random, sys, urllib.request, urllib.parse

BASE = "http://127.0.0.1:8765"
SCRATCH = "/tmp/claude-1000/-home-leo----bilibili/7ae81ed2-efb1-446d-95dc-6901201fe793/scratchpad"
MODE = sys.argv[sys.argv.index("--audit") + 1] if "--audit" in sys.argv else "main"
OUT = {"main": "/labels.jsonl", "self": "/labels_audit_self.jsonl", "strong": "/labels_audit_strong.jsonl",
       "second": "/labels_second.jsonl", "arb": "/labels_arb.jsonl", "evalclean": "/labels_eval.jsonl"}[MODE]
PRO_MODES = {"strong", "arb", "evalclean"}
MODEL = "deepseek-v4-pro" if MODE in PRO_MODES else "deepseek-v4-flash"
BATCH = 30 if MODE in PRO_MODES else 100
WORKERS = 10 if MODE in ("arb", "evalclean") else 3

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
random.seed(42)

if MODE == "main":
    done = set()
    try:
        done = {json.loads(l)["b"] for l in open(SCRATCH + OUT)}
    except FileNotFoundError:
        pass
    # 分层：rcmd/rank/weekly/popular 全收，newlist 采样补足到 20k
    keep, newl = [], []
    for r in corpus:
        (newl if r["s"].startswith("new_") else keep).append(r)
    random.shuffle(newl)
    budget = max(0, 20000 - len(keep))
    sel = keep + newl[:budget]
    items = [r for r in sel if r["b"] not in done]
    print(f"corpus={len(corpus)} selected={len(sel)} to-label={len(items)}", flush=True)
else:
    by_b = {r["b"]: r for r in corpus}
    gold = [json.loads(l) for l in open(SCRATCH + "/labels.jsonl")]
    done = set()
    try:
        done = {json.loads(l)["b"] for l in open(SCRATCH + OUT)}
    except FileNotFoundError:
        pass
    if MODE in ("self", "strong"):
        random.shuffle(gold)
        n = 500 if MODE == "self" else 250
        items = [by_b[g["b"]] for g in gold[:n] if g["b"] in by_b]
    elif MODE == "second":
        random.shuffle(gold)  # 打乱批次组合，保证独立性
        items = [by_b[g["b"]] for g in gold if g["b"] in by_b and g["b"] not in done]
    elif MODE == "arb":
        second = {json.loads(l)["b"]: json.loads(l) for l in open(SCRATCH + "/labels_second.jsonl")}
        g1 = {g["b"]: g for g in gold}
        dis = [b for b, s in second.items() if b in g1 and (g1[b]["pro"] != s["pro"] or g1[b]["neg"] != s["neg"])]
        items = [by_b[b] for b in dis if b in by_b and b not in done]
    elif MODE == "evalclean":
        sp = json.load(open(SCRATCH + "/splits.json"))
        target = set(sp["val"]) | set(sp["test"])
        items = [by_b[b] for b in target if b in by_b and b not in done]
    print(f"{MODE}: {len(items)} samples, model={MODEL}", flush=True)

if not items:
    print("nothing to do; DONE", flush=True)
    sys.exit(0)

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

SYS = (
    "你是B站视频分类器。输入为列表，每行一个视频：序号|标题|UP主。对每行输出两个独立的二元判断，组成两个字符：\n"
    "第1位 p 或 -：p=专业内容——有信息密度、看完能学到真东西（硬核知识科普、技术/编程/工程、财经与宏观分析、学术、深度纪录片、严肃行业解读、高质量教学），"
    "且语气冷静克制有建设性。情绪化标题党式\"分析\"、贩卖焦虑的\"干货\"、蹭热点的浅科普不算专业；否则填 -\n"
    "第2位 n 或 -：n=负能量——贩卖焦虑、渲染恐慌灾难、煽动对立引战、末日论、阴谋论、猎奇审丑、擦边、狗血冲突、贩卖愤怒的社会新闻、卖课引流营销号；否则填 -\n"
    "输出 JSON：{\"r\":{\"1\":\"p-\",\"2\":\"-n\",\"3\":\"--\",...}}，键为每行序号，覆盖所有行，不要输出其他内容。"
)

RUN = r'''
window.__lab = {state:"running", out:[], done:0, total:0, usage:{i:0,o:0,h:0}, errs:0, lastErr:null};
(async () => {
  const L = window.__lab;
  const items = ITEMS_JSON;
  const MODEL = "MODEL_NAME";
  const BATCH = BATCH_N;
  const SYS = SYS_JSON;
  L.total = items.length;
  const key = (localStorage.getItem("bfm_api_key")||"").trim();
  const chunks = [];
  for (let off=0; off<items.length; off+=BATCH) chunks.push(items.slice(off, off+BATCH));
  let ci = 0;
  const worker = async () => {
    while (ci < chunks.length) {
      const chunk = chunks[ci++];
      const payload = chunk.map((it,i)=> (i+1)+"|"+String(it.t||"").replace(/[|\n]/g," ").slice(0,80)+"|"+String(it.u||"").slice(0,25)).join("\n");
      const body = {model: MODEL, max_tokens: MODEL==="deepseek-v4-pro"?8000:1600,
        messages:[{role:"system",content:SYS},{role:"user",content:payload}]};
      if (MODEL === "deepseek-v4-flash") { body.thinking = {type:"disabled"}; body.response_format = {type:"json_object"}; }
      for (let att=0; att<3; att++) {
        try {
          const r = await fetch("https://api.deepseek.com/chat/completions", {method:"POST",
            headers:{"content-type":"application/json","authorization":"Bearer "+key},
            body: JSON.stringify(body)});
          const d = await r.json();
          if (d.usage) { L.usage.i += d.usage.prompt_tokens||0; L.usage.o += d.usage.completion_tokens||0; L.usage.h += d.usage.prompt_cache_hit_tokens||0; }
          if (!d.choices) throw new Error("api:"+JSON.stringify(d).slice(0,100));
          let txt = d.choices[0].message.content;
          const m = txt.match(/\{[\s\S]*\}/);
          const out = JSON.parse(m ? m[0] : txt);
          for (const [k,v] of Object.entries(out.r||{})) {
            const idx = parseInt(k,10)-1;
            if (idx>=0 && idx<chunk.length && /^[p-][n-]$/.test(v))
              L.out.push({b: chunk[idx].b, lab: v});
          }
          break;
        } catch(e) { L.errs++; L.lastErr = String(e).slice(0,150); await new Promise(r=>setTimeout(r,3000)); }
      }
      L.done += chunk.length;
    }
  };
  await Promise.all(Array.from({length: WORKERS_N}, () => worker()));
  L.state = "done";
})();
return "started";
'''
RUN = (RUN.replace("ITEMS_JSON", json.dumps(items, ensure_ascii=False))
          .replace("MODEL_NAME", MODEL).replace("BATCH_N", str(BATCH)).replace("WORKERS_N", str(WORKERS))
          .replace("SYS_JSON", json.dumps(SYS, ensure_ascii=False)))
print(js(RUN, 120), flush=True)

f = open(SCRATCH + OUT, "a")
t0 = time.time()
while True:
    time.sleep(15)
    try:
        d = json.loads(js('const L=window.__lab; const o=L.out.splice(0); return JSON.stringify({s:L.state,d:L.done,t:L.total,e:L.errs,le:L.lastErr,u:L.usage,out:o})', 90))
    except Exception as e:
        print("poll-err", e, flush=True)
        continue
    for r in d["out"]:
        f.write(json.dumps({"b": r["b"], "pro": 1 if r["lab"][0] == "p" else 0, "neg": 1 if r["lab"][1] == "n" else 0}, ensure_ascii=False) + "\n")
    f.flush()
    u = d["u"]
    peak = 2 if (1 <= __import__("datetime").datetime.utcnow().hour < 4) or (6 <= __import__("datetime").datetime.utcnow().hour < 10) else 1
    pr = {"deepseek-v4-pro": (4.75, 0.16, 14.3)}.get(MODEL, (1.58, 0.05, 4.75))  # (miss,hit,out) 元/M 非峰
    cost = ((u["i"] - u["h"]) * pr[0] + u["h"] * pr[1] + u["o"] * pr[2]) * peak / 1e6
    print(f"{d['d']}/{d['t']} errs={d['e']} cost=Y{cost:.3f} elapsed={int(time.time()-t0)}s lastErr={d['le']}", flush=True)
    if d["s"] != "running":
        break
f.close()
print("DONE", MODE, flush=True)
