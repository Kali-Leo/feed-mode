"""E22：独立证据——用插件真实的四分类提示词给视频打标（pro/good/ent/junk），
再用独立训练的情绪模型测各组效价。两个系统互不相关，若「精选娱乐」组效价显著更高，即为真证据。"""
import json, time, urllib.parse, urllib.request
import numpy as np

BASE = "http://127.0.0.1:8765"
S = "/tmp/claude-1000/-home-leo----bilibili/7ae81ed2-efb1-446d-95dc-6901201fe793/scratchpad"

def js(code, timeout=90):
    req = urllib.request.Request(BASE + "/js", data=code.encode("utf-8"), method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        out = json.loads(r.read())
        if "error" in out:
            raise RuntimeError(out["error"][:200])
        return out["result"]

def goto(url):
    with urllib.request.urlopen(BASE + "/goto?url=" + urllib.parse.quote(url, safe=""), timeout=90) as r:
        r.read()

# 插件线上使用的四分类提示词（从脚本里原样取出，保证测的就是产品行为）
src = open("/home/leo/桌面/bilibili/bilibili-feed-mode.user.js").read()
i = src.index("const SYSTEM_PROMPT = `") + len("const SYSTEM_PROMPT = `")
SYS = src[i:src.index("`;", i)]
print("提示词取自线上脚本，长度", len(SYS))

corpus = {r["b"]: r for l in open(S + "/corpus.jsonl") for r in [json.loads(l)]}
emo = {}
for l in open(S + "/emotions.jsonl"):
    r = json.loads(l)
    emo.setdefault(r["b"], r["tid"] - 1)
EMO = json.load(open("/home/leo/桌面/bilibili/interest-model/emotions.json"))
VAL = np.array([e["valence"] for e in EMO["emotions"]])

rng = np.random.RandomState(0)
cand = [b for b in emo if b in corpus]
rng.shuffle(cand)
sample = [corpus[b] for b in cand[:2400]]
print("样本:", len(sample))

goto("https://www.bilibili.com/")
time.sleep(6)

RUN = r'''
window.__ev = {state:"running", out:[], done:0, total:0, usage:{i:0,o:0,h:0}, errs:0};
(async () => {
  const L = window.__ev, items = ITEMS, SYS = SYSJ;
  L.total = items.length;
  const key = (localStorage.getItem("bfm_api_key")||"").trim();
  const chunks = [];
  for (let o=0; o<items.length; o+=40) chunks.push(items.slice(o, o+40));
  let ci = 0;
  const worker = async () => {
    while (ci < chunks.length) {
      const ck = chunks[ci++];
      const payload = ck.map((it,i)=> (i+1)+"|"+String(it.t||"").replace(/[|\n]/g," ").slice(0,80)+"|"+String(it.u||"")+"|").join("\n");
      for (let a=0; a<3; a++) {
        try {
          const r = await fetch("https://api.deepseek.com/chat/completions", {method:"POST",
            headers:{"content-type":"application/json","authorization":"Bearer "+key},
            body: JSON.stringify({model:"deepseek-v4-flash", thinking:{type:"disabled"}, max_tokens:800,
              response_format:{type:"json_object"},
              messages:[{role:"system",content:SYS},{role:"user",content:payload}]})});
          const d = await r.json();
          if (d.usage){L.usage.i+=d.usage.prompt_tokens||0;L.usage.o+=d.usage.completion_tokens||0;L.usage.h+=d.usage.prompt_cache_hit_tokens||0;}
          const out = JSON.parse(d.choices[0].message.content);
          const raw = out.r ?? out;
          for (const [k,v] of Object.entries(raw||{})) {
            const idx = parseInt(k,10)-1, c = String(v).trim();
            if (idx>=0 && idx<ck.length && ["p","g","e","j"].includes(c)) L.out.push({b: ck[idx].b, c});
          }
          break;
        } catch(e) { L.errs++; await new Promise(r=>setTimeout(r,2500)); }
      }
      L.done += ck.length;
    }
  };
  await Promise.all([worker(),worker(),worker()]);
  L.state = "done";
})();
return "started";
'''
RUN = RUN.replace("ITEMS", json.dumps([{"b": r["b"], "t": r["t"], "u": r["u"]} for r in sample], ensure_ascii=False)).replace("SYSJ", json.dumps(SYS, ensure_ascii=False))
print(js(RUN, 120))

labels = {}
while True:
    time.sleep(10)
    d = json.loads(js('const L=window.__ev; const o=L.out.splice(0); return JSON.stringify({s:L.state,d:L.done,t:L.total,e:L.errs,u:L.usage,out:o})'))
    for r in d["out"]:
        labels[r["b"]] = r["c"]
    u = d["u"]
    cost = ((u["i"]-u["h"])*1.58 + u["h"]*0.05 + u["o"]*4.75)/1e6
    print(f"  {d['d']}/{d['t']} 已标 {len(labels)} 花费 ¥{cost:.3f}")
    if d["s"] != "running":
        break

groups = {"g": [], "e": [], "p": [], "j": []}
for b, c in labels.items():
    if b in emo:
        groups[c].append(VAL[emo[b]])
print("\n=== 独立证据：四分类各组的情绪效价（情绪模型独立训练） ===")
names = {"g": "精选娱乐 Feel-good", "e": "普通娱乐 Fun", "p": "专业 Learn", "j": "营销水 Junk"}
res = {}
for c in ["g", "e", "p", "j"]:
    v = np.array(groups[c])
    if len(v) < 20:
        continue
    res[c] = {"n": len(v), "mean": float(v.mean()), "neg_share": float((v < 0).mean())}
    print(f"{names[c]:22s} n={len(v):4d}  平均效价 {v.mean():+.3f}  负面内容占比 {(v<0).mean():.1%}")
if "g" in res and "e" in res:
    g, e = np.array(groups["g"]), np.array(groups["e"])
    from math import sqrt
    d_eff = (g.mean() - e.mean()) / sqrt((g.var() + e.var()) / 2)
    print(f"\n精选娱乐 vs 普通娱乐：效价差 {g.mean()-e.mean():+.3f}，效应量 Cohen's d = {d_eff:.2f}")
    print(f"负面内容占比：{(g<0).mean():.1%} vs {(e<0).mean():.1%}")
    res["delta"] = {"diff": float(g.mean()-e.mean()), "cohens_d": float(d_eff),
                    "neg_g": float((g<0).mean()), "neg_e": float((e<0).mean())}
json.dump(res, open(S + "/evidence.json", "w"), indent=1)
print("saved evidence.json")
