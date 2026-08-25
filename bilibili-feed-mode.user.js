// ==UserScript==
// @name         B站首页 娱乐/专业 模式切换
// @namespace    leo.bilibili.feedmode
// @version      1.0.3
// @description  用 LLM 把B站首页推荐流分为「专业/精选娱乐/娱乐」，左下角开关一键切换，可调"破茧"比例跳出信息茧房。需自备 DeepSeek API Key（⚙ 设置，启用后视频标题/UP名/标签会发送给 DeepSeek 用于分类）。不屏蔽任何广告与商业内容。非官方工具，与哔哩哔哩无关联。
// @match        https://www.bilibili.com/
// @match        https://www.bilibili.com/?*
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

  // ================= 配置 =================
  // API Key 通过页面左下角开关条上的 ⚙ 按钮设置，仅保存在你自己浏览器的 localStorage 中，
  // 不写在代码里、不随脚本分发、不上传到任何地方。未设置 key 时退回本地关键词规则分类。
  const API_KEY = (localStorage.getItem("bfm_api_key") || "").trim();
  const API_URL = localStorage.getItem("bfm_api_url") || "https://api.deepseek.com/chat/completions";
  const MODEL = localStorage.getItem("bfm_model") || "deepseek-chat";
  const BATCH_SIZE = 24;     // 攒够多少条发一次请求
  const BATCH_WAIT_MS = 400; // 或最多等待多久
  // ========================================

  const SYSTEM_PROMPT = `你是B站视频分类器。根据视频的标题、UP主名和标签，把每个视频分为四类之一：
- "pro"（专业）：真正有信息密度的内容——硬核知识科普、技术/编程/工程、财经与宏观分析、学术、深度纪录片、严肃的行业解读、高质量教学。判断标准是"看完能学到真东西"，且情绪基调必须冷静、克制、有建设性——看完是"搞懂了"而不是"更焦虑了"。以下内容即使话题专业也不算 pro：贩卖焦虑、渲染恐慌与灾难、煽动对立情绪、末日论调、阴谋论、"要崩盘/要完蛋/劲爆"式的情绪化标题党分析——这类归 ent（若含营销引流则归 junk）。专业同样宁缺毋滥。
- "good"（精选娱乐）：能带来优质情绪与情感价值的娱乐——治愈、温暖、纯粹的欢笑、才华与匠心（高水平创作、音乐、手艺、动画）、萌宠与自然、美食美景、真诚的生活记录、高质量的游戏/影视内容。判断标准是"看完心情变好：愉悦、感动或惊叹"。
- "ent"（普通娱乐）：其他娱乐内容，尤其包括：制造对立/引战/吵架的话题、蹭热点骂战、猎奇审丑、擦边、狗血冲突、贩卖愤怒或焦虑的社会新闻、无营养的快餐剪辑。在 good 和 ent 之间拿不准时归 ent（精选宁缺毋滥）。
- "junk"（营销水）：营销号、卖课/引流（"私信领资料""训练营""副业月入"类）、贩卖焦虑的成功学、标题党软广、水内容。

注意：标题里带"教程""知识"字样但实为卖课引流的归 junk；情侣日常、个人抱怨归 ent 而非 pro。
输入是 JSON 数组，每项有 id/title/up/tags。tags 可能为空；若 tags 为空且仅凭标题和UP主名确实无法判断，可以输出 "?"（之后会带着标签再问你）；但若 tags 非空，必须给出明确分类。
输出 JSON 对象：{"r": [{"id": "...", "c": "pro|good|ent|junk|?"}, ...]}，顺序与输入一致，不要输出其他内容。`;

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
    #bfm-mix { display: none; align-items: center; gap: 4px; padding: 0 6px 0 10px;
      border-left: 1px solid #e3e5e7; margin-left: 4px; color: #61666d; font-size: 12px; }
    html[data-bfm-mode="pro"] #bfm-mix { display: flex; }
    #bfm-mix input { width: 70px; accent-color: #0d9488; }
    #bfm-mix b { min-width: 30px; font-weight: normal; }
  `;
  document.head.appendChild(style);

  // ---------- 切换开关 ----------
  let mode = localStorage.getItem(LS.mode) || "all";
  const sw = document.createElement("div");
  sw.id = "bfm-switch";
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
    const cur = localStorage.getItem("bfm_api_key") || "";
    const inp = prompt(
      "输入你自己的 DeepSeek API Key（在 platform.deepseek.com 申请，费用自理，重度使用约每月几元）。\n" +
      "留空并确定 = 关闭 LLM 分类，使用本地关键词规则（免费但较不准确）。\n\n" +
      "隐私说明：启用后，仅视频的「标题、UP主名、标签」会发送给 DeepSeek 用于分类；\n" +
      "不会发送你的账号信息、Cookie 或观看历史。Key 仅保存在你自己的浏览器中。",
      cur);
    if (inp === null) return;
    localStorage.setItem("bfm_api_key", inp.trim());
    alert(inp.trim() ? "已保存，刷新页面生效。" : "已清除 Key，将使用本地关键词分类。刷新页面生效。");
  };
  sw.appendChild(cfgBtn);
  document.body.appendChild(sw);
  let booted = false; // 脚本尾部初始化完成后才允许 setMode 触发补货
  function setMode(m) {
    mode = m;
    localStorage.setItem(LS.mode, m);
    document.documentElement.dataset.bfmMode = m;
    sw.querySelectorAll("button").forEach(b => b.classList.toggle("on", b.dataset.m === m));
    if (booted && m !== "all") { ensurePool(); ensureMixPool(); maybeInject(); }
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
      await new Promise(r => setTimeout(r, 300 + Math.random() * 400)); // 请求间随机间隔
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
    const payload = items.map(it => ({ id: it.bvid, title: it.title, up: it.owner, tags: it.tags }));
    let map = null;
    for (let attempt = 0; attempt < 2 && !map; attempt++) { // 失败重试一次（可能是偶发限流）
      stats.llmReq++;
      try {
        const r = await fetch(API_URL, {
          method: "POST",
          headers: { "content-type": "application/json", "authorization": "Bearer " + API_KEY },
          body: JSON.stringify({
            model: MODEL,
            max_tokens: 2000,
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

  // 两段式：先只用标题+UP名问 LLM（省掉标签请求），LLM 没把握("?")的少数视频才去查标签重问
  async function classify(id, title, owner, presetTags) {
    if (upRule[owner]) return upRule[owner];
    if (cache[id]) return cache[id];
    let tags = presetTags || [];
    let cls = null;
    if (API_KEY) {
      cls = await enqueueLLM({ bvid: id, title, owner, tags });
      if (cls === "?") {
        stats.stage2++;
        if (id.startsWith("BV")) {
          tags = await fetchTags(id);
          cls = await enqueueLLM({ bvid: id, title, owner, tags });
        }
        if (cls === "?") cls = null;
      }
      stats.classified++;
    }
    if (!cls) cls = kwClassify(title, owner, tags); // 无 key 或 LLM 失败时兜底
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
    while (inflight < 32 && queue.length) { inflight++; queue.shift()().finally(() => { inflight--; pump(); }); }
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
  const MIX_TTL_MS = 60 * 60 * 1000;   // 破茧内容是长青精选，存活可以久一些
  let mixRatio = Number(localStorage.getItem("bfm_mix_ratio") ?? 30); // 注入卡片中破茧内容的百分比
  let pool = [];                       // {item, cls, ts}
  let mixPool = [];                    // {item, cls:"pro", ts, src:"mix"}
  let mixDisplayId = 1 + Math.floor(Math.random() * 5);
  let popularPn = 1 + Math.floor(Math.random() * 3); // 备用料源（综合热门）的页码
  try {
    const saved = JSON.parse(sessionStorage.getItem("bfm_pool") || "{}");
    if (saved.pool) pool = saved.pool.filter(p => Date.now() - p.ts < POOL_TTL_MS);
    if (saved.mixPool) mixPool = saved.mixPool.filter(p => Date.now() - p.ts < MIX_TTL_MS);
    (saved.shown || []).slice(-2000).forEach(b => shownBvids.add(b));
    if (saved.freshIdx) freshIdx = saved.freshIdx;
    if (saved.mixDisplayId) mixDisplayId = saved.mixDisplayId;
    if (saved.popularPn) popularPn = saved.popularPn;
  } catch (e) {}
  let poolSaveTimer = null;
  function persistPool() {
    clearTimeout(poolSaveTimer);
    poolSaveTimer = setTimeout(() => {
      try {
        sessionStorage.setItem("bfm_pool", JSON.stringify({
          pool: pool.slice(-240), mixPool: mixPool.slice(-120),
          shown: [...shownBvids].slice(-2000), freshIdx, mixDisplayId, popularPn,
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
      // 每轮并行抓 3 页 × 30 条，最多 3 轮；两段式分类下大部分视频不再需要标签请求
      for (let round = 0; round < 3 && poolCountFor(mode) < POOL_TARGET; round++) {
        const pages = await Promise.all([fetchFeedPage(), fetchFeedPage(), fetchFeedPage()]);
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
            pool.push({ item: it, cls, ts: Date.now() });
          } catch (e) {}
        }));
        if (pool.length > 240) pool.splice(0, pool.length - 240);
        persistPool();
        if (poolCountFor(mode) < POOL_TARGET) await new Promise(r => setTimeout(r, 1500)); // 轮间冷却
      }
    } catch (e) {
      if (!String(e).includes("bili-cooldown")) console.warn("[bfm] 预取失败", e);
    }
    // 抓了 9 页还没凑够（推荐流里该类内容少），歇 30 秒；若处于限流退避则对齐退避时间
    if (poolCountFor(mode) < POOL_MIN) poolCooldownUntil = Math.max(Date.now() + 30000, biliBackoffUntil);
    fetching = false;
  }

  // ---------- 破茧混入：从知识/科技/资讯分区的推荐流取料，LLM 过滤后按比例掺进注入卡片 ----------
  const MIX_REGIONS = [1010, 1012, 1009]; // 知识 / 科技数码 / 资讯
  let mixFetching = false, mixCooldownUntil = 0;
  const mixCount = () => mixPool.filter(p => Date.now() - p.ts < MIX_TTL_MS).length;

  async function fetchRegionPage(region) {
    stats.feedPages++;
    const u = "https://api.bilibili.com/x/web-interface/region/feed/rcmd?display_id=" + (mixDisplayId++) + "&request_cnt=30&from_region=" + region;
    let d;
    try { d = await biliFetch(u); } catch (e) { return null; }
    if (d.code !== 0) { stats.lastRegionErr = d.code; return null; } // null = 接口报错（多为限流）
    return (d.data.archives || []).filter(v => v.bvid).map(v => ({
      bvid: v.bvid, title: v.title, pic: v.cover, duration: v.duration, pubdate: v.pubdate,
      owner: { name: v.author ? v.author.name : "" },
      stat: { view: v.stat ? v.stat.view : 0, danmaku: v.stat ? v.stat.danmaku : 0 },
    }));
  }

  // 备用料源：综合热门（稳定、新鲜、量大），分区 feed 供给耗尽时顶上，LLM 照样只滤出专业
  async function fetchPopularPage() {
    stats.feedPages++;
    try {
      const d = await biliFetch("https://api.bilibili.com/x/web-interface/popular?pn=" + (popularPn++) + "&ps=20");
      if (d.code !== 0) return null;
      return (d.data.list || []).filter(v => v.bvid).map(v => ({
        bvid: v.bvid, title: v.title, pic: v.pic, duration: v.duration, pubdate: v.pubdate,
        owner: { name: v.owner ? v.owner.name : "" },
        stat: { view: v.stat ? v.stat.view : 0, danmaku: v.stat ? v.stat.danmaku : 0 },
      }));
    } catch (e) { return null; }
  }

  // 分区 feed 一次只抓一个分区（轮换），平时最少间隔 20 秒；供给耗尽/出错自动切换综合热门
  let mixRegionIdx = 0, lastMixFetch = 0;
  async function ensureMixPool(force) {
    if (mixFetching || mode !== "pro" || mixRatio === 0) return;
    if (Date.now() < mixCooldownUntil) return; // 冷却期间不动，force 也不豁免
    if (!force && Date.now() - lastMixFetch < 20000) return;
    if (mixCount() >= 20) return;
    mixFetching = true;
    lastMixFetch = Date.now();
    try {
      const region = MIX_REGIONS[mixRegionIdx++ % MIX_REGIONS.length];
      let page = await fetchRegionPage(region);
      if (page === null) page = await fetchPopularPage(); // 分区没货 → 综合热门顶上
      if (page === null) {
        mixCooldownUntil = Date.now() + 300000; // 两个料源都不行，歇 5 分钟
      } else {
        const seen = new Set(mixPool.map(p => p.item.bvid));
        const items = [];
        for (const it of page) {
          if (shownBvids.has(it.bvid) || seen.has(it.bvid)) continue;
          seen.add(it.bvid);
          items.push(it);
        }
        stats.mixCand = (stats.mixCand || 0) + items.length;
        await Promise.all(items.map(async (it) => {
          try {
            const cls = await classify(it.bvid, it.title, it.owner.name);
            stats["mix_" + cls] = (stats["mix_" + cls] || 0) + 1;
            if (cls === "pro") mixPool.push({ item: it, cls, ts: Date.now(), src: "mix" }); // 只收专业，营销水照样挡在门外
          } catch (e) { stats.mixErr = (stats.mixErr || 0) + 1; }
        }));
        if (mixPool.length > 120) mixPool.splice(0, mixPool.length - 120);
        persistPool();
      }
    } catch (e) { console.warn("[bfm] 破茧预取失败", e); }
    mixFetching = false;
  }

  // 破茧比例滑条（仅专业模式显示）
  const mixUI = document.createElement("div");
  mixUI.id = "bfm-mix";
  mixUI.title = "注入卡片中「热榜内容」的占比：0% 纯个性化推荐，100% 全是来自知识/科技分区和全站热门的圈外精选";
  mixUI.innerHTML = '<span>热榜内容</span><input type="range" min="0" max="100" step="10"><b></b>';
  sw.appendChild(mixUI);
  const mixInput = mixUI.querySelector("input"), mixLabel = mixUI.querySelector("b");
  mixInput.value = mixRatio;
  mixLabel.textContent = mixRatio + "%";
  mixInput.oninput = () => {
    mixRatio = Number(mixInput.value);
    mixLabel.textContent = mixRatio + "%";
    localStorage.setItem("bfm_mix_ratio", String(mixRatio));
    if (mixRatio > 0) ensureMixPool(true);
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
    for (let i = mixPool.length - 1; i >= 0; i--) if (now - mixPool[i].ts > MIX_TTL_MS) mixPool.splice(i, 1);
    const pickOne = (arr) => {
      for (let i = 0; i < arr.length; i++) {
        if (matchMode(arr[i].cls, mode) && !shownBvids.has(arr[i].item.bvid)) return arr.splice(i, 1)[0];
      }
      return null;
    };
    // 按比例分配名额：破茧池不足用推荐池补，推荐池不足用破茧池兜底（比例为 0 时不兜底）
    const useMix = mode === "pro" && mixRatio > 0;
    const wantMix = useMix ? Math.round(n * mixRatio / 100) : 0;
    const picks = [];
    for (let k = 0; k < n; k++) {
      const p = k < wantMix
        ? (pickOne(mixPool) || pickOne(pool))
        : (pickOne(pool) || (useMix ? pickOne(mixPool) : null));
      if (!p) break;
      picks.push(p);
    }
    picks.sort(() => Math.random() - 0.5); // 打散，避免破茧内容扎堆
    for (const p of picks) {
      shownBvids.add(p.item.bvid);
      const el = buildCard(p);
      cont.appendChild(el); // 只追加到末尾，绝不插入中间
    }
    if (picks.length) persistPool();
    if (poolCountFor(mode) < POOL_MIN) ensurePool(true); // 用户在消耗，强制补货
    if (useMix && mixCount() < 10) ensureMixPool(true);
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
    ensurePool(); ensureMixPool(); maybeInject();
  }, 3000);
  booted = true;
  if (mode !== "all") { ensurePool(); ensureMixPool(); maybeInject(); }
  window.__bfm = { get pool() { return pool; }, get mixPool() { return mixPool; }, shownBvids, cache, upRule, ensurePool, ensureMixPool, injectFromPool, stats,
    get backoff() { return { biliBackoffUntil, biliBackoffLevel, llmCooldownUntil, llmFailStreak, poolCooldownUntil, mixCooldownUntil }; } }; // 调试用
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
