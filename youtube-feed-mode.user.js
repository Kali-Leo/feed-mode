// ==UserScript==
// @name         YouTube Feed Mode: Learn / Feel-good / Fun
// @name:zh-CN   YouTube 首页 娱乐/专业 模式切换
// @namespace    leo.youtube.feedmode
// @version      2.0.2
// @description  Filter your YouTube home feed into Learn / Feel-good / Fun with one click. A built-in local AI model works offline out of the box — no API key needed. Add a DeepSeek key for cloud review and higher accuracy; usage and cost are shown live and a tolerance slider controls how much goes to the cloud. Free forever, never handles your money. Does not block ads. Unofficial tool, not affiliated with YouTube/Google.
// @description:zh-CN  内置本地 AI 小模型 + 大模型复核，把 YouTube 首页推荐流分为「专业/精选娱乐/娱乐」，左下角开关一键切换。不填 API Key 也能用（本地模型离线分类）；填入 DeepSeek Key 后由大模型复核提升精度（用量实时显示，「容忍」滑条可控制用量，费用由你在 DeepSeek 后台自理）。本项目完全免费。不屏蔽任何广告与商业内容。非官方工具，与 YouTube/Google 无关联。
// @match        https://www.youtube.com/*
// @grant        none
// @run-at       document-idle
// @license      GPL-3.0
// @homepageURL  https://github.com/Kali-Leo/feed-mode
// @supportURL   https://github.com/Kali-Leo/feed-mode/issues
// ==/UserScript==
// 本脚本为非官方社区工具。设计原则：不屏蔽广告、不劫持流量、不调用任何非页面自身的站内接口
// （纯 DOM 过滤，补货完全依赖 YouTube 自己的无限滚动）。仅在首页生效。

(function () {
  "use strict";
  if (window.__yfm) return; // 防止重复注入

  const ZH = (navigator.language || "").toLowerCase().startsWith("zh"); // 界面语言跟随浏览器

  // ================= 个人兴趣模型回传（默认关闭） =================
  // 只有在开关条的 🔗 里填了连接码，下面这些才会做事；没填时全部空转，脚本行为与不带此功能时一致。
  // 目标固定为本机 127.0.0.1 的兴趣服务（interest-model/daemon），发的是标题、频道名、视频 id、
  // 封面地址、观看时长；不发 Cookie、不发账号、不发任何身份信息，也不发往本机以外的任何地方。
  const IM_URL = "http://127.0.0.1:21456/events";
  const IM_TOKEN = (localStorage.getItem("yfm_im_token") || "").trim();
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
    ev.site = "youtube";
    ev.ts = Date.now() / 1000;
    imQueue.push(ev);
    if (!imTimer) imTimer = setTimeout(imFlush, 5000);
  }
  const imCover = (id) => "https://i.ytimg.com/vi/" + id + "/hqdefault.jpg";

  // 观看时长：YouTube 是单页应用，切走一个视频就结算一次
  if (IM_TOKEN) {
    let watching = null;
    const watchedId = () =>
      location.pathname === "/watch" ? new URLSearchParams(location.search).get("v") : null;
    const tick = () => {
      if (!watching) return;
      const now = Date.now();
      if (watching.counting) watching.watched += (now - watching.lastTick) / 1000;
      watching.lastTick = now;
    };
    const settle = () => {
      tick();
      if (watching && watching.watched >= 5) {
        const v = document.querySelector("video");
        imReport({
          type: "watch", id: watching.id, t: watching.title, u: watching.up,
          pic: imCover(watching.id), dwell: Math.round(watching.watched),
          dur: v && v.duration ? Math.round(v.duration) : 0,
        });
        imFlush();
      }
      watching = null;
    };
    const sync = () => {
      const id = watchedId();
      if (watching && watching.id !== id) settle();
      if (id && !watching) {
        watching = { id, watched: 0, lastTick: Date.now(), counting: !document.hidden, title: "", up: "" };
      }
      if (!watching) return;
      tick();
      const h1 = document.querySelector("h1.ytd-watch-metadata, h1.title");
      const ch = document.querySelector("#owner #channel-name a, ytd-channel-name a");
      if (h1 && h1.textContent.trim()) watching.title = h1.textContent.trim();
      if (ch && ch.textContent.trim()) watching.up = ch.textContent.trim();
    };
    setInterval(sync, 5000);
    document.addEventListener("yt-navigate-finish", () => setTimeout(sync, 800));
    document.addEventListener("visibilitychange", () => {
      tick();
      if (watching) watching.counting = !document.hidden;
    });
    window.addEventListener("pagehide", settle);
    sync();
  }

  // 首页上点开一个视频，记一次「选择」（曝光在卡片处理里记）
  document.addEventListener("click", (e) => {
    if (!IM_TOKEN || !e.target.closest) return;
    const a = e.target.closest('a[href*="watch?v="]');
    if (!a) return;
    const id = ((a.getAttribute("href") || "").match(/watch\?v=([\w-]{6,})/) || [])[1];
    if (!id) return;
    const card = a.closest("ytd-rich-item-renderer") || a;
    const h3 = card.querySelector("h3");
    const ch = card.querySelector('a[href^="/@"], ytd-channel-name a');
    imReport({
      type: "click", id,
      t: ((h3 && h3.textContent) || a.getAttribute("title") || "").trim(),
      u: ((ch && ch.textContent) || "").trim(),
      pic: imCover(id), dwell: 0, dur: 0,
    });
  }, true);

  // ================= 配置 =================
  // API Key 通过左下角开关条上的 ⚙ 设置，仅存于你浏览器的 localStorage（youtube.com 域下）
  const API_KEY = (localStorage.getItem("yfm_api_key") || "").trim();
  const API_URL = localStorage.getItem("yfm_api_url") || "https://api.deepseek.com/chat/completions";
  const MODEL = localStorage.getItem("yfm_model") || "deepseek-v4-flash"; // 旧名 deepseek-chat 已于 2026-07 退役
  const BATCH_SIZE = 40; // 批量越大，system prompt 摊得越薄
  const BATCH_WAIT_MS = 300;
  // ========================================

  // 提示词与输入输出格式均为省 token 设计：输入用行式紧凑格式（不发 id），
  // 输出用「序号→单字母」映射（输出 token 单价更高，压缩收益最大）
  const SYSTEM_PROMPT = `你是视频分类器。输入为列表，每行一个 YouTube 视频（可能是任何语言），格式：序号|标题|频道名。把每个视频分为四类之一：
- p（专业）：有信息密度、看完能学到真东西的内容——硬核知识科普、技术/编程/工程、财经与宏观分析、学术、深度纪录片、严肃行业解读、高质量教学，且情绪基调冷静克制、有建设性（看完是"搞懂了"而不是"更焦虑了"）。贩卖焦虑、渲染恐慌灾难、煽动对立、末日论调、阴谋论、"要崩盘/要完蛋"式情绪化标题党分析，即使话题专业也不算 p：归 e，含营销引流归 j。宁缺毋滥。
- g（精选娱乐）：看完心情变好（愉悦、感动或惊叹）的娱乐——治愈、温暖、纯粹的欢笑、才华与匠心（高水平创作、音乐、手艺、动画）、萌宠自然、美食美景、真诚的生活记录、高质量游戏/影视。
- e（普通娱乐）：其他娱乐，尤其是制造对立/引战的话题、蹭热点骂战、猎奇审丑、擦边、狗血冲突、贩卖愤怒或焦虑的内容、无营养的快餐剪辑、标题党 clickbait。g 和 e 之间拿不准归 e（精选宁缺毋滥）。
- j（营销水）：营销号、卖课/引流、贩卖焦虑的成功学、软广。

若仅凭标题和频道名确实无法判断，该行可给 "?"。
输出 JSON：{"r":{"1":"p","2":"e",...}}，键为每行序号，值为 p/g/e/j/?，覆盖所有行，不要输出其他内容。`;

  const load = (k, d) => { try { return JSON.parse(localStorage.getItem(k)) ?? d; } catch { return d; } };
  const cache = load("yfm_cache", {});   // videoId -> 分类
  if (localStorage.getItem("yfm_cache_v") !== "2") { // v2 专业模式加入情绪门槛：旧的 pro 按新标准重判
    for (const k of Object.keys(cache)) if (cache[k] === "pro") delete cache[k];
    localStorage.setItem("yfm_cache_v", "2");
  }
  const upRule = load("yfm_up", {});     // 频道名 -> 分类（预留）
  if (Object.keys(cache).length > 5000) { for (const k of Object.keys(cache).slice(0, 2500)) delete cache[k]; }
  let saveTimer = null;
  const save = () => {
    clearTimeout(saveTimer);
    saveTimer = setTimeout(() => {
      localStorage.setItem("yfm_cache", JSON.stringify(cache));
      localStorage.setItem("yfm_up", JSON.stringify(upRule));
    }, 800);
  };

  // ================= 本地学生模型（多语言标题；无 Key 也可用；训练记录见仓库 research/ E20） =================
  const FM_CFG = { dims: 16384, ngLo: 2, ngHi: 4, scale: 0.04090379923582077, bias: 0.7546152220603145 };
  const FM_B64 = "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";
  const FM_W = (() => { const bin = atob(FM_B64); const w = new Int8Array(bin.length); for (let i = 0; i < bin.length; i++) w[i] = (bin.charCodeAt(i) << 24) >> 24; return w; })();
  function fmHash(bytes) { // murmurhash3_32 (x86, seed=0)，与训练侧 sklearn 一致
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
    const chars = Array.from(s);
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
  const fmDelta = load("yfm_delta", {});
  let fmDeltaTimer = null;
  const fmDeltaSave = () => { clearTimeout(fmDeltaTimer); fmDeltaTimer = setTimeout(() => { try { localStorage.setItem("yfm_delta", JSON.stringify(fmDelta)); } catch (e) {} }, 2000); };
  function fmScore(counts, norm) {
    let s = 0, ds = 0;
    for (const [idx, c] of counts) { s += FM_W[idx] * c; const d = fmDelta[idx]; if (d) ds += d * c; }
    return (s * FM_CFG.scale) / norm + FM_CFG.bias + ds / norm;
  }
  function fmProb(title, up) {
    const { counts, norm } = fmFeatures(title, up);
    return 1 / (1 + Math.exp(-fmScore(counts, norm)));
  }
  function fmLearn(title, up, y) { // 只学 LLM 确认过的标签，防自我强化
    const { counts, norm } = fmFeatures(title, up);
    const p = 1 / (1 + Math.exp(-fmScore(counts, norm)));
    const g = 0.3 * (y - p);
    for (const [idx, c] of counts) {
      const v = (fmDelta[idx] || 0) + (g * c) / norm;
      if (Math.abs(v) < 0.001) delete fmDelta[idx];
      else fmDelta[idx] = Math.max(-1, Math.min(1, v));
    }
    const keys = Object.keys(fmDelta);
    if (keys.length > 30000) {
      keys.sort((a, b) => Math.abs(fmDelta[a]) - Math.abs(fmDelta[b]));
      for (const k of keys.slice(0, 5000)) delete fmDelta[k];
    }
    fmDeltaSave();
  }
  const FM_SHARE = {"0": 1.0, "5": 0.912, "10": 0.782, "15": 0.741, "20": 0.731, "25": 0.703, "30": 0.682, "35": 0.647, "40": 0.591, "45": 0.548, "50": 0.506, "55": 0.459, "60": 0.412, "65": 0.363, "70": 0.322, "75": 0.275, "80": 0.214, "85": 0.13, "90": 0.052, "95": 0.004, "100": 0.0};
  let tol = Math.max(0, Math.min(100, Number(localStorage.getItem("yfm_tol") ?? 50)));
  const ROUTE = { low: 0, high: 2, audit: 0 };
  function applyTol() {
    ROUTE.low = tol === 0 ? -1 : Math.min(0.60, 0.10 + 0.008 * tol);
    ROUTE.high = tol <= 50 ? 2 : 0.995 - 0.003 * (tol - 50);
    ROUTE.audit = tol === 0 ? 0 : Math.max(0.01, 0.06 - 0.0005 * tol);
  }
  applyTol();
  const fmShareEst = () => {
    const k = String(Math.min(100, Math.max(0, Math.round((ROUTE.low * 100) / 5) * 5)));
    return FM_SHARE[k] ?? 0.35;
  };

  // ---------- 样式 ----------
  const style = document.createElement("style");
  style.textContent = `
    /* 模式可见性：娱乐=good+ent，精选(gent)=仅good，专业=仅pro。
       广告卡（data-yfm="ad"）在任何模式下都不隐藏——本脚本不做广告屏蔽 */
    html[data-yfm-mode="pro"] ytd-rich-item-renderer[data-yfm="ent"],
    html[data-yfm-mode="pro"] ytd-rich-item-renderer[data-yfm="good"],
    html[data-yfm-mode="ent"] ytd-rich-item-renderer[data-yfm="pro"],
    html[data-yfm-mode="gent"] ytd-rich-item-renderer[data-yfm="pro"],
    html[data-yfm-mode="gent"] ytd-rich-item-renderer[data-yfm="ent"],
    html[data-yfm-mode="pro"] ytd-rich-item-renderer[data-yfm="junk"],
    html[data-yfm-mode="ent"] ytd-rich-item-renderer[data-yfm="junk"],
    html[data-yfm-mode="gent"] ytd-rich-item-renderer[data-yfm="junk"],
    html[data-yfm-mode="pro"] ytd-rich-item-renderer[data-yfm="pending"],
    html[data-yfm-mode="ent"] ytd-rich-item-renderer[data-yfm="pending"],
    html[data-yfm-mode="gent"] ytd-rich-item-renderer[data-yfm="pending"] { display: none !important; }
    /* Shorts 等娱乐性板块按 ent 处理（仅在全部/娱乐模式显示）；广告板块永不隐藏 */
    html[data-yfm-mode="pro"] ytd-rich-section-renderer[data-yfm="ent"],
    html[data-yfm-mode="gent"] ytd-rich-section-renderer[data-yfm="ent"] { display: none !important; }
    #yfm-switch {
      position: fixed; bottom: 24px; left: 24px; z-index: 99999;
      display: flex; gap: 2px; padding: 3px; border-radius: 999px;
      background: rgba(255,255,255,.97); box-shadow: 0 2px 10px rgba(0,0,0,.2);
      font-size: 13px; user-select: none;
    }
    #yfm-switch button {
      border: 0; background: transparent; padding: 4px 12px; border-radius: 999px;
      cursor: pointer; color: #333; font-size: 13px; font-family: inherit;
    }
    #yfm-switch button.on { background: #f00; color: #fff; }
    html[dark] #yfm-switch { background: rgba(40,40,40,.97); }
    html[dark] #yfm-switch button { color: #ddd; }
    #yfm-tok { display: flex; align-items: center; padding: 0 6px; color: #909090;
      font-size: 11px; white-space: nowrap; }
    #yfm-tol { display: flex; align-items: center; gap: 4px; padding: 0 6px 0 10px;
      border-left: 1px solid #e3e5e7; margin-left: 4px; color: #909090; font-size: 12px; }
    #yfm-tol input { width: 60px; accent-color: #0d9488; }
    #yfm-tol b { min-width: 36px; font-weight: normal; font-size: 11px; }
    html[dark] #yfm-tol { border-left-color: #4a4a4a; }
  `;
  document.head.appendChild(style);

  // ---------- 切换开关 ----------
  let mode = localStorage.getItem("yfm_mode") || "all";
  const sw = document.createElement("div");
  sw.id = "yfm-switch";
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
    const cur = localStorage.getItem("yfm_api_key") || "";
    const inp = prompt(ZH
      ? "输入你自己的 DeepSeek API Key（在 platform.deepseek.com 申请，用量与费用由你在 DeepSeek 后台自理，本脚本免费且不经手任何费用）。\n" +
        "留空并确定 = 不用云端，仅由内置本地模型分类。\n\n" +
        "隐私说明：启用后，仅视频的「标题、频道名」会发送给 DeepSeek 用于分类；\n" +
        "不会发送你的账号信息、Cookie 或观看历史。Key 仅保存在你自己的浏览器中。"
      : "Enter your DeepSeek API key (get one at platform.deepseek.com; usage is billed by DeepSeek to you — this script is free and never handles money).\n" +
        "Leave empty to skip the cloud and classify with the built-in local model only.\n\n" +
        "Privacy: only video titles and channel names are sent to DeepSeek for classification;\n" +
        "never your account, cookies or watch history. The key stays in your browser.",
      cur);
    if (inp === null) return;
    localStorage.setItem("yfm_api_key", inp.trim());
    alert(inp.trim() ? (ZH ? "已保存，刷新页面生效。" : "Saved. Reload the page to apply.") : (ZH ? "已清除 Key，将仅使用本地模型分类。刷新页面生效。" : "Key removed. The built-in local model will be used. Reload to apply."));
  };
  sw.appendChild(cfgBtn);
  // 连接码：填了才把浏览记录交给本机的兴趣程序，留空 = 这个功能完全不存在
  const imBtn = document.createElement("button");
  imBtn.textContent = "🔗";
  const IM_STATE_TEXT = {
    off:     [ "连接码（本机兴趣程序）：未启用", "Connection code (local interest service): off" ],
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
    const cur = localStorage.getItem("yfm_im_token") || "";
    const inp = prompt(ZH
      ? "粘贴本机兴趣程序的连接码（程序启动时会打印，也可以在 Breadcrumb 的发现页上复制）。\n\n" +
        "填好之后，脚本会把你在 YouTube 看到和点开的视频标题、频道名、封面地址、观看时长，发到你自己电脑上的 127.0.0.1:21456，\n" +
        "用来整理你自己的兴趣。这些内容不出这台电脑，也不会发给任何网站。\n\n" +
        "留空并确定 = 关闭这个功能。"
      : "Paste the connection code of the interest service running on this computer (it prints one on startup).\n\n" +
        "Once set, this script sends titles, channel names, cover urls and watch time of videos you see and open to 127.0.0.1:21456 on your own machine,\n" +
        "so it can build your own interest profile. Nothing leaves this computer and nothing is sent to any website.\n\n" +
        "Leave empty to turn this off.",
      cur);
    if (inp === null) return;
    localStorage.setItem("yfm_im_token", inp.trim());
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
  const tok = load("yfm_tok", { in: 0, hit: 0, out: 0, req: 0, c: 0, day: "", dIn: 0, dHit: 0, dOut: 0, dC: 0 });
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
    localStorage.setItem("yfm_tok", JSON.stringify(tok));
    tokRender();
  }
  const tokChip = document.createElement("span");
  tokChip.id = "yfm-tok";
  function tokRender() {
    tokRoll();
    tokChip.textContent = (ZH ? "今日" : "Today ") + fmtTok(tokDayUsed()) + "tok";
    tokChip.title = ZH
      ? "本站 LLM 用量（逐请求累计 API 返回的 usage）\n" +
        "今日：输入 " + fmtTok(tok.dIn) + "（缓存命中 " + fmtTok(tok.dHit) + "）+ 输出 " + fmtTok(tok.dOut) +
        " ≈ ¥" + (tok.dC || 0).toFixed(3) + "\n" +
        "累计：" + fmtTok(tok.in + tok.out) + " tok / " + tok.req + " 次请求 ≈ ¥" + (tok.c || 0).toFixed(2)
      : "LLM usage on this site (exact, from API-reported usage)\n" +
        "Today: in " + fmtTok(tok.dIn) + " (cache hit " + fmtTok(tok.dHit) + ") + out " + fmtTok(tok.dOut) +
        " ≈ ¥" + (tok.dC || 0).toFixed(3) + "\n" +
        "Total: " + fmtTok(tok.in + tok.out) + " tok / " + tok.req + " requests ≈ ¥" + (tok.c || 0).toFixed(2);
  }
  if (API_KEY) { sw.appendChild(tokChip); tokRender(); }
  // 容忍度滑条：更准更费 ←→ 更省更依赖本地模型
  const tolUI = document.createElement("div");
  tolUI.id = "yfm-tol";
  tolUI.title = ZH ? "分类容忍度：越低越多内容送大模型复核，更准但更费；越高越依赖本地小模型，几乎免费但可能有少量错分或漏内容。右侧数字为预计送大模型的比例。" : "Tolerance: lower sends more items to the cloud model (more accurate, costs more); higher relies on the free local model (a few misclassifications possible). The number shows the estimated share sent to the cloud.";
  const tolSpan = document.createElement("span");
  tolSpan.textContent = ZH ? "容忍" : "Tol";
  const tolInput = document.createElement("input");
  tolInput.type = "range"; tolInput.min = "0"; tolInput.max = "100"; tolInput.step = "10";
  const tolLabel = document.createElement("b");
  tolUI.append(tolSpan, tolInput, tolLabel);
  if (API_KEY) sw.appendChild(tolUI);
  const tolRender = () => { tolLabel.textContent = "AI" + Math.round(fmShareEst() * 100) + "%"; };
  tolInput.value = tol;
  tolRender();
  tolInput.oninput = () => {
    tol = Number(tolInput.value);
    localStorage.setItem("yfm_tol", String(tol));
    applyTol();
    tolRender();
  };

  function setMode(m) {
    mode = m;
    localStorage.setItem("yfm_mode", m);
    document.documentElement.dataset.yfmMode = m;
    sw.querySelectorAll("button").forEach(b => b.classList.toggle("on", b.dataset.m === m));
  }
  setMode(mode);

  // ---------- 关键词兜底分类（无 key 或 LLM 失败时用，中英双语） ----------
  const PRO_KW = ["科普","财经","经济","金融","投资","宏观","编程","代码","算法","AI","人工智能","大模型","芯片","半导体","教程","历史","纪录片","深度","解读","分析","讲座","physics","math","engineering","programming","coding","tutorial","lecture","documentary","economics","finance","science","research","explained","analysis","history"];
  const ENT_KW = ["游戏","搞笑","动画","vlog","日常","美食","旅行","宠物","音乐","舞蹈","综艺","影视","剪辑","电影","挑战","直播","funny","gaming","gameplay","vlog","music","dance","reaction","prank","challenge","meme","movie","trailer","shorts","cover","asmr","mukbang","cat","dog"];
  const JUNK_KW = ["变现","副业","月入","躺赚","涨粉","免费领","限时","passive income","get rich","make money fast","secret method","giveaway"];
  function kwClassify(title, owner) {
    const text = (title + " " + owner).toLowerCase();
    const score = (kws) => kws.reduce((s, kw) => s + (text.includes(kw.toLowerCase()) ? 1 : 0), 0);
    const j = score(JUNK_KW), p = score(PRO_KW), e = score(ENT_KW);
    if (j >= 1 && j >= p) return "junk";
    return p > e ? "pro" : e > p ? "ent" : "unk";
  }

  // ---------- LLM 批量分类（带重试与熔断） ----------
  const stats = { llmReq: 0, classified: 0 };
  let batch = [], batchTimer = null;
  let llmFailStreak = 0, llmCooldownUntil = 0;
  function enqueueLLM(item) {
    return new Promise((resolve) => {
      batch.push({ ...item, resolve });
      if (batch.length >= BATCH_SIZE) flushBatch();
      else if (!batchTimer) batchTimer = setTimeout(flushBatch, BATCH_WAIT_MS);
    });
  }
  async function flushBatch() {
    clearTimeout(batchTimer); batchTimer = null;
    const items = batch.splice(0);
    if (!items.length) return;
    if (Date.now() < llmCooldownUntil) { for (const it of items) it.resolve(null); return; }
    // 行式紧凑输入：序号|标题|频道名。不发 id（11 位视频 id 要吃约 8 个 token 且要被回显）
    const clean = (s) => String(s || "").replace(/[|\n]/g, " ").trim();
    const payload = items.map((it, i) =>
      (i + 1) + "|" + clean(it.title).slice(0, 80) + "|" + clean(it.owner)
    ).join("\n");
    // 兼容模型偶发输出全称或数组格式
    const CODE = { p: "pro", g: "good", e: "ent", j: "junk", "?": "?", pro: "pro", good: "good", ent: "ent", junk: "junk" };
    let map = null;
    for (let attempt = 0; attempt < 2 && !map; attempt++) {
      stats.llmReq++;
      try {
        const r = await fetch(API_URL, {
          method: "POST",
          headers: { "content-type": "application/json", "authorization": "Bearer " + API_KEY },
          body: JSON.stringify({
            model: MODEL, max_tokens: 500,
            // v4-flash 默认开思考模式，reasoning token 按输出计费，分类任务必须显式关闭
            ...(MODEL.startsWith("deepseek") ? { thinking: { type: "disabled" } } : {}),
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
          if (Number.isInteger(idx) && idx >= 0 && idx < items.length && c) map[items[idx].id] = c;
        }
      } catch (e) {
        console.warn("[yfm] LLM 分类失败(第" + (attempt + 1) + "次):", e);
        if (attempt === 0) await new Promise(res => setTimeout(res, 2500));
      }
    }
    if (map) llmFailStreak = 0;
    else if (++llmFailStreak >= 2) {
      llmCooldownUntil = Date.now() + 60000;
      console.warn("[yfm] LLM 连续失败，熔断 60 秒");
    }
    for (const it of items) it.resolve(map ? (map[it.id] || null) : null);
  }

  // 三层分类：① 本地学生模型（离线免费）② LLM 复核本地判正/按容忍度抽查判负 ③ 关键词兜底
  async function classify(id, title, owner) {
    if (upRule[owner]) return upRule[owner];
    if (cache[id]) return cache[id];
    const lp = fmProb(title, owner);
    if (!API_KEY) {
      if (lp >= 0.5) return "pro";
      const kw = kwClassify(title, owner);
      return kw === "pro" ? "ent" : kw;
    }
    if (mode === "pro" || mode === "all") {
      if (lp < ROUTE.low && Math.random() >= ROUTE.audit) { stats.localSkip = (stats.localSkip || 0) + 1; return "ent"; }
      if (lp >= ROUTE.high) { stats.localPass = (stats.localPass || 0) + 1; return "pro"; }
    }
    let cls = await enqueueLLM({ id, title, owner });
    if (cls === "?") cls = null;
    stats.classified++;
    if (cls) fmLearn(title, owner, cls === "pro" ? 1 : 0);
    if (!cls) cls = kwClassify(title, owner);
    if (cls !== "unk" && cls) { cache[id] = cls; save(); }
    return cls;
  }

  // ---------- 卡片处理（纯 DOM 过滤，零额外站内请求；补货依赖 YouTube 自身无限滚动） ----------
  const matchMode = (cls, m) => m === "gent" ? cls === "good" : m === "ent" ? (cls === "ent" || cls === "good") : cls === m;
  const onHome = () => location.pathname === "/";
  let inflight = 0;
  const queue = [];
  // 并发上限必须 ≥ LLM 批量大小：每个任务都在等同一次批量请求返回，
  // 上限过低会把实际批量压小（之前 6 并发导致每次 LLM 往返只带 6 条，吞吐砍到 1/4）
  function pump() {
    while (inflight < 32 && queue.length) { inflight++; queue.shift()().finally(() => { inflight--; pump(); }); }
  }

  const AD_SEL = "ytd-ad-slot-renderer, ytd-in-feed-ad-layout-renderer, ytd-display-ad-renderer, [class*=AdSlot]";
  function processCard(card) {
    if (card.dataset.yfmSeen) return;
    if (card.querySelector(AD_SEL)) { // 广告卡：标记后任何模式都显示
      card.dataset.yfm = "ad";
      card.dataset.yfmSeen = "1";
      return;
    }
    const link = card.querySelector('a[href*="watch?v="]');
    const vid = link && (link.getAttribute("href").match(/watch\?v=([\w-]{6,})/) || [])[1];
    if (!vid) return; // 未加载完成或 Shorts 等，等下一轮
    card.dataset.yfmSeen = "1";
    const h3 = card.querySelector("h3");
    const title = (h3 && h3.textContent.trim()) || "";
    const chA = card.querySelector('a[href^="/@"], ytd-channel-name a');
    const owner = (chA && chA.textContent.trim()) || "";
    if (!title) { delete card.dataset.yfmSeen; return; } // 标题未渲染，下一轮再试
    imReport({ type: "expose", id: vid, t: title, u: owner, pic: imCover(vid), dwell: 0, dur: 0 });
    if (!card.dataset.yfm) card.dataset.yfm = "pending"; // 分类完成前先藏起来（过滤模式下）
    queue.push(async () => {
      try { card.dataset.yfm = await classify(vid, title, owner); }
      catch (e) { card.dataset.yfm = "unk"; } // 出错也要放行
    });
    pump();
  }

  function processSection(sec) {
    if (sec.dataset.yfmSeen) return;
    if (sec.querySelector(AD_SEL)) { sec.dataset.yfm = "ad"; sec.dataset.yfmSeen = "1"; return; }
    const txt = sec.innerText.slice(0, 100);
    if (/Shorts/i.test(txt) || sec.querySelector("ytd-rich-shelf-renderer[is-shorts]")) {
      sec.dataset.yfm = "ent"; // Shorts 板块按娱乐处理
      sec.dataset.yfmSeen = "1";
    }
  }

  function scan() {
    if (!onHome()) return; // 只处理首页，不碰搜索/播放页
    document.querySelectorAll("ytd-rich-item-renderer").forEach(processCard);
    document.querySelectorAll("ytd-rich-section-renderer").forEach(processSection);
    // 背压阀：过滤模式下被隐藏的卡不占高度，加载哨兵一直可见会让 YouTube 无限狂灌。
    // 待分类积压超过阈值时暂时隐藏哨兵（暂停加载），消化完再放开——也是对 YT 服务器的保护
    const backlog = document.querySelectorAll('ytd-rich-item-renderer[data-yfm="pending"]').length;
    const cont = document.querySelector("ytd-continuation-item-renderer");
    if (cont) cont.style.display = (mode !== "all" && backlog > 60) ? "none" : "";
    // 供给指示：过滤模式下有积压时给出反馈，把"等待"变成"可见的进行中"
    hint.style.display = (mode !== "all" && backlog > 0) ? "block" : "none";
    if (backlog > 0) hint.textContent = "AI 分类中… " + backlog + " 条待处理";
    // 推荐流耗尽（YT 移除了加载哨兵，一次会话的推荐配额有限，过滤模式消耗更快）：
    // 在流末尾提供"换一批"卡片，刷新即获得全新一轮推荐（分类缓存在，老视频零成本）
    const grid = document.querySelector("ytd-rich-grid-renderer #contents");
    let btn = document.getElementById("yfm-refresh");
    if (grid && !cont && mode !== "all" && backlog === 0) {
      if (!btn) {
        btn = document.createElement("div");
        btn.id = "yfm-refresh";
        btn.textContent = "本轮推荐已刷完 · 点击换一批新推荐";
        btn.style.cssText = "grid-column:1/-1;width:100%;padding:28px 0;margin:8px 0 40px;text-align:center;font-size:15px;color:#fff;background:#f00;border-radius:12px;cursor:pointer;";
        btn.onclick = () => location.reload();
      }
      if (btn.parentElement !== grid || btn !== grid.lastElementChild) grid.appendChild(btn);
    } else if (btn) {
      btn.remove();
    }
  }

  const hint = document.createElement("div");
  hint.style.cssText = "position:fixed;bottom:70px;left:24px;z-index:99998;display:none;padding:4px 12px;border-radius:999px;background:rgba(0,0,0,.7);color:#fff;font-size:12px;";
  document.body.appendChild(hint);

  // SPA 导航：离开首页时开关条隐藏含义不大，保留但只在首页生效过滤
  document.addEventListener("yt-navigate-finish", () => setTimeout(scan, 500));
  scan();
  // DOM 变更合并调度：突发变更风暴下最多 300ms 扫一次
  let scanScheduled = false;
  const scheduleScan = () => {
    if (scanScheduled) return;
    scanScheduled = true;
    setTimeout(() => { scanScheduled = false; scan(); }, 300);
  };
  new MutationObserver(scheduleScan).observe(document.body, { childList: true, subtree: true });
  setInterval(scan, 3000);
  window.__yfm = { get imState() { return imState; }, get imQueued() { return imQueue.length; }, get imSent() { return imSent; }, cache, upRule, stats }; // 调试用
})();
