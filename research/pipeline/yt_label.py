"""E20 打标：YouTube 语料一遍标三轴（专业 p/- , 主题 1-48 , 情绪 1-9），断点续跑。"""
import json, time, urllib.request, urllib.parse

BASE = "http://127.0.0.1:8765"
S = "/tmp/claude-1000/-home-leo----bilibili/7ae81ed2-efb1-446d-95dc-6901201fe793/scratchpad"
TAX = json.load(open("/home/leo/桌面/bilibili/interest-model/taxonomy.json"))
EMO = json.load(open("/home/leo/桌面/bilibili/interest-model/emotions.json"))
LEAVES = [l for g in TAX["groups"].values() for l in g]
E_NAMES = [e["name"] for e in EMO["emotions"]]

def js(code, timeout=90):
    req = urllib.request.Request(BASE + "/js", data=code.encode(), method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        out = json.loads(r.read())
        if "error" in out:
            raise RuntimeError(out["error"][:150])
        return out["result"]

corpus = [json.loads(l) for l in open(S + "/yt_corpus.jsonl")]
done = set()
try:
    done = {json.loads(l)["b"] for l in open(S + "/yt_labels.jsonl")}
except FileNotFoundError:
    pass
items = [r for r in corpus if r["b"] not in done]
print(f"corpus={len(corpus)} to-label={len(items)}", flush=True)
if not items:
    print("YT-LABEL-DONE")
    raise SystemExit

t_menu = "\n".join(f"{i+1}={t}" for i, t in enumerate(LEAVES))
e_menu = " ".join(f"{i+1}={n}" for i, n in enumerate(E_NAMES))
SYS = ("你是 YouTube 视频分类器，标题可能是任何语言。输入为列表，每行：序号|标题|频道名。对每行输出三个判断，用竖线连接：\n"
      "第1项 p 或 -：p=专业内容，有信息密度、看完能学到真东西（硬核科普、技术编程、财经分析、学术、深度纪录片、严肃行业解读、高质量教学），且语气冷静克制；情绪化标题党式内容不算，填 -\n"
      "第2项 主题编号 1-48：\n" + t_menu + "\n"
      "第3项 情绪编号 1-9，标题传递给观众的主导情绪：" + e_menu + "\n"
      "输出 JSON：{\"r\":{\"1\":\"p|17|3\",\"2\":\"-|33|2\",...}}，覆盖所有行，不要输出其他内容。")

RUN = r'''
window.__yl = {state:"running", out:[], done:0, total:0, usage:{i:0,o:0,h:0}, errs:0, lastErr:null};
(async () => {
  const L = window.__yl;
  const items = ITEMS_JSON;
  const SYS = SYS_JSON;
  L.total = items.length;
  const key = (localStorage.getItem("yfm_api_key") || localStorage.getItem("bfm_api_key") || "").trim();
  const chunks = [];
  for (let off=0; off<items.length; off+=60) chunks.push(items.slice(off, off+60));
  let ci = 0;
  const worker = async () => {
    while (ci < chunks.length) {
      const chunk = chunks[ci++];
      const payload = chunk.map((it,i)=> (i+1)+"|"+String(it.t||"").replace(/[|\n]/g," ").slice(0,90)+"|"+String(it.u||"").slice(0,30)).join("\n");
      for (let att=0; att<3; att++) {
        try {
          const r = await fetch("https://api.deepseek.com/chat/completions", {method:"POST",
            headers:{"content-type":"application/json","authorization":"Bearer "+key},
            body: JSON.stringify({model:"deepseek-v4-flash", thinking:{type:"disabled"}, max_tokens:2000,
              response_format:{type:"json_object"},
              messages:[{role:"system",content:SYS},{role:"user",content:payload}]})});
          const d = await r.json();
          if (d.usage) { L.usage.i+=d.usage.prompt_tokens||0; L.usage.o+=d.usage.completion_tokens||0; L.usage.h+=d.usage.prompt_cache_hit_tokens||0; }
          if (!d.choices) throw new Error("api:"+JSON.stringify(d).slice(0,80));
          const out = JSON.parse(d.choices[0].message.content);
          for (const [k,v] of Object.entries(out.r||{})) {
            const idx = parseInt(k,10)-1;
            const m = String(v).match(/^([p-])\|(\d{1,2})\|(\d)$/);
            if (idx>=0 && idx<chunk.length && m) {
              const tid = parseInt(m[2],10), eid = parseInt(m[3],10);
              if (tid>=1 && tid<=48 && eid>=1 && eid<=9)
                L.out.push({b: chunk[idx].b, pro: m[1]==="p"?1:0, tid, eid});
            }
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

f = open(S + "/yt_labels.jsonl", "a")
t0 = time.time()
while True:
    time.sleep(12)
    try:
        d = json.loads(js('const L=window.__yl; const o=L.out.splice(0); return JSON.stringify({s:L.state,d:L.done,t:L.total,e:L.errs,le:L.lastErr,u:L.usage,out:o})'))
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
print("YT-LABEL-DONE", flush=True)
