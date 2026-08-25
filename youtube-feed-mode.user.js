// ==UserScript==
// @name         YouTube 首页 娱乐/专业 模式切换
// @namespace    leo.youtube.feedmode
// @version      1.2.0
// @description  用 LLM 把 YouTube 首页推荐流分为「专业/精选娱乐/娱乐」，左下角开关一键切换。需自备 DeepSeek API Key（⚙ 设置，启用后视频标题/频道名会发送给 DeepSeek 用于分类）。不屏蔽任何广告与商业内容。非官方工具，与 YouTube/Google 无关联。
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

  // ---------- token 计量（纯观测，不干预请求）：逐请求累计 API 返回的 usage，精确值非估算 ----------
  // deepseek-v4-flash 价目（元/百万token，≈美元价×7.2）；高峰时段（UTC 1-4 与 6-10 点）价格×2
  const PRICE = { hit: 0.05, miss: 1.58, out: 4.75 };
  const priceFactor = () => { const h = new Date().getUTCHours(); return (h >= 1 && h < 4) || (h >= 6 && h < 10) ? 2 : 1; };
  const tok = load("yfm_tok", { in: 0, hit: 0, out: 0, req: 0, c: 0, day: "", dIn: 0, dHit: 0, dOut: 0, dC: 0 });
  const tokDayStr = () => { const t = new Date(); return t.getFullYear() + "-" + (t.getMonth() + 1) + "-" + t.getDate(); };
  const tokRoll = () => { const d = tokDayStr(); if (tok.day !== d) { tok.day = d; tok.dIn = tok.dHit = tok.dOut = 0; tok.dC = 0; } };
  const tokDayUsed = () => { tokRoll(); return tok.dIn + tok.dOut; };
  const fmtTok = (n) => n >= 1e8 ? (n / 1e8).toFixed(2) + "亿" : n >= 1e4 ? (n / 1e4).toFixed(1) + "万" : String(n);
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
    tokChip.textContent = "今日" + fmtTok(tokDayUsed()) + "tok";
    tokChip.title = "本站 LLM 用量（逐请求累计 API 返回的 usage）\n" +
      "今日：输入 " + fmtTok(tok.dIn) + "（缓存命中 " + fmtTok(tok.dHit) + "）+ 输出 " + fmtTok(tok.dOut) +
      " ≈ ¥" + (tok.dC || 0).toFixed(3) + "\n" +
      "累计：" + fmtTok(tok.in + tok.out) + " tok / " + tok.req + " 次请求 ≈ ¥" + (tok.c || 0).toFixed(2);
  }
  if (API_KEY) { sw.appendChild(tokChip); tokRender(); }

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
  window.__yfm = { cache, upRule, stats }; // 调试用
})();
