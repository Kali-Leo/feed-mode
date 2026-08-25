// ==UserScript==
// @name         YouTube 首页 娱乐/专业 模式切换
// @namespace    leo.youtube.feedmode
// @version      1.0.0
// @description  用 LLM 把 YouTube 首页推荐流分为「专业/精选娱乐/娱乐」，左下角开关一键切换。需自备 DeepSeek API Key（⚙ 设置，启用后视频标题/频道名会发送给 DeepSeek 用于分类）。不屏蔽任何广告与商业内容。非官方工具，与 YouTube/Google 无关联。
// @match        https://www.youtube.com/*
// @grant        none
// @run-at       document-idle
// @license      GPL-3.0
// ==/UserScript==
// 本脚本为非官方社区工具。设计原则：不屏蔽广告、不劫持流量、不调用任何非页面自身的站内接口
// （纯 DOM 过滤，补货完全依赖 YouTube 自己的无限滚动）。仅在首页生效。

(function () {
  "use strict";
  if (window.__yfm) return; // 防止重复注入

  // ================= 配置 =================
  // API Key 通过左下角开关条上的 ⚙ 设置，仅存于你浏览器的 localStorage（youtube.com 域下）
  const API_KEY = (localStorage.getItem("yfm_api_key") || "").trim();
  const API_URL = localStorage.getItem("yfm_api_url") || "https://api.deepseek.com/chat/completions";
  const MODEL = localStorage.getItem("yfm_model") || "deepseek-chat";
  const BATCH_SIZE = 24;
  const BATCH_WAIT_MS = 400;
  // ========================================

  const SYSTEM_PROMPT = `你是视频分类器。根据 YouTube 视频的标题和频道名（可能是任何语言），把每个视频分为四类之一：
- "pro"（专业）：真正有信息密度的内容——硬核知识科普、技术/编程/工程、财经与宏观分析、学术、深度纪录片、严肃的行业解读、高质量教学。判断标准是"看完能学到真东西"。
- "good"（精选娱乐）：能带来优质情绪与情感价值的娱乐——治愈、温暖、纯粹的欢笑、才华与匠心（高水平创作、音乐、手艺、动画）、萌宠与自然、美食美景、真诚的生活记录、高质量的游戏/影视内容。判断标准是"看完心情变好：愉悦、感动或惊叹"。
- "ent"（普通娱乐）：其他娱乐内容，尤其包括：制造对立/引战的话题、蹭热点骂战、猎奇审丑、擦边、狗血冲突、贩卖愤怒或焦虑的内容、无营养的快餐剪辑、标题党 clickbait。在 good 和 ent 之间拿不准时归 ent（精选宁缺毋滥）。
- "junk"（营销水）：营销号、卖课/引流、贩卖焦虑的成功学、软广。

输入是 JSON 数组，每项有 id/title/up。若仅凭标题和频道名确实无法判断，可以输出 "?"。
输出 JSON 对象：{"r": [{"id": "...", "c": "pro|good|ent|junk|?"}, ...]}，顺序与输入一致，不要输出其他内容。`;

  const load = (k, d) => { try { return JSON.parse(localStorage.getItem(k)) ?? d; } catch { return d; } };
  const cache = load("yfm_cache", {});   // videoId -> 分类
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
  `;
  document.head.appendChild(style);

  // ---------- 切换开关 ----------
  let mode = localStorage.getItem("yfm_mode") || "all";
  const sw = document.createElement("div");
  sw.id = "yfm-switch";
  for (const [m, label] of [["all", "全部"], ["ent", "娱乐"], ["gent", "精选娱乐"], ["pro", "专业"]]) {
    const b = document.createElement("button");
    b.textContent = label;
    b.dataset.m = m;
    b.onclick = () => setMode(m);
    sw.appendChild(b);
  }
  const cfgBtn = document.createElement("button");
  cfgBtn.textContent = "⚙";
  cfgBtn.title = "设置 API Key（用于 LLM 智能分类）";
  cfgBtn.onclick = () => {
    const cur = localStorage.getItem("yfm_api_key") || "";
    const inp = prompt(
      "输入你自己的 DeepSeek API Key（在 platform.deepseek.com 申请，费用自理）。\n" +
      "留空并确定 = 关闭 LLM 分类，使用本地关键词规则（免费但较不准确）。\n\n" +
      "隐私说明：启用后，仅视频的「标题、频道名」会发送给 DeepSeek 用于分类；\n" +
      "不会发送你的账号信息、Cookie 或观看历史。Key 仅保存在你自己的浏览器中。",
      cur);
    if (inp === null) return;
    localStorage.setItem("yfm_api_key", inp.trim());
    alert(inp.trim() ? "已保存，刷新页面生效。" : "已清除 Key，将使用本地关键词分类。刷新页面生效。");
  };
  sw.appendChild(cfgBtn);
  document.body.appendChild(sw);
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
    const payload = items.map(it => ({ id: it.id, title: it.title, up: it.owner }));
    let map = null;
    for (let attempt = 0; attempt < 2 && !map; attempt++) {
      stats.llmReq++;
      try {
        const r = await fetch(API_URL, {
          method: "POST",
          headers: { "content-type": "application/json", "authorization": "Bearer " + API_KEY },
          body: JSON.stringify({
            model: MODEL, max_tokens: 2000,
            response_format: { type: "json_object" },
            messages: [
              { role: "system", content: SYSTEM_PROMPT },
              { role: "user", content: JSON.stringify(payload) },
            ],
          }),
        });
        const d = await r.json();
        if (!d.choices) throw new Error("api error: " + JSON.stringify(d).slice(0, 120));
        const out = JSON.parse(d.choices[0].message.content);
        map = {};
        for (const it of (out.r || [])) if (["pro","good","ent","junk","?"].includes(it.c)) map[it.id] = it.c;
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

  async function classify(id, title, owner) {
    if (upRule[owner]) return upRule[owner];
    if (cache[id]) return cache[id];
    let cls = null;
    if (API_KEY) {
      cls = await enqueueLLM({ id, title, owner });
      if (cls === "?") cls = null;
      stats.classified++;
    }
    if (!cls) cls = kwClassify(title, owner);
    if (cls !== "unk") { cache[id] = cls; save(); }
    return cls;
  }

  // ---------- 卡片处理（纯 DOM 过滤，零额外站内请求；补货依赖 YouTube 自身无限滚动） ----------
  const matchMode = (cls, m) => m === "gent" ? cls === "good" : m === "ent" ? (cls === "ent" || cls === "good") : cls === m;
  const onHome = () => location.pathname === "/";
  let inflight = 0;
  const queue = [];
  function pump() {
    while (inflight < 6 && queue.length) { inflight++; queue.shift()().finally(() => { inflight--; pump(); }); }
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
    const cont = document.querySelector("ytd-continuation-item-renderer");
    if (cont) {
      const backlog = document.querySelectorAll('ytd-rich-item-renderer[data-yfm="pending"]').length;
      cont.style.display = (mode !== "all" && backlog > 60) ? "none" : "";
    }
  }

  // SPA 导航：离开首页时开关条隐藏含义不大，保留但只在首页生效过滤
  document.addEventListener("yt-navigate-finish", () => setTimeout(scan, 500));
  scan();
  new MutationObserver(() => scan()).observe(document.body, { childList: true, subtree: true });
  setInterval(scan, 3000);
  window.__yfm = { cache, upRule, stats }; // 调试用
})();
