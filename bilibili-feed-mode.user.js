// ==UserScript==
// @name         B站首页 娱乐/专业 模式切换
// @name:en      Bilibili Feed Mode: Learn / Feel-good / Fun
// @namespace    leo.bilibili.feedmode
// @version      2.0.6
// @description  内置本地 AI 小模型 + 大模型复核，把B站首页推荐流分为「专业/精选娱乐/娱乐」，左下角开关一键切换。不填 API Key 也能用（本地模型离线分类）；填入 DeepSeek Key 后由大模型复核提升精度（用量实时显示，「容忍」滑条可控制用量，费用由你在 DeepSeek 后台自理）。本项目完全免费。不屏蔽任何广告与商业内容。非官方工具，与哔哩哔哩无关联。
// @description:en  Filter your Bilibili home feed into Learn / Feel-good / Fun with one click. A built-in local AI model works offline out of the box - no API key needed. Add a DeepSeek key for cloud review and higher accuracy; usage and cost are shown live and a tolerance slider controls how much goes to the cloud. Free forever, never handles your money. Does not block ads. Unofficial tool, not affiliated with Bilibili.
// @match        https://www.bilibili.com/
// @match        https://www.bilibili.com/?*
// @match        https://www.bilibili.com/video/*
// @grant        none
// @run-at       document-idle
// @license      GPL-3.0
// @homepageURL  https://github.com/Kali-Leo/feed-mode
// @supportURL   https://github.com/Kali-Leo/feed-mode/issues
// ==/UserScript==
// 本脚本为非官方社区工具，与哔哩哔哩无任何关联。设计原则：不屏蔽广告、不劫持流量、
// 不损害平台与创作者权益。详见仓库 README 与 COMPLIANCE.md。

(function () {
  "use strict";
  if (window.__bfm) return; // 防止重复注入

  const ZH = (navigator.language || "").toLowerCase().startsWith("zh"); // 界面语言跟随浏览器

  // ================= 个人兴趣模型回传（默认关闭） =================
  // 只有在开关条的 🔗 里填了连接码，下面这些才会做事；没填时全部空转，脚本行为与不带此功能时一致。
  // 目标固定为本机 127.0.0.1 的兴趣服务（interest-model/daemon），发的是标题、UP主名、视频 id、
  // 封面地址、观看时长；不发 Cookie、不发账号、不发任何身份信息，也不发往本机以外的任何地方。
  const IM_URL = "http://127.0.0.1:21456/events";
  let IM_TOKEN = (localStorage.getItem("bfm_im_token") || "").trim();
  // 一次性配对：本机程序把配对码放进 URL fragment，脚本立刻抹掉它并换取令牌。
  // 用户不必手抄任何东西；令牌仍是唯一凭证，页面上不显示、不进历史记录。
  function imPair() {
    const m = (location.hash || "").match(/[#&]im-pair=([\w-]{16,64})/);
    if (!m) return;
    const nonce = m[1];
    // 先抹掉地址栏里的配对码，再去兑换，避免它留在历史或被别处读到
    try { history.replaceState(null, "", location.pathname + location.search); } catch (e) { location.hash = ""; }
    fetch("http://127.0.0.1:21456/pair/exchange", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ nonce }),
    }).then((r) => r.ok ? r.json() : null).then((d) => {
      if (!d || !d.token) return;
      localStorage.setItem("bfm_im_token", d.token);
      IM_TOKEN = d.token;
      if (typeof imSetState === "function") imSetState("ok");
      if (imQueue.length && !imTimer) imTimer = setTimeout(imFlush, 500);
    }).catch(() => {});
  }
  imPair();
  // 站点是单页应用：若用户已开着页面、配对码是后加到地址栏的，不会触发重新加载，这里补上
  window.addEventListener("hashchange", imPair);
  const imQueue = [];
  let imTimer = null;
  // 连接状态：off 未启用 / ok 正常 / bad 连接码不对 / offline 本机程序没开
  let imState = IM_TOKEN ? "pending" : "off";
  let imSent = 0, imFails = 0, imWarned = false;
  const imOnState = [];
  function imSetState(s) {
    if (imState === s) return;
    imState = s;
    for (const fn of imOnState) fn(s);
    // 连接码不对是配置错误，用户不改就永远收不到数据，必须说一次
    if (s === "bad" && !imWarned) {
      imWarned = true;
      alert(ZH ? "兴趣程序的连接码不对，浏览记录没有送达。请点开关条上的 🔗 重新粘贴（程序启动时会打印新的连接码）。"
               : "The interest service rejected the connection code, so nothing is being recorded. Click 🔗 on the switch bar and paste the current code (the service prints it on startup).");
    }
  }
  function imFlush() {
    imTimer = null;
    if (!IM_TOKEN || !imQueue.length) return;
    const batch = imQueue.splice(0, 200);
    fetch(IM_URL, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-IM-Token": IM_TOKEN },
      body: JSON.stringify(batch),
      keepalive: true,
    }).then((r) => {
      if (r.ok) { imSent += batch.length; imFails = 0; imSetState("ok"); return; }
      // 403 = 连接码不对：留着也没用，丢弃并提示
      if (r.status === 403) { imSetState("bad"); return; }
      imQueue.unshift(...batch);
      imSetState("offline");
    }).catch(() => {
      // 本机程序没开：事件放回队列，下次再试，不丢数据
      imQueue.unshift(...batch);
      if (imQueue.length > 1000) imQueue.splice(0, imQueue.length - 1000);
      imFails++;
      imSetState("offline");
      if (!imTimer) imTimer = setTimeout(imFlush, Math.min(60000, 5000 * Math.pow(2, Math.min(imFails, 4))));
    });
  }
  function imReport(ev) {
    if (!IM_TOKEN) return;
    ev.site = "bilibili";
    ev.ts = Date.now() / 1000;
    imQueue.push(ev);
    if (!imTimer) imTimer = setTimeout(imFlush, 5000);
  }
  const imCover = (card) => {
    const img = card.querySelector("img");
    return img && img.src ? img.src.split("@")[0].replace(/^https?:/, "https:") : "";
  };

  // 视频页只做一件事：这次看了多久。没填连接码就到此为止，整段不运行。
  if (/^\/video\//.test(location.pathname)) {
    if (!IM_TOKEN) return;
    const bvid = (location.pathname.match(/BV[0-9A-Za-z]{10}/) || [])[0];
    if (!bvid) return;
    let watched = 0, lastTick = Date.now(), counting = !document.hidden;
    const tick = () => {
      const now = Date.now();
      if (counting) watched += (now - lastTick) / 1000;
      lastTick = now;
    };
    setInterval(tick, 5000);
    const send = () => {
      tick();
      if (watched < 5) return; // 打开就关掉的不算看过
      const v = document.querySelector("video");
      const h1 = document.querySelector("h1.video-title, h1[title]");
      const up = document.querySelector(".up-name, a.up-name, .username");
      imReport({
        type: "watch", id: bvid,
        t: ((h1 && (h1.getAttribute("title") || h1.textContent)) || document.title.replace(/_哔哩哔哩.*$/, "")).trim(),
        u: (up && up.textContent || "").trim(),
        pic: "", dwell: Math.round(watched), dur: v && v.duration ? Math.round(v.duration) : 0,
      });
      imFlush();
      watched = 0;
    };
    document.addEventListener("visibilitychange", () => {
      tick();
      counting = !document.hidden;
      if (document.hidden) send();
    });
    window.addEventListener("pagehide", send);
    return;
  }

  // 首页上点开一个视频，记一次「选择」（曝光在卡片处理里记）
  document.addEventListener("click", (e) => {
    if (!IM_TOKEN || !e.target.closest) return;
    const a = e.target.closest('a[href*="/video/BV"]');
    if (!a) return;
    const id = (a.href.match(/BV[0-9A-Za-z]{10}/) || [])[0];
    if (!id) return;
    const card = a.closest(".bili-video-card") || a;
    const t = card.querySelector(".bili-video-card__info--tit");
    const o = card.querySelector(".bili-video-card__info--author, .bili-video-card__info--owner");
    imReport({
      type: "click", id,
      t: ((t && (t.getAttribute("title") || t.textContent)) || "").trim(),
      u: ((o && o.textContent) || "").trim().split("\n")[0].replace(/\s*·.*$/, ""),
      pic: imCover(card), dwell: 0, dur: 0,
    });
  }, true);

  // ================= 配置 =================
  // API Key 通过页面左下角开关条上的 ⚙ 按钮设置，仅保存在你自己浏览器的 localStorage 中，
  // 不写在代码里、不随脚本分发、不上传到任何地方。未设置 key 时退回本地关键词规则分类。
  const API_KEY = (localStorage.getItem("bfm_api_key") || "").trim();
  const API_URL = localStorage.getItem("bfm_api_url") || "https://api.deepseek.com/chat/completions";
  const MODEL = localStorage.getItem("bfm_model") || "deepseek-v4-flash"; // 旧名 deepseek-chat 已于 2026-07 退役
  const BATCH_SIZE = 40;     // 攒够多少条发一次请求（批量越大，system prompt 摊得越薄）
  const BATCH_WAIT_MS = 400; // 或最多等待多久
  // ========================================

  // 提示词与输入输出格式均为省 token 设计：输入用行式紧凑格式（不发 id），
  // 输出用「序号→单字母」映射（输出 token 单价更高，压缩收益最大）
  const SYSTEM_PROMPT = `你是B站视频分类器。输入为列表，每行一个视频，格式：序号|标题|UP主|标签（可能为空）。把每个视频分为四类之一：
- p（专业）：有信息密度、看完能学到真东西的内容——硬核知识科普、技术/编程/工程、财经与宏观分析、学术、深度纪录片、严肃行业解读、高质量教学，且情绪基调冷静克制、有建设性（看完是"搞懂了"而不是"更焦虑了"）。贩卖焦虑、渲染恐慌灾难、煽动对立、末日论调、阴谋论、"要崩盘/要完蛋/劲爆"式情绪化标题党分析，即使话题专业也不算 p：归 e，含营销引流归 j。宁缺毋滥。
- g（精选娱乐）：看完心情变好（愉悦、感动或惊叹）的娱乐——治愈、温暖、纯粹的欢笑、才华与匠心（高水平创作、音乐、手艺、动画）、萌宠自然、美食美景、真诚的生活记录、高质量游戏/影视。
- e（普通娱乐）：其他娱乐，尤其是制造对立/引战的话题、蹭热点骂战、猎奇审丑、擦边、狗血冲突、贩卖愤怒或焦虑的社会新闻、无营养的快餐剪辑。g 和 e 之间拿不准归 e（精选宁缺毋滥）。
- j（营销水）：营销号、卖课/引流（"私信领资料""训练营""副业月入"类）、贩卖焦虑的成功学、标题党软广、水内容。标题带"教程""知识"但实为卖课引流的归 j；情侣日常、个人抱怨归 e。

若某行标签为空且仅凭标题和UP主名确实无法判断，该行可给 "?"（之后会带标签再问你）；标签非空必须给明确分类。
输出 JSON：{"r":{"1":"p","2":"e",...}}，键为每行序号，值为 p/g/e/j/?，覆盖所有行，不要输出其他内容。`;

  const LS = { mode: "bfm_mode", cache: "bfm_cache", up: "bfm_up" };
  const load = (k, d) => { try { return JSON.parse(localStorage.getItem(k)) ?? d; } catch { return d; } };
  const cache = load(LS.cache, {});   // bvid -> "pro"|"good"|"ent"|"junk"
  for (const k of Object.keys(cache)) if (cache[k] === "unk") delete cache[k];
  if (localStorage.getItem("bfm_cache_v") !== "2") { // v2 引入精选娱乐：旧的 ent 里可能藏着 good，清掉重判
    for (const k of Object.keys(cache)) if (cache[k] === "ent") delete cache[k];
    localStorage.setItem("bfm_cache_v", "2");
  }
  if (localStorage.getItem("bfm_cache_v") !== "3") { // v3 专业模式加入情绪门槛：旧的 pro 按新标准重判
    for (const k of Object.keys(cache)) if (cache[k] === "pro") delete cache[k];
    sessionStorage.removeItem("bfm_pool"); // 缓冲池里的旧标准存货一并作废
    localStorage.setItem("bfm_cache_v", "3");
  }
  const upRule = load(LS.up, {});     // UP主名 -> 分类 (Shift+点角标写入)
  if (Object.keys(cache).length > 5000) { for (const k of Object.keys(cache).slice(0, 2500)) delete cache[k]; }
  let saveTimer = null;
  const save = () => {
    clearTimeout(saveTimer);
    saveTimer = setTimeout(() => {
      localStorage.setItem(LS.cache, JSON.stringify(cache));
      localStorage.setItem(LS.up, JSON.stringify(upRule));
    }, 800);
  };

  // ================= 本地学生模型（无 Key 也可用；训练与验证记录见仓库 research/ E5~E12） =================
  // 字符 n-gram 哈希线性分类器（int8 量化 64KB），输出"专业内容"概率；推理微秒级、离线零成本。
  // 由 1.7 万条 LLM 标注的多来源全站语料训练，JS 推理与训练侧 sklearn 位级对齐（含 emoji 码点、空白折叠）。
  const FM_CFG = { dims: 65536, ngLo: 1, ngHi: 3, scale: 0.04569815844297409, bias: 0.28706878423690796 };
  const FM_B64 = "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";
  const FM_W = (() => { const bin = atob(FM_B64); const w = new Int8Array(bin.length); for (let i = 0; i < bin.length; i++) w[i] = (bin.charCodeAt(i) << 24) >> 24; return w; })();
  function fmHash(bytes) { // murmurhash3_32 (x86, seed=0)，与 sklearn 一致
    const c1 = 0xcc9e2d51, c2 = 0x1b873593;
    let h = 0;
    const n = bytes.length - (bytes.length % 4);
    for (let i = 0; i < n; i += 4) {
      let k = (bytes[i] | (bytes[i + 1] << 8) | (bytes[i + 2] << 16) | (bytes[i + 3] << 24)) >>> 0;
      k = Math.imul(k, c1); k = (k << 15) | (k >>> 17); k = Math.imul(k, c2);
      h ^= k; h = (h << 13) | (h >>> 19); h = (Math.imul(h, 5) + 0xe6546b64) >>> 0;
    }
    let k = 0;
    const tail = bytes.length % 4;
    if (tail >= 3) k ^= bytes[n + 2] << 16;
    if (tail >= 2) k ^= bytes[n + 1] << 8;
    if (tail >= 1) { k ^= bytes[n]; k = Math.imul(k >>> 0, c1); k = (k << 15) | (k >>> 17); k = Math.imul(k, c2); h ^= k; }
    h ^= bytes.length;
    h ^= h >>> 16; h = Math.imul(h, 0x85ebca6b);
    h ^= h >>> 13; h = Math.imul(h, 0xc2b2ae35);
    h ^= h >>> 16;
    return h | 0;
  }
  const fmEnc = new TextEncoder();
  function fmFeatures(title, up) {
    const s = (String(title || "") + " \x01 " + String(up || "")).toLowerCase().replace(/\s\s+/g, " ");
    const chars = Array.from(s); // 按 Unicode 码点切分，与训练侧一致
    const counts = new Map();
    for (let n = FM_CFG.ngLo; n <= FM_CFG.ngHi; n++)
      for (let i = 0; i + n <= chars.length; i++) {
        const h = fmHash(fmEnc.encode(chars.slice(i, i + n).join("")));
        const idx = Math.abs(h) % FM_CFG.dims;
        counts.set(idx, (counts.get(idx) || 0) + 1);
      }
    let norm = 0;
    for (const v of counts.values()) norm += v * v;
    return { counts, norm: Math.sqrt(norm) || 1 };
  }
  // 端上自适应（研究 E11）：只学 LLM 确认过的标签，稀疏增量存本地，数据不出设备。
  // 作用：本地模型逐渐适应你的信息流领域分布（陌生领域的召回随使用自动恢复）
  const fmDelta = load("bfm_delta", {});
  let fmDeltaTimer = null;
  const fmDeltaSave = () => { clearTimeout(fmDeltaTimer); fmDeltaTimer = setTimeout(() => { try { localStorage.setItem("bfm_delta", JSON.stringify(fmDelta)); } catch (e) {} }, 2000); };
  function fmScore(counts, norm) {
    let s = 0, ds = 0;
    for (const [idx, c] of counts) { s += FM_W[idx] * c; const d = fmDelta[idx]; if (d) ds += d * c; }
    return (s * FM_CFG.scale) / norm + FM_CFG.bias + ds / norm;
  }
  function fmProb(title, up) {
    const { counts, norm } = fmFeatures(title, up);
    return 1 / (1 + Math.exp(-fmScore(counts, norm)));
  }
  function fmLearn(title, up, y) { // y: 1=专业 0=非专业（仅接受 LLM 判定，防自我强化）
    const { counts, norm } = fmFeatures(title, up);
    const p = 1 / (1 + Math.exp(-fmScore(counts, norm)));
    const g = 0.3 * (y - p);
    for (const [idx, c] of counts) {
      const v = (fmDelta[idx] || 0) + (g * c) / norm;
      if (Math.abs(v) < 0.001) delete fmDelta[idx];
      else fmDelta[idx] = Math.max(-1, Math.min(1, v)); // 限幅
    }
    const keys = Object.keys(fmDelta);
    if (keys.length > 30000) { // 容量上限：淘汰最小权重
      keys.sort((a, b) => Math.abs(fmDelta[a]) - Math.abs(fmDelta[b]));
      for (const k of keys.slice(0, 5000)) delete fmDelta[k];
    }
    fmDeltaSave();
  }
  // 容忍度：0=零容忍（全量送大模型复核）… 100=最省（本地模型大包大揽）。
  // 阈值→预计送 LLM 比例的估算表来自 360 条真实推荐流实测分布（研究 E9）
  const FM_SHARE = {"0": 1.0, "5": 0.981, "10": 0.881, "15": 0.778, "20": 0.664, "25": 0.6, "30": 0.531, "35": 0.478, "40": 0.425, "45": 0.369, "50": 0.325, "55": 0.261, "60": 0.219, "65": 0.183, "70": 0.142, "75": 0.114, "80": 0.072, "85": 0.033, "90": 0.008, "95": 0.0, "100": 0.0};
  let tol = Math.max(0, Math.min(100, Number(localStorage.getItem("bfm_tol") ?? 50)));
  const ROUTE = { low: 0, high: 2, audit: 0 };
  function applyTol() {
    ROUTE.off = tol >= 100; // 拉到头 = 完全不用 LLM，只信本地模型，置信度不足的丢弃
    ROUTE.low = tol === 0 ? -1 : Math.min(0.60, 0.10 + 0.008 * tol); // 低于此：本地判非专业，不送 LLM
    ROUTE.high = tol <= 50 ? 2 : 0.995 - 0.003 * (tol - 50);         // 高于此：本地直接判专业，不送 LLM
    ROUTE.audit = tol === 0 ? 0 : Math.max(0.01, 0.06 - 0.0005 * tol); // 判负审计抽查率（喂自适应+防整域漏判）
  }
  applyTol();
  const fmShareEst = () => {
    if (ROUTE.off) return 0;
    const k = String(Math.min(100, Math.max(0, Math.round((ROUTE.low * 100) / 5) * 5)));
    return FM_SHARE[k] ?? 0.35;
  };

  // ---------- 样式 ----------
  const style = document.createElement("style");
  style.textContent = `
    /* 模式可见性：娱乐=good+ent，精选(gent)=仅good，专业=仅pro */
    html[data-bfm-mode="pro"] [data-bfm="ent"],
    html[data-bfm-mode="pro"] [data-bfm="good"],
    html[data-bfm-mode="ent"] [data-bfm="pro"],
    html[data-bfm-mode="gent"] [data-bfm="pro"],
    html[data-bfm-mode="gent"] [data-bfm="ent"],
    html[data-bfm-mode="pro"] [data-bfm="junk"],
    html[data-bfm-mode="ent"] [data-bfm="junk"],
    html[data-bfm-mode="gent"] [data-bfm="junk"] { display: none !important; }
    /* 注意：B站的商业推广卡（data-bfm="ad"，含广告与课堂等自营推广位）在任何模式下都不隐藏，
       本脚本不做广告屏蔽，不损害平台及创作者收益 */
    /* 过滤模式下未分类的卡片先隐藏，分类完成后再放行，避免"看见了才消失"的闪烁 */
    html[data-bfm-mode="pro"] [data-bfm="pending"],
    html[data-bfm-mode="ent"] [data-bfm="pending"],
    html[data-bfm-mode="gent"] [data-bfm="pending"] { display: none !important; }
    /* 与缓冲池注入的卡片重复的原生卡片，在过滤模式下隐藏 */
    html[data-bfm-mode="pro"] [data-bfm="dup"],
    html[data-bfm-mode="ent"] [data-bfm="dup"],
    html[data-bfm-mode="gent"] [data-bfm="dup"] { display: none !important; }
    /* 注入卡片只在过滤模式下出现，"全部"模式隐藏以免和原生流重复 */
    html[data-bfm-mode="all"] [data-bfm-injected] { display: none !important; }
    /* 过滤模式下接管信息流：原生视频卡片隐藏（内容与缓冲池同源），只显示注入卡片，
       注入永远只往末尾追加，从结构上杜绝"已显示的卡片前后移动"。
       豁免不隐藏：广告/商业推广卡（data-bfm="ad"）和番剧/影视等官方推广位（.floor-single-card，
       由上面的分类规则决定在哪些模式显示）——不损害平台商业权益 */
    html[data-bfm-mode="pro"] .container.is-version8 > *:not([data-bfm-injected]):not([data-bfm="ad"]):not(.floor-single-card[data-bfm]),
    html[data-bfm-mode="ent"] .container.is-version8 > *:not([data-bfm-injected]):not([data-bfm="ad"]):not(.floor-single-card[data-bfm]),
    html[data-bfm-mode="gent"] .container.is-version8 > *:not([data-bfm-injected]):not([data-bfm="ad"]):not(.floor-single-card[data-bfm]) { display: none !important; }
    #bfm-switch {
      position: fixed; bottom: 24px; left: 24px; z-index: 99999;
      display: flex; gap: 2px; padding: 3px; border-radius: 999px;
      background: rgba(255,255,255,.95); box-shadow: 0 2px 10px rgba(0,0,0,.15);
      font-size: 13px; user-select: none;
    }
    #bfm-switch button {
      border: 0; background: transparent; padding: 4px 12px; border-radius: 999px;
      cursor: pointer; color: #61666d; font-size: 13px;
    }
    #bfm-switch button.on { background: #00aeec; color: #fff; }
    #bfm-tol { display: flex; align-items: center; gap: 4px; padding: 0 6px 0 10px;
      border-left: 1px solid #e3e5e7; margin-left: 4px; color: #61666d; font-size: 12px; }
    #bfm-tol input { width: 60px; accent-color: #0d9488; }
    #bfm-tol b { min-width: 36px; font-weight: normal; font-size: 11px; }
    #bfm-tok { display: flex; align-items: center; padding: 0 6px; color: #9499a0;
      font-size: 11px; white-space: nowrap; }
  `;
  document.head.appendChild(style);

  // ---------- 切换开关 ----------
  let mode = localStorage.getItem(LS.mode) || "all";
  const sw = document.createElement("div");
  sw.id = "bfm-switch";
  for (const [m, label] of (ZH ? [["all", "全部"], ["ent", "娱乐"], ["gent", "精选娱乐"], ["pro", "专业"]] : [["all", "All"], ["ent", "Fun"], ["gent", "Feel-good"], ["pro", "Learn"]])) {
    const b = document.createElement("button");
    b.textContent = label;
    b.dataset.m = m;
    b.onclick = () => setMode(m);
    sw.appendChild(b);
  }
  const cfgBtn = document.createElement("button");
  cfgBtn.textContent = "⚙";
  cfgBtn.title = ZH ? "设置 API Key（用于 LLM 智能分类）" : "Set API key for AI classification";
  cfgBtn.onclick = () => {
    const cur = localStorage.getItem("bfm_api_key") || "";
    const inp = prompt(ZH
      ? "输入你自己的 DeepSeek API Key（在 platform.deepseek.com 申请，用量与费用由你在 DeepSeek 后台自理，本脚本免费且不经手任何费用）。\n" +
        "不填也能用：内置本地小模型（免费离线）支撑「专业」模式主要功能，填 Key 后由大模型复核、精度更高。\n\n" +
        "隐私说明：启用后，仅视频的「标题、UP主名、标签」会发送给 DeepSeek 用于分类；\n" +
        "不会发送你的账号信息、Cookie 或观看历史。Key 仅保存在你自己的浏览器中。"
      : "Enter your DeepSeek API key (get one at platform.deepseek.com; usage is billed by DeepSeek to you — this script is free and never handles money).\n" +
        "Optional: the built-in local model already powers Learn mode offline for free; a key adds cloud review for higher accuracy.\n\n" +
        "Privacy: only video titles, uploader names and tags are sent to DeepSeek for classification;\n" +
        "never your account, cookies or watch history. The key stays in your browser.",
      cur);
    if (inp === null) return;
    localStorage.setItem("bfm_api_key", inp.trim());
    alert(inp.trim()
      ? (ZH ? "已保存，刷新页面生效。\n\n本地模型会先过滤大部分内容、只把少数送云端，已分类内容还有本地缓存不再重复调用，因此用量通常很省。\n开关条上实时显示你的用量，「容忍」滑条可进一步降低（越高越省）。\n具体费用请以 DeepSeek 后台的实际用量与账单为准。"
            : "Saved. Reload the page to apply.\n\nThe local model filters most items first and only sends a few to the cloud; already-classified videos are cached and never re-sent, so usage stays low.\nLive usage is shown on the switch bar, and the tolerance slider can lower it further.\nActual charges follow your DeepSeek dashboard.")
      : (ZH ? "已清除 Key。本地小模型仍支撑「专业」模式主要功能，精选娱乐改用关键词规则。刷新页面生效。"
            : "Key removed. The built-in local model still powers Learn mode; finer modes fall back to keyword rules. Reload to apply."));
  };
  sw.appendChild(cfgBtn);
  // 连接码：填了才把浏览记录交给本机的兴趣程序，留空 = 这个功能完全不存在
  const imBtn = document.createElement("button");
  imBtn.textContent = "🔗";
  const IM_STATE_TEXT = {
    off:     [ "连接码（本机兴趣程序）：未启用。若本机兴趣程序在运行，由它发起连接即可，无需手填", "Connection code (local interest service): off. If the local service is running, let it initiate the connection — no manual entry needed" ],
    pending: [ "连接码（本机兴趣程序）：等待连接…", "Connection code: connecting…" ],
    ok:      [ "连接码（本机兴趣程序）：已连接", "Connection code: connected" ],
    bad:     [ "连接码（本机兴趣程序）：连接码不对，点此重填", "Connection code: rejected — click to re-enter" ],
    offline: [ "连接码（本机兴趣程序）：本机程序没在运行，记录已暂存", "Connection code: local service not running, events are queued" ],
  };
  function imRenderBtn(s) {
    const txt = IM_STATE_TEXT[s] || IM_STATE_TEXT.off;
    imBtn.title = ZH ? txt[0] : txt[1];
    imBtn.style.opacity = s === "ok" ? "1" : s === "off" ? "0.45" : "0.7";
    imBtn.style.filter = s === "bad" ? "grayscale(1)" : "";
  }
  imOnState.push(imRenderBtn);
  imRenderBtn(imState);
  imBtn.onclick = () => {
    const cur = localStorage.getItem("bfm_im_token") || "";
    const inp = prompt(ZH
      ? "粘贴本机兴趣程序的连接码（程序启动时会打印，也可以在 Breadcrumb 的发现页上复制）。\n\n" +
        "填好之后，脚本会把你在B站看到和点开的视频标题、UP主名、封面地址、观看时长，发到你自己电脑上的 127.0.0.1:21456，\n" +
        "用来整理你自己的兴趣。这些内容不出这台电脑，也不会发给任何网站。\n\n" +
        "留空并确定 = 关闭这个功能。"
      : "Paste the connection code of the interest service running on this computer (it prints one on startup).\n\n" +
        "Once set, this script sends titles, uploader names, cover urls and watch time of videos you see and open to 127.0.0.1:21456 on your own machine,\n" +
        "so it can build your own interest profile. Nothing leaves this computer and nothing is sent to any website.\n\n" +
        "Leave empty to turn this off.",
      cur);
    if (inp === null) return;
    localStorage.setItem("bfm_im_token", inp.trim());
    alert(inp.trim()
      ? (ZH ? "已保存，刷新页面生效。连接是否成功，看开关条上 🔗 的提示。"
            : "Saved. Reload to apply; hover 🔗 on the switch bar to see whether it connected.")
      : (ZH ? "已关闭，脚本不再把任何浏览记录发出去。刷新页面生效。"
            : "Turned off. The script no longer reports anything. Reload to apply."));
  };
  sw.appendChild(imBtn);
  document.body.appendChild(sw);

  // ---------- token 计量（纯观测，不干预请求）：逐请求累计 API 返回的 usage，精确值非估算 ----------
  // deepseek-v4-flash 价目（元/百万token，≈美元价×7.2）；高峰时段（UTC 1-4 与 6-10 点）价格×2
  const PRICE = { hit: 0.05, miss: 1.58, out: 4.75 };
  const priceFactor = () => { const h = new Date().getUTCHours(); return (h >= 1 && h < 4) || (h >= 6 && h < 10) ? 2 : 1; };
  const tok = load("bfm_tok", { in: 0, hit: 0, out: 0, req: 0, c: 0, day: "", dIn: 0, dHit: 0, dOut: 0, dC: 0 });
  const tokDayStr = () => { const t = new Date(); return t.getFullYear() + "-" + (t.getMonth() + 1) + "-" + t.getDate(); };
  const tokRoll = () => { const d = tokDayStr(); if (tok.day !== d) { tok.day = d; tok.dIn = tok.dHit = tok.dOut = 0; tok.dC = 0; } };
  const tokDayUsed = () => { tokRoll(); return tok.dIn + tok.dOut; };
  const fmtTok = (n) => ZH ? (n >= 1e8 ? (n / 1e8).toFixed(2) + "亿" : n >= 1e4 ? (n / 1e4).toFixed(1) + "万" : String(n)) : (n >= 1e6 ? (n / 1e6).toFixed(2) + "M" : n >= 1e3 ? (n / 1e3).toFixed(1) + "k" : String(n));
  function addUsage(u) {
    if (!u) return;
    tokRoll();
    const hit = u.prompt_cache_hit_tokens ?? (u.prompt_tokens_details && u.prompt_tokens_details.cached_tokens) ?? 0;
    const miss = (u.prompt_tokens || 0) - hit, out = u.completion_tokens || 0;
    const cost = (miss * PRICE.miss + hit * PRICE.hit + out * PRICE.out) * priceFactor() / 1e6; // 按当下峰谷时段计价
    tok.in += u.prompt_tokens || 0; tok.out += out; tok.hit += hit; tok.req++;
    tok.c = (tok.c || 0) + cost;
    tok.dIn += u.prompt_tokens || 0; tok.dOut += out; tok.dHit += hit;
    tok.dC = (tok.dC || 0) + cost;
    localStorage.setItem("bfm_tok", JSON.stringify(tok));
    tokRender();
  }
  const tokChip = document.createElement("span");
  tokChip.id = "bfm-tok";
  function tokRender() {
    tokRoll();
    tokChip.textContent = (ZH ? "今日" : "Today ") + fmtTok(tokDayUsed()) + "tok";
    tokChip.title = ZH
      ? "本站 LLM 用量（逐请求累计 API 返回的 usage）\n" +
        "今日：输入 " + fmtTok(tok.dIn) + "（缓存命中 " + fmtTok(tok.dHit) + "）+ 输出 " + fmtTok(tok.dOut) +
        " ≈ ¥" + (tok.dC || 0).toFixed(3) + "\n" +
        "累计：" + fmtTok(tok.in + tok.out) + " tok / " + tok.req + " 次请求 ≈ ¥" + (tok.c || 0).toFixed(2) + "\n" +
        "本地模型先过滤、缓存不重复调用，用量通常很省；具体费用以 DeepSeek 后台账单为准"
      : "LLM usage on this site (exact, from API-reported usage)\n" +
        "Today: in " + fmtTok(tok.dIn) + " (cache hit " + fmtTok(tok.dHit) + ") + out " + fmtTok(tok.dOut) +
        " ≈ ¥" + (tok.dC || 0).toFixed(3) + "\n" +
        "Total: " + fmtTok(tok.in + tok.out) + " tok / " + tok.req + " requests ≈ ¥" + (tok.c || 0).toFixed(2) + "\n" +
        "The local model filters first and cached items are never re-sent; actual charges follow your DeepSeek dashboard";
  }
  if (API_KEY) { sw.appendChild(tokChip); tokRender(); }

  let booted = false; // 脚本尾部初始化完成后才允许 setMode 触发补货
  function setMode(m) {
    mode = m;
    localStorage.setItem(LS.mode, m);
    document.documentElement.dataset.bfmMode = m;
    sw.querySelectorAll("button").forEach(b => b.classList.toggle("on", b.dataset.m === m));
    if (booted && m !== "all") { ensurePool(); maybeInject(); }
  }
  setMode(mode);

  const stats = { llmReq: 0, classified: 0, stage2: 0, tagReq: 0, feedPages: 0, biliReq: 0 };

  // ---------- B站请求全局节流：所有后台 API 调用串行化 + 随机间隔 + 限流指数退避 ----------
  // 命中限流/风控错误码后：1→2→4→8→16 分钟退避，期间所有预取暂停（页面上已有内容不受影响）
  // 注意 62013 不在此列：它是分区 feed 的"暂无更多内容"（供给耗尽），不是限流，单独处理
  const RATE_CODES = new Set([-412, -799, -352]);
  let biliQueue = Promise.resolve();
  let biliBackoffUntil = 0, biliBackoffLevel = 0;
  function biliFetch(url) {
    const run = async () => {
      if (Date.now() < biliBackoffUntil) throw new Error("bili-cooldown");
      await new Promise(r => setTimeout(r, 150 + Math.random() * 250)); // 请求间随机间隔
      stats.biliReq++;
      const d = await (await fetch(url, { credentials: "include" })).json();
      if (RATE_CODES.has(d.code)) {
        biliBackoffLevel = Math.min(biliBackoffLevel + 1, 5);
        biliBackoffUntil = Date.now() + 60000 * Math.pow(2, biliBackoffLevel - 1);
        stats.biliLimited = (stats.biliLimited || 0) + 1;
        stats.lastLimitCode = d.code;
        console.warn("[bfm] B站接口限流(code " + d.code + ")，退避 " + Math.pow(2, biliBackoffLevel - 1) + " 分钟");
        throw new Error("bili-rate-limited:" + d.code);
      }
      if (d.code === 0) biliBackoffLevel = 0; // 成功即重置退避等级
      return d;
    };
    const p = biliQueue.then(run, run);
    biliQueue = p.catch(() => {});
    return p;
  }

  // ---------- 标签获取（给 LLM 提供更多信号，失败不阻塞） ----------
  async function fetchTags(bvid) {
    stats.tagReq++;
    try {
      const d = await biliFetch("https://api.bilibili.com/x/tag/archive/tags?bvid=" + bvid);
      return d.code === 0 ? d.data.map(t => t.tag_name).slice(0, 8) : [];
    } catch { return []; }
  }

  // ---------- 关键词兜底分类（无 key 或 LLM 失败时用） ----------
  const PRO_KW = ["知识","科普","科学","物理","数学","财经","经济","金融","投资","宏观","研报","编程","代码","开发","算法","AI","人工智能","大模型","芯片","半导体","科技","技术","教程","课程","考研","历史","人文","哲学","法律","心理学","纪录片","深度","解读","分析","美债","国债","利率","通胀","关税","汇率","央行","GDP","政策"];
  const ENT_KW = ["游戏","电竞","电子竞技","英雄联盟","原神","搞笑","沙雕","整活","鬼畜","动画","动漫","番剧","vlog","日常","美食","吃播","旅行","宠物","猫","狗","音乐","翻唱","舞蹈","明星","综艺","八卦","影视","剪辑","电影","电视剧","解说","恋爱","情侣","男朋友","女朋友","挑战","整蛊","直播","切片","主播","vtuber","体育","足球","篮球","NBA","娱乐","MOBA","攻略","实况","吐槽","抱怨"];
  const JUNK_KW = ["私信","领取","资料","训练营","报名","学员","变现","副业","兼职","月入","躺赚","风口","红利","涨粉","起号","自媒体运营","知识付费","陪跑","逆袭","破局","搞钱","项目拆解","免费送","限时"];
  function kwClassify(title, owner, tags) {
    const tagText = tags.join(" ");
    const titleText = title + " " + owner;
    const score = (kws) => {
      let s = 0;
      for (const kw of kws) { if (tagText.includes(kw)) s += 2; if (titleText.includes(kw)) s += 1; }
      return s;
    };
    const j = score(JUNK_KW), p = score(PRO_KW), e = score(ENT_KW);
    if (j >= 2 && j >= p) return "junk";
    return p > e ? "pro" : e > p ? "ent" : "unk";
  }

  // ---------- LLM 批量分类 ----------
  let batch = [];       // {bvid, title, owner, tags, resolve}
  let batchTimer = null;
  function enqueueLLM(item) {
    return new Promise((resolve) => {
      batch.push({ ...item, resolve });
      if (batch.length >= BATCH_SIZE) flushBatch();
      else if (!batchTimer) batchTimer = setTimeout(flushBatch, BATCH_WAIT_MS);
    });
  }
  let llmFailStreak = 0, llmCooldownUntil = 0; // 连续失败熔断：60秒内不再发请求，直接走关键词兜底
  async function flushBatch() {
    clearTimeout(batchTimer); batchTimer = null;
    const items = batch.splice(0);
    if (!items.length) return;
    if (Date.now() < llmCooldownUntil) { for (const it of items) it.resolve(null); return; }
    // 行式紧凑输入：序号|标题|UP主|标签。不发 id（BV 号本身要吃 8~10 个 token 且要被回显）
    const clean = (s) => String(s || "").replace(/[|\n]/g, " ").trim();
    const payload = items.map((it, i) =>
      (i + 1) + "|" + clean(it.title).slice(0, 80) + "|" + clean(it.owner) + "|" + (it.tags || []).map(clean).join(",")
    ).join("\n");
    // 兼容模型偶发输出全称或数组格式
    const CODE = { p: "pro", g: "good", e: "ent", j: "junk", "?": "?", pro: "pro", good: "good", ent: "ent", junk: "junk" };
    let map = null;
    for (let attempt = 0; attempt < 2 && !map; attempt++) { // 失败重试一次（可能是偶发限流）
      stats.llmReq++;
      try {
        const r = await fetch(API_URL, {
          method: "POST",
          headers: { "content-type": "application/json", "authorization": "Bearer " + API_KEY },
          body: JSON.stringify({
            model: MODEL,
            // v4-flash 默认开思考模式，reasoning token 按输出计费，分类任务必须显式关闭
            ...(MODEL.startsWith("deepseek") ? { thinking: { type: "disabled" } } : {}),
            max_tokens: 500,
            response_format: { type: "json_object" },
            messages: [
              { role: "system", content: SYSTEM_PROMPT },
              { role: "user", content: payload },
            ],
          }),
        });
        const d = await r.json();
        addUsage(d.usage); // 精确计量：直接累计 API 返回的 usage
        if (!d.choices) throw new Error("api error: " + JSON.stringify(d).slice(0, 120));
        const out = JSON.parse(d.choices[0].message.content);
        const raw = out.r ?? out;
        const entries = Array.isArray(raw)
          ? raw.map((v, i) => [i, v])
          : Object.entries(raw || {}).map(([k, v]) => [parseInt(k, 10) - 1, v]);
        map = {};
        for (const [idx, v] of entries) {
          const c = CODE[String(v && v.c !== undefined ? v.c : v).trim()];
          if (Number.isInteger(idx) && idx >= 0 && idx < items.length && c) map[items[idx].bvid] = c;
        }
      } catch (e) {
        stats.llmFail = (stats.llmFail || 0) + 1;
        stats.lastErr = String(e).slice(0, 160);
        console.warn("[bfm] LLM 分类失败(第" + (attempt + 1) + "次):", e);
        if (attempt === 0) await new Promise(res => setTimeout(res, 2500));
      }
    }
    if (map) llmFailStreak = 0;
    else if (++llmFailStreak >= 2) {
      llmCooldownUntil = Date.now() + 60000;
      console.warn("[bfm] LLM 连续失败，熔断 60 秒");
    }
    for (const it of items) it.resolve(map ? (map[it.bvid] || null) : null);
  }

  // 三层分类：① 本地学生模型（离线免费）② LLM 复核本地判正/按容忍度抽查判负 ③ 关键词兜底
  async function classify(id, title, owner, presetTags) {
    if (upRule[owner]) return upRule[owner];
    if (cache[id]) return cache[id];
    const lp = fmProb(title, owner); // 本地"专业"概率，微秒级
    let tags = presetTags || [];
    if (!API_KEY || ROUTE.off) {
      // 纯本地模式（无 Key 或滑条拉到头）：置信度足够才判，不足的丢弃不展示。
      // 阈值取自外折实测（研究 E24）：接受≥0.70 时展示精度 0.71，硬切 0.5 只有 0.55
      if (lp >= 0.70) return "pro";
      if (lp > 0.30) return "unk"; // 置信度不足：丢弃（过滤模式下不显示），供给无限不心疼
      const kw = kwClassify(title, owner, tags);
      return kw === "pro" ? "ent" : kw;
    }
    // 分流路由（研究 E8/E9：token 降至全量送审的 ~1/5）：只在 专业/全部 模式下生效，
    // 精选娱乐需要 good/ent 细分仍走 LLM。本地高置信判断直接采用且不落缓存，其他模式下可被 LLM 重判。
    if (mode === "pro" || mode === "all") {
      if (lp < ROUTE.low && Math.random() >= ROUTE.audit) { stats.localSkip = (stats.localSkip || 0) + 1; return "ent"; }
      if (lp >= ROUTE.high) { stats.localPass = (stats.localPass || 0) + 1; return "pro"; }
    }
    let cls = await enqueueLLM({ bvid: id, title, owner, tags });
    if (cls === "?") {
      stats.stage2++;
      if (id.startsWith("BV")) {
        tags = await fetchTags(id);
        cls = await enqueueLLM({ bvid: id, title, owner, tags });
      }
      if (cls === "?") cls = null;
    }
    stats.classified++;
    if (cls) fmLearn(title, owner, cls === "pro" ? 1 : 0); // 端上自适应：只学 LLM 确认过的标签
    if (!cls) cls = kwClassify(title, owner, tags); // LLM 失败时兜底
    if (cls !== "unk") { cache[id] = cls; save(); }
    return cls;
  }

  // ---------- 卡片处理 ----------
  // 某分类在某模式下是否该显示
  const matchMode = (cls, m) => m === "gent" ? cls === "good" : m === "ent" ? (cls === "ent" || cls === "good") : cls === m;
  let inflight = 0;
  const queue = [];
  // 并发上限必须 ≥ LLM 批量大小：每个任务都在等同一次批量请求返回，上限过低会把实际批量压小、吞吐骤降。
  // 对B站接口的保护由 biliFetch 全局串行节流承担，这里放开无风险
  function pump() {
    while (inflight < 48 && queue.length) { inflight++; queue.shift()().finally(() => { inflight--; pump(); }); }
  }

  // 注意嵌套层级 .feed-card > .bili-feed-card > .bili-video-card，必须隐藏最外层才能让网格补位
  const wrapOf = (card) => card.closest(".feed-card") || card.closest(".bili-feed-card") || card;

  function setCls(card, cls) {
    wrapOf(card).dataset.bfm = cls;
  }

  function processCard(card) {
    if (card.dataset.bfmSeen) return;
    if (card.closest(".recommended-swipe")) return; // 顶部轮播跳过
    if (card.querySelector('a[href*="cm.bilibili.com"]')) { // 广告卡
      wrapOf(card).dataset.bfm = "ad";
      card.dataset.bfmSeen = "1";
      return;
    }
    const link = card.querySelector('a[href*="video/BV"]');
    const bvid = link && (link.href.match(/BV[0-9A-Za-z]{10}/) || [])[0];
    if (!bvid) return; // 尚未加载完成，等下一轮扫描
    card.dataset.bfmSeen = "1";
    if (shownBvids.has(bvid)) { // 缓冲池已经注入过这个视频，原生卡片按重复隐藏
      wrapOf(card).dataset.bfm = "dup";
      return;
    }
    shownBvids.add(bvid);
    const t = card.querySelector(".bili-video-card__info--tit");
    const title = (t && (t.getAttribute("title") || t.textContent) || "").trim();
    const o = card.querySelector(".bili-video-card__info--author, .bili-video-card__info--owner");
    const owner = (o && o.textContent.trim().split("\n")[0].replace(/\s*·.*$/, "")) || "";
    imReport({ type: "expose", id: bvid, t: title, u: owner, pic: imCover(card), dwell: 0, dur: 0 });
    if (!wrapOf(card).dataset.bfm) wrapOf(card).dataset.bfm = "pending"; // 分类完成前先藏起来
    queue.push(async () => {
      try { setCls(card, await classify(bvid, title, owner), bvid, owner); }
      catch (e) { setCls(card, "unk", bvid, owner); } // 出错也要放行，不能永远隐藏
    });
    pump();
  }

  // ---------- 特殊卡片：直播 / 番剧 / 国创 / 综艺 / 影视 / 漫画 / 课堂 ----------
  // 这些卡片自带类型标签，直接按类型映射；直播内容差异大（可能是技术直播），单独走 LLM
  // 课堂是B站自营付费内容的推广位，归入 "ad"（任何模式下都显示，不参与过滤）
  const FLOOR_MAP = { "番剧": "good", "国创": "good", "电影": "good", "综艺": "ent", "电视剧": "ent", "漫画": "ent", "纪录片": "pro", "课堂": "ad" };
  function processSpecial(el) {
    if (el.dataset.bfmSeen) return;
    const a = el.querySelector("a[href]");
    if (!a) return; // 骨架屏，等下一轮
    el.dataset.bfmSeen = "1";
    const href = a.getAttribute("href") || "";
    const liveId = (href.match(/live\.bilibili\.com\/(\d+)/) || [])[1];
    if (liveId) {
      const lines = el.innerText.trim().split("\n").map(s => s.trim()).filter(Boolean);
      const title = lines.filter(s => !["直播", "直播中"].includes(s)).slice(0, 3).join(" ");
      const owner = lines[lines.length - 1] || "";
      if (!wrapOf(el).dataset.bfm) wrapOf(el).dataset.bfm = "pending";
      queue.push(async () => {
        try { setCls(el, await classify("live:" + liveId, "【直播】" + title, owner, []), "live:" + liveId, owner); }
        catch (e) { setCls(el, "unk", "live:" + liveId, owner); }
      });
      pump();
      return;
    }
    const label = (el.querySelector(".floor-title") || {}).innerText || el.innerText.trim().split("\n")[0];
    const cls = FLOOR_MAP[label.trim()] || "ent";
    if (cls === "ad") { el.dataset.bfm = "ad"; return; } // 商业推广位：不打角标、不过滤
    setCls(el, cls, "floor:" + href.slice(0, 40), "");
  }

  function scan() {
    document.querySelectorAll(".bili-video-card").forEach(processCard);
    document.querySelectorAll(".floor-single-card, .bili-live-card").forEach(processSpecial);
  }

  // ---------- 缓冲池：后台预取推荐流并提前分类，过滤模式下补充卡片 ----------
  // 时效性：条目只存内存、15 分钟过期；每次预取都实时调 B 站推荐接口（和刷新首页同源）
  const POOL_MIN = 20;                 // 当前模式的存货低于此值就去预取
  const POOL_TARGET = 40;              // 一直补到这个数
  const POOL_TTL_MS = 15 * 60 * 1000;  // 池内条目超时丢弃
  const shownBvids = new Set();
  let freshIdx = 20 + Math.floor(Math.random() * 80);
  let fetching = false;

  // 池子持久化：刷新页面不丢已分类的存货；TTL 照常生效，保证时效性
  let pool = [];                       // {item, cls, ts}
  try {
    const saved = JSON.parse(sessionStorage.getItem("bfm_pool") || "{}");
    if (saved.pool) pool = saved.pool.filter(p => Date.now() - p.ts < POOL_TTL_MS);
    (saved.shown || []).slice(-2000).forEach(b => shownBvids.add(b));
    if (saved.freshIdx) freshIdx = saved.freshIdx;
  } catch (e) {}
  let poolSaveTimer = null;
  function persistPool() {
    clearTimeout(poolSaveTimer);
    poolSaveTimer = setTimeout(() => {
      try {
        sessionStorage.setItem("bfm_pool", JSON.stringify({
          pool: pool.slice(-240),
          shown: [...shownBvids].slice(-2000), freshIdx,
        }));
      } catch (e) {}
    }, 1000);
  }

  const poolCountFor = (m) => pool.filter(p => matchMode(p.cls, m) && Date.now() - p.ts < POOL_TTL_MS).length;

  async function fetchFeedPage() {
    stats.feedPages++;
    freshIdx++;
    const u = "https://api.bilibili.com/x/web-interface/wbi/index/top/feed/rcmd?ps=30&fresh_type=4&fresh_idx=" + freshIdx + "&fresh_idx_1h=" + freshIdx + "&brush=" + freshIdx;
    const d = await biliFetch(u); // 限流时抛异常 → ensurePool 进入冷却
    return d.code === 0 ? (d.data.item || []).filter(it => it.goto === "av" && it.bvid) : [];
  }

  let poolCooldownUntil = 0;
  async function ensurePool(force) {
    if (fetching || mode === "all") return;
    if (!force && Date.now() < poolCooldownUntil) return;
    fetching = true;
    try {
      // 每轮抓 4 页 × 30 条，最多 4 轮；本地模型先筛，LLM 只看少数
      for (let round = 0; round < 4 && poolCountFor(mode) < POOL_TARGET; round++) {
        const pages = await Promise.all([fetchFeedPage(), fetchFeedPage(), fetchFeedPage(), fetchFeedPage()]);
        const seen = new Set(pool.map(p => p.item.bvid));
        const items = [];
        for (const it of pages.flat()) {
          if (shownBvids.has(it.bvid) || seen.has(it.bvid)) continue;
          seen.add(it.bvid);
          items.push(it);
        }
        await Promise.all(items.map(async (it) => {
          try {
            const cls = await classify(it.bvid, it.title, it.owner ? it.owner.name : "");
            if (cls && cls !== "unk") pool.push({ item: it, cls, ts: Date.now() });
          } catch (e) {}
        }));
        if (pool.length > 240) pool.splice(0, pool.length - 240);
        persistPool();
        if (poolCountFor(mode) < POOL_TARGET) await new Promise(r => setTimeout(r, 400)); // 轮间冷却
      }
    } catch (e) {
      if (!String(e).includes("bili-cooldown")) console.warn("[bfm] 预取失败", e);
    }
    // 抓了 9 页还没凑够（推荐流里该类内容少），歇 30 秒；若处于限流退避则对齐退避时间
    if (poolCountFor(mode) < POOL_MIN) poolCooldownUntil = Math.max(Date.now() + 30000, biliBackoffUntil);
    fetching = false;
  }

  // 容忍度滑条：控制「多花 token 换更准」还是「更依赖本地模型更省」（设置 Key 后显示）
  const tolUI = document.createElement("div");
  tolUI.id = "bfm-tol";
  tolUI.title = ZH ? "分类容忍度：越低 → 越多内容送大模型复核，更准但更费；越高 → 越依赖本地小模型，几乎免费但可能出现少量错分或漏内容。右侧数字为预计送大模型的比例。" : "Tolerance: lower sends more items to the cloud model (more accurate, costs more); higher relies on the free local model (a few misclassifications possible). The number shows the estimated share sent to the cloud.";
  tolUI.innerHTML = '<span>' + (ZH ? "容忍" : "Tol") + '</span><input type="range" min="0" max="100" step="10"><b></b>';
  if (API_KEY) sw.appendChild(tolUI);
  const tolInput = tolUI.querySelector("input"), tolLabel = tolUI.querySelector("b");
  const tolRender = () => { tolLabel.textContent = "AI" + Math.round(fmShareEst() * 100) + "%"; };
  tolInput.value = tol;
  tolRender();
  tolInput.oninput = () => {
    tol = Number(tolInput.value);
    localStorage.setItem("bfm_tol", String(tol));
    applyTol();
    tolRender();
  };

  // 克隆一张真实卡片当模板，保证注入卡片样式和原生一致
  let template = null;
  function captureTemplate() {
    if (template) return template;
    for (const fc of document.querySelectorAll(".feed-card")) {
      if (fc.querySelector('a[href*="video/BV"]') && fc.querySelector("img") && fc.querySelector(".bili-video-card__info--tit")) {
        // 用内层 .bili-feed-card 当模板根：B站的 CSS 会按 nth-child 隐藏多余的 .feed-card，
        // 而无限滚动加载的卡片正是以 .bili-feed-card 直接作为网格子元素
        template = (fc.querySelector(".bili-feed-card") || fc).cloneNode(true);
        template.querySelectorAll("[data-bfm], [data-bfm-seen]").forEach(e => { delete e.dataset.bfm; delete e.dataset.bfmSeen; });
        delete template.dataset.bfm;
        break;
      }
    }
    return template;
  }

  const fmtNum = n => n >= 1e8 ? (n / 1e8).toFixed(1) + "亿" : n >= 1e4 ? (n / 1e4).toFixed(1) + "万" : String(n ?? "");
  const fmtDur = s => Math.floor(s / 60) + ":" + String(s % 60).padStart(2, "0");

  function buildCard(p) {
    const el = captureTemplate().cloneNode(true);
    const it = p.item;
    const owner = it.owner ? it.owner.name : "";
    el.querySelectorAll("a").forEach(a => { a.setAttribute("href", "https://www.bilibili.com/video/" + it.bvid + "/"); a.setAttribute("target", "_blank"); });
    el.querySelectorAll("picture source").forEach(s => s.remove()); // source 优先级高于 img src，必须清掉
    const img = el.querySelector("img");
    if (img) {
      img.removeAttribute("srcset"); img.removeAttribute("data-src");
      img.src = (it.pic || "").replace(/^http:/, "https:") + "@672w_378h_1c_!web-home-common-cover";
      img.alt = it.title;
    }
    const tit = el.querySelector(".bili-video-card__info--tit");
    if (tit) { tit.setAttribute("title", it.title); (tit.querySelector("a") || tit).textContent = it.title; }
    const au = el.querySelector(".bili-video-card__info--author");
    if (au) au.textContent = owner;
    const date = el.querySelector(".bili-video-card__info--date");
    if (date && it.pubdate) { const d = new Date(it.pubdate * 1000); date.textContent = " · " + (d.getMonth() + 1) + "-" + String(d.getDate()).padStart(2, "0"); }
    const sv = el.querySelectorAll(".bili-video-card__stats--item");
    if (sv[0] && it.stat) (sv[0].querySelector("span:last-child") || sv[0]).textContent = fmtNum(it.stat.view);
    if (sv[1] && it.stat) (sv[1].querySelector("span:last-child") || sv[1]).textContent = fmtNum(it.stat.danmaku);
    const dur = el.querySelector(".bili-video-card__stats__duration");
    if (dur) dur.textContent = fmtDur(it.duration || 0);
    const icon = el.querySelector(".bili-video-card__info--icon-text");
    if (icon) icon.remove(); // 去掉克隆来的"已关注"等角标
    el.dataset.bfm = p.cls;
    el.dataset.bfmInjected = "1";
    const card = el.querySelector(".bili-video-card") || el;
    card.dataset.bfmSeen = "1";
    return el;
  }

  function injectFromPool(n) {
    if (mode === "all") return;
    const cont = document.querySelector(".container.is-version8");
    if (!cont || !captureTemplate()) return;
    const now = Date.now();
    for (let i = pool.length - 1; i >= 0; i--) if (now - pool[i].ts > POOL_TTL_MS) pool.splice(i, 1);
    const pickOne = (arr) => {
      for (let i = 0; i < arr.length; i++) {
        if (matchMode(arr[i].cls, mode) && !shownBvids.has(arr[i].item.bvid)) return arr.splice(i, 1)[0];
      }
      return null;
    };
    const picks = [];
    for (let k = 0; k < n; k++) {
      const p = pickOne(pool);
      if (!p) break;
      picks.push(p);
    }
    for (const p of picks) {
      shownBvids.add(p.item.bvid);
      const el = buildCard(p);
      cont.appendChild(el); // 只追加到末尾，绝不插入中间
    }
    if (picks.length) persistPool();
    if (poolCountFor(mode) < POOL_MIN) ensurePool(true); // 用户在消耗，强制补货
  }

  function maybeInject() {
    if (mode === "all") return;
    const cont = document.querySelector(".container.is-version8");
    // 接管模式下屏幕内容全靠注入卡片：可见数不足或接近底部都触发补充
    const visInjected = cont ? [...cont.querySelectorAll("[data-bfm-injected]")].filter(e => e.offsetHeight > 0).length : 0;
    const remaining = document.documentElement.scrollHeight - window.scrollY - innerHeight;
    if (remaining < 3200 || visInjected < 15) injectFromPool(10);
  }
  let lastScrollInject = 0;
  window.addEventListener("scroll", () => { // 节流：真实滚轮每秒可触发数十次事件
    const now = Date.now();
    if (now - lastScrollInject > 250) { lastScrollInject = now; maybeInject(); }
  }, { passive: true });
  setInterval(() => {
    if (mode === "all") return;
    // 后台标签页只做保底维持（低于最低水位才补），不做囤货，减少无人观看时的请求量
    if (document.hidden && poolCountFor(mode) >= POOL_MIN) return;
    ensurePool(); maybeInject();
  }, 3000);
  booted = true;
  if (mode !== "all") { ensurePool(); maybeInject(); }
  window.__bfm = { get imState() { return imState; }, get imQueued() { return imQueue.length; }, get imSent() { return imSent; }, get pool() { return pool; }, shownBvids, cache, upRule, ensurePool, injectFromPool, stats, fmProb, ROUTE,
    get delta() { return fmDelta; },
    get backoff() { return { biliBackoffUntil, biliBackoffLevel, llmCooldownUntil, llmFailStreak, poolCooldownUntil }; } }; // 调试用
  scan();
  // DOM 变更合并调度：突发变更风暴下最多 300ms 扫一次
  let scanScheduled = false;
  const scheduleScan = () => {
    if (scanScheduled) return;
    scanScheduled = true;
    setTimeout(() => { scanScheduled = false; scan(); }, 300);
  };
  new MutationObserver(scheduleScan).observe(document.body, { childList: true, subtree: true });
  setInterval(scan, 3000); // 兜底：懒加载卡片链接就位后补扫
})();
