/* 小说转短剧 前端（原生 JS，无需构建） */
(() => {
  'use strict';

  // ------------------------------------------------------------------
  // 工具
  // ------------------------------------------------------------------
  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const fmtTime = (ts) => (ts ? new Date(ts * 1000).toLocaleString('zh-CN', { hour12: false }) : '');
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

  function toast(msg, type = '') {
    const el = $('toast');
    el.textContent = msg;
    el.className = `toast ${type}`;
    clearTimeout(toast._t);
    toast._t = setTimeout(() => el.classList.add('hidden'), type === 'error' ? 6000 : 2500);
  }

  async function api(method, path, body) {
    const opt = { method, headers: {} };
    if (body !== undefined) {
      opt.headers['Content-Type'] = 'application/json';
      opt.body = JSON.stringify(body);
    }
    const resp = await fetch(`/api${path}`, opt);
    if (!resp.ok) {
      let detail = resp.statusText;
      try { detail = (await resp.json()).detail || detail; } catch (_) { /* ignore */ }
      if (typeof detail !== 'string') detail = JSON.stringify(detail);
      throw new Error(detail);
    }
    return resp.json();
  }

  function modal(title, bodyHtml, onMount) {
    $('modalTitle').textContent = title;
    $('modalBody').innerHTML = bodyHtml;
    $('modal').classList.remove('hidden');
    if (onMount) onMount($('modalBody'));
  }
  const closeModal = () => $('modal').classList.add('hidden');

  function confirmDialog(title, html) {
    return new Promise((resolve) => {
      modal(title, `${html}<div style="display:flex;gap:8px;justify-content:flex-end;margin-top:14px"><button class="btn" id="cfNo">取消</button><button class="btn primary" id="cfYes">确认执行</button></div>`, (box) => {
        box.querySelector('#cfNo').onclick = () => { closeModal(); resolve(false); };
        box.querySelector('#cfYes').onclick = () => { closeModal(); resolve(true); };
      });
    });
  }

  const fileUrl = (asset) => (asset ? `/files/${state.project.id}/${asset.path}` : '');
  const PROVIDER_LABEL = { mock: '模拟', deepseek: 'DeepSeek', qwen: '通义千问', wanx: '通义万相', jimeng: '即梦', kling: '可灵' };
  const GENRES = ['都市情感', '甜宠', '虐恋', '豪门恩怨', '复仇逆袭', '悬疑推理', '古装宫斗', '玄幻仙侠', '穿越重生', '职场商战', '家庭伦理', '校园青春', '科幻', '恐怖惊悚', '喜剧'];

  // ------------------------------------------------------------------
  // 状态
  // ------------------------------------------------------------------
  const state = {
    config: null,
    projects: [],
    project: null,
    step: 'settings',
    chapterIndex: 1,
    visualChapter: 1,
    job: null,
    jobTimer: null,
    imageKinds: ['characters', 'scenes', 'props', 'storyboard'],
    imageChapter: 'all',
  };

  // ------------------------------------------------------------------
  // 任务轮询
  // ------------------------------------------------------------------
  function showJob(job) {
    state.job = job;
    const bar = $('jobbar');
    bar.classList.remove('hidden');
    $('jobKind').textContent = jobKindLabel(job.kind);
    $('jobMessage').textContent = job.message || ({ pending: '已提交，等待开始…', running: '运行中…', done: '完成', failed: '失败', cancelled: '已取消' }[job.status] || job.status);
    $('jobProgress').style.width = `${Math.round((job.progress || 0) * 100)}%`;
    $('jobLogs').textContent = (job.logs || []).join('\n');
    $('jobLogs').scrollTop = $('jobLogs').scrollHeight;
    const sp = $('jobSpinner');
    sp.className = 'spinner' + (job.status === 'done' ? ' stopped' : job.status === 'failed' || job.status === 'cancelled' ? ' failed' : '');
    $('btnJobCancel').classList.toggle('hidden', !(job.status === 'running' || job.status === 'pending'));
  }

  function jobKindLabel(kind) {
    const map = { outline: '生成大纲', 'chapters:all': '生成全部章节', characters: '角色设定', 'visual:all': '全部分镜', images: '生成图片' };
    if (map[kind]) return map[kind];
    if (kind.startsWith('chapter:')) return `第${kind.split(':')[1]}章初稿`;
    if (kind.startsWith('humanize:')) return `第${kind.split(':')[1]}章去AI味`;
    if (kind.startsWith('visual:')) return `第${kind.split(':')[1]}章分镜`;
    if (kind.startsWith('videos:')) return `${kind.split(':')[1].replace('ep', '第')}集视频`;
    if (kind.startsWith('render:')) return `${kind.split(':')[1].replace('ep', '第')}集成片`;
    return kind;
  }

  async function runJob(startPromise, onDone) {
    let job;
    try {
      job = await startPromise;
    } catch (e) {
      toast(e.message, 'error');
      return null;
    }
    showJob(job);
    clearInterval(state.jobTimer);
    return new Promise((resolve) => {
      state.jobTimer = setInterval(async () => {
        try {
          const j = await api('GET', `/jobs/${job.id}`);
          showJob(j);
          if (['done', 'failed', 'cancelled'].includes(j.status)) {
            clearInterval(state.jobTimer);
            await loadProject(state.project.id, false);
            await loadProjects();
            if (j.status === 'done') toast('任务完成', 'ok');
            else if (j.status === 'failed') toast(`任务失败：${j.error || ''}`, 'error');
            render();
            if (onDone) onDone(j);
            resolve(j);
          }
        } catch (e) {
          clearInterval(state.jobTimer);
          toast(e.message, 'error');
          resolve(null);
        }
      }, 1200);
    });
  }

  $('btnJobLogs').onclick = () => $('jobLogs').classList.toggle('hidden');
  $('btnJobClose').onclick = () => $('jobbar').classList.add('hidden');
  $('btnJobCancel').onclick = async () => { if (state.job) { await api('POST', `/jobs/${state.job.id}/cancel`).catch((e) => toast(e.message, 'error')); } };

  // ------------------------------------------------------------------
  // 加载
  // ------------------------------------------------------------------
  async function loadConfig() {
    state.config = await api('GET', '/config');
    renderBadges();
  }

  async function loadProjects() {
    state.projects = await api('GET', '/projects');
    const sel = $('projectSelect');
    sel.innerHTML = state.projects.map((p) => `<option value="${p.id}">${esc(p.name)}（${esc(p.genre)} · ${p.chapters_done}/${p.chapter_count} 章）</option>`).join('') || '<option value="">（暂无项目，请新建）</option>';
    if (state.project) sel.value = state.project.id;
  }

  async function loadProject(id, doRender = true) {
    if (!id) { state.project = null; if (doRender) render(); return; }
    state.project = await api('GET', `/projects/${id}`);
    localStorage.setItem('n2d:lastProject', id);
    $('projectSelect').value = id;
    if (doRender) render();
  }

  function renderBadges() {
    const c = state.config;
    if (!c) return;
    const s = c.selection;
    const badge = (label, name) => `<span class="badge ${name === 'mock' ? 'mock' : 'real'}" title="${esc(label)}">${esc(label)}：${esc(PROVIDER_LABEL[name] || name)}</span>`;
    $('providerBadges').innerHTML = badge('文本', s.llm_provider) + badge('分镜', s.visual_llm_provider) + badge('图片', s.image_provider) + badge('视频', s.video_provider) + (c.ffmpeg_ok ? '' : '<span class="badge" style="color:var(--danger)">未检测到 ffmpeg</span>');
  }

  // ------------------------------------------------------------------
  // 渲染
  // ------------------------------------------------------------------
  function render() {
    document.querySelectorAll('#stepNav button').forEach((b) => {
      b.classList.toggle('active', b.dataset.step === state.step);
      b.classList.toggle('done', isStepDone(b.dataset.step));
    });
    const main = $('main');
    if (!state.project) {
      main.innerHTML = `<div class="card"><h2>欢迎使用「小说转短剧」</h2><p class="hint">点击右上角「＋ 新建」创建一个项目开始。整个流程：设定 → 大纲 → 章节正文（含去 AI 味）→ 角色与分镜提示词 → 图片 → 视频与剧集。每一步都可以预览、修改、重新生成。</p>
        <p class="hint">当前模式：${state.config && Object.values(state.config.selection).every((v) => v === 'mock') ? '<b style="color:var(--warn)">全部模拟</b>（不需要密钥，可完整跑通流程）' : '部分真实厂商'}。点击「⚙ 厂商设置」可切换。</p></div>`;
      return;
    }
    const renderers = { settings: renderSettings, outline: renderOutline, chapters: renderChapters, visual: renderVisual, images: renderImages, video: renderVideo };
    main.innerHTML = '';
    renderers[state.step]();
  }

  function isStepDone(step) {
    const p = state.project;
    if (!p) return false;
    switch (step) {
      case 'settings': return !!p.settings.genre && p.settings.chapter_count > 0;
      case 'outline': return !!p.outline;
      case 'chapters': return p.chapters.length > 0 && p.chapters.every((c) => c.status !== 'empty');
      case 'visual': return Object.keys(p.visuals || {}).length > 0;
      case 'images': return Object.values(p.visuals || {}).some((v) => v.shots.some((s) => s.image));
      case 'video': return p.episodes.some((e) => e.status === 'rendered');
      default: return false;
    }
  }

  // ---------------- 1. 设定 ----------------
  function renderSettings() {
    const p = state.project;
    const s = p.settings;
    const dp = state.config.default_prompts;
    const sp = s.style_prompts || {};
    const promptField = (key, label) => `<label class="field">${esc(label)}<textarea data-prompt="${key}" placeholder="${esc(dp[key])}">${esc(sp[key] || '')}</textarea></label>`;
    $('main').innerHTML = `
      <div class="card">
        <div class="card-head"><div><h2>1. 小说设定</h2><p class="hint">设定题材、人物、篇幅。保存后进入「大纲」。</p></div>
          <div class="actions"><button class="btn" id="btnSaveSettings">保存设定</button><button class="btn primary" id="btnSaveAndOutline">保存并生成大纲 →</button></div></div>
        <div class="grid-3">
          <label class="field">项目名称<input type="text" id="f_name" value="${esc(p.name)}"></label>
          <label class="field">书名（可留空由模型拟定）<input type="text" id="f_title" value="${esc(s.title)}"></label>
          <label class="field">题材<input type="text" id="f_genre" list="genreList" value="${esc(s.genre)}"><datalist id="genreList">${GENRES.map((g) => `<option value="${g}">`).join('')}</datalist></label>
          <label class="field">基调（如：爽、虐、悬疑、轻喜剧）<input type="text" id="f_tone" value="${esc(s.tone)}"></label>
          <label class="field">目标总字数<input type="number" id="f_words" min="1000" step="1000" value="${s.target_word_count}"></label>
          <label class="field">章节数<input type="number" id="f_chapters" min="1" max="200" value="${s.chapter_count}"></label>
          <label class="field">每集包含章节数（默认 1 章 = 1 集）<input type="number" id="f_cpe" min="1" value="${s.chapters_per_episode}"></label>
          <label class="field">每章镜头数<input type="number" id="f_shots" min="1" max="40" value="${s.shots_per_chapter}"></label>
          <label class="field">每镜头时长（秒）<select id="f_dur"><option value="5" ${s.shot_duration_sec === 5 ? 'selected' : ''}>5 秒</option><option value="10" ${s.shot_duration_sec === 10 ? 'selected' : ''}>10 秒</option></select></label>
          <label class="field">画幅<select id="f_ar">${['16:9', '9:16', '1:1', '4:3', '3:4'].map((a) => `<option ${s.aspect_ratio === a ? 'selected' : ''}>${a}</option>`).join('')}</select></label>
        </div>
        <label class="field" style="margin-top:12px">故事创意 / 梗概（可留空）<textarea id="f_premise">${esc(s.premise)}</textarea></label>
      </div>
      <div class="card">
        <div class="card-head"><h3>人物设定</h3><button class="btn" id="btnAddChar">＋ 添加人物</button></div>
        <div class="grid-2" id="charList">${s.characters.map((c, i) => charCard(c, i)).join('') || '<div class="empty">还没有人物。不添加也可以，模型会自行设计。</div>'}</div>
      </div>
      <div class="card">
        <details class="prompts"><summary>风格提示词（高级，可编辑；留空使用默认值）</summary>
          <p class="hint">这些提示词决定大纲、正文、去 AI 味改写、分镜与画风。文本框内灰色为默认值，直接修改即可覆盖。</p>
          <div class="grid-2">
            ${promptField('outline_system', '大纲 系统提示词')}
            ${promptField('chapter_system', '章节正文 系统提示词')}
            ${promptField('humanize_system', '去 AI 味改写 系统提示词')}
            ${promptField('summary_system', '前情摘要 系统提示词')}
            ${promptField('visual_system', '分镜/提示词 系统提示词（第二个模型）')}
            <div>${promptField('image_style_suffix', '图片统一画风后缀')}${promptField('video_style_suffix', '视频统一风格后缀')}</div>
          </div>
          <button class="btn small ghost" id="btnResetPrompts" style="margin-top:8px">全部恢复默认</button>
        </details>
      </div>`;

    $('btnAddChar').onclick = () => { collectSettings(); state.project.settings.characters.push({ name: '', role: '', gender: '', age: '', traits: '', appearance: '', relationships: '', background: '' }); renderSettings(); };
    document.querySelectorAll('[data-del-char]').forEach((b) => { b.onclick = () => { collectSettings(); state.project.settings.characters.splice(+b.dataset.delChar, 1); renderSettings(); }; });
    $('btnResetPrompts').onclick = () => { document.querySelectorAll('[data-prompt]').forEach((t) => (t.value = '')); };
    $('btnSaveSettings').onclick = async () => { if (await saveSettings()) toast('设定已保存', 'ok'); };
    $('btnSaveAndOutline').onclick = async () => {
      if (!(await saveSettings())) return;
      state.step = 'outline';
      render();
      await runJob(api('POST', `/projects/${state.project.id}/outline/generate`));
    };
  }

  function charCard(c, i) {
    const f = (k, label, ph = '') => `<label class="field">${label}<input type="text" data-char="${i}" data-k="${k}" value="${esc(c[k])}" placeholder="${esc(ph)}"></label>`;
    return `<div class="char-card"><div class="head"><b>人物 ${i + 1}</b><button class="btn small danger ghost" data-del-char="${i}">删除</button></div>
      <div class="row">${f('name', '姓名', '必填')}${f('role', '定位', '主角 / 反派 / 配角')}${f('gender', '性别')}${f('age', '年龄')}</div>
      <div class="row" style="margin-top:8px"><label class="field">性格<textarea data-char="${i}" data-k="traits">${esc(c.traits)}</textarea></label><label class="field">外貌（影响画面一致性，尽量具体）<textarea data-char="${i}" data-k="appearance">${esc(c.appearance)}</textarea></label></div>
      <div class="row" style="margin-top:8px"><label class="field">与他人关系<textarea data-char="${i}" data-k="relationships">${esc(c.relationships)}</textarea></label><label class="field">背景<textarea data-char="${i}" data-k="background">${esc(c.background)}</textarea></label></div></div>`;
  }

  function collectSettings() {
    const s = state.project.settings;
    state.project.name = $('f_name').value.trim() || state.project.name;
    s.title = $('f_title').value.trim();
    s.genre = $('f_genre').value.trim() || '都市情感';
    s.tone = $('f_tone').value.trim();
    s.premise = $('f_premise').value.trim();
    s.target_word_count = Math.max(500, +$('f_words').value || 20000);
    s.chapter_count = Math.max(1, +$('f_chapters').value || 10);
    s.chapters_per_episode = Math.max(1, +$('f_cpe').value || 1);
    s.shots_per_chapter = Math.max(1, +$('f_shots').value || 8);
    s.shot_duration_sec = +$('f_dur').value || 5;
    s.aspect_ratio = $('f_ar').value;
    const chars = {};
    document.querySelectorAll('[data-char]').forEach((el) => { (chars[el.dataset.char] ||= {})[el.dataset.k] = el.value.trim(); });
    s.characters = Object.keys(chars).sort((a, b) => a - b).map((k) => ({ ...s.characters[+k], ...chars[k] })).filter((c) => c.name);
    s.style_prompts = s.style_prompts || {};
    document.querySelectorAll('[data-prompt]').forEach((t) => { s.style_prompts[t.dataset.prompt] = t.value.trim(); });
  }

  async function saveSettings() {
    try {
      collectSettings();
      state.project = await api('PUT', `/projects/${state.project.id}`, { name: state.project.name, settings: state.project.settings });
      await loadProjects();
      return true;
    } catch (e) { toast(e.message, 'error'); return false; }
  }

  // ---------------- 2. 大纲 ----------------
  function renderOutline() {
    const p = state.project;
    const o = p.outline;
    const head = `<div class="card"><div class="card-head"><div><h2>2. 大纲</h2><p class="hint">大纲包含故事梗概、世界设定、角色圣经与逐章纲要。后续章节写作严格依据这里的内容，可随时修改后保存。</p></div>
      <div class="actions"><button class="btn ${o ? '' : 'primary'}" id="btnGenOutline">${o ? '重新生成大纲' : '生成大纲'}</button>${o ? '<button class="btn primary" id="btnSaveOutline">保存修改</button><button class="btn" id="btnGoChapters">下一步：章节正文 →</button>' : ''}</div></div>`;
    if (!o) { $('main').innerHTML = head + '<div class="empty">还没有大纲。点击「生成大纲」。</div>'; bindOutline(); return; }
    const ta = (k, label, tall = false) => `<label class="field">${label}<textarea id="o_${k}" class="${tall ? 'tall' : ''}">${esc(o[k])}</textarea></label>`;
    $('main').innerHTML = head + `
      <div class="card"><div class="grid-2">
        <label class="field">书名<input type="text" id="o_title" value="${esc(o.title)}"></label>
        <label class="field">一句话故事<input type="text" id="o_logline" value="${esc(o.logline)}"></label>
      </div><div class="grid-2" style="margin-top:10px">${ta('synopsis', '故事梗概')}${ta('world_setting', '世界设定')}</div>
      <div style="margin-top:10px">${ta('character_bible', '角色圣经（跨章节一致性的依据）')}</div></div>
      <div class="card"><div class="card-head"><h3>章节纲要（${o.chapters.length} 章）</h3><button class="btn small" id="btnAddChapterOutline">＋ 添加章节</button></div>
      <table class="table"><thead><tr><th style="width:40px">#</th><th style="width:180px">标题</th><th>剧情</th><th style="width:200px">关键事件（逗号分隔）</th><th style="width:160px">章末钩子</th><th></th></tr></thead>
      <tbody>${o.chapters.map((c, i) => `<tr>
        <td>${c.index}</td>
        <td><input type="text" data-oc="${i}" data-k="title" value="${esc(c.title)}"></td>
        <td><textarea data-oc="${i}" data-k="summary" style="min-height:70px">${esc(c.summary)}</textarea></td>
        <td><textarea data-oc="${i}" data-k="key_events" style="min-height:70px">${esc(c.key_events.join('，'))}</textarea></td>
        <td><textarea data-oc="${i}" data-k="hook" style="min-height:70px">${esc(c.hook)}</textarea></td>
        <td><button class="btn small danger ghost" data-del-oc="${i}">删</button></td></tr>`).join('')}</tbody></table></div>`;
    bindOutline();
  }

  function collectOutline() {
    const o = JSON.parse(JSON.stringify(state.project.outline));
    o.title = $('o_title').value.trim(); o.logline = $('o_logline').value.trim();
    ['synopsis', 'world_setting', 'character_bible'].forEach((k) => (o[k] = $(`o_${k}`).value));
    document.querySelectorAll('[data-oc]').forEach((el) => {
      const c = o.chapters[+el.dataset.oc];
      if (el.dataset.k === 'key_events') c.key_events = el.value.split(/[,，;；\n]/).map((x) => x.trim()).filter(Boolean);
      else c[el.dataset.k] = el.value.trim();
    });
    o.chapters.forEach((c, i) => (c.index = i + 1));
    return o;
  }

  function bindOutline() {
    $('btnGenOutline').onclick = async () => {
      if (state.project.outline && !(await confirmDialog('重新生成大纲', '<p class="hint">重新生成会覆盖当前大纲（已写好的章节正文会保留，但可能与新大纲不一致）。</p>'))) return;
      await runJob(api('POST', `/projects/${state.project.id}/outline/generate`));
    };
    const save = async () => { try { state.project = await api('PUT', `/projects/${state.project.id}/outline`, collectOutline()); await loadProjects(); return true; } catch (e) { toast(e.message, 'error'); return false; } };
    if ($('btnSaveOutline')) $('btnSaveOutline').onclick = async () => { if (await save()) { toast('大纲已保存', 'ok'); renderOutline(); } };
    if ($('btnGoChapters')) $('btnGoChapters').onclick = async () => { if (await save()) { state.step = 'chapters'; render(); } };
    if ($('btnAddChapterOutline')) $('btnAddChapterOutline').onclick = () => { const o = collectOutline(); o.chapters.push({ index: o.chapters.length + 1, title: `第${o.chapters.length + 1}章`, summary: '', key_events: [], characters: [], hook: '' }); state.project.outline = o; renderOutline(); };
    document.querySelectorAll('[data-del-oc]').forEach((b) => { b.onclick = () => { const o = collectOutline(); o.chapters.splice(+b.dataset.delOc, 1); o.chapters.forEach((c, i) => (c.index = i + 1)); state.project.outline = o; renderOutline(); }; });
  }

  // ---------------- 3. 章节 ----------------
  function renderChapters() {
    const p = state.project;
    if (!p.outline) { $('main').innerHTML = '<div class="card"><h2>3. 章节正文</h2><div class="empty">请先在「大纲」生成或填写大纲。</div></div>'; return; }
    const chapters = p.chapters.length ? p.chapters : p.outline.chapters.map((c) => ({ index: c.index, title: c.title, text: '', draft_text: '', summary: '', status: 'empty' }));
    if (!chapters.some((c) => c.index === state.chapterIndex)) state.chapterIndex = chapters[0].index;
    const ch = chapters.find((c) => c.index === state.chapterIndex);
    const statusChip = (st) => st === 'humanized' ? '<span class="chip ok">已去AI味</span>' : st === 'drafted' ? '<span class="chip warn">初稿</span>' : '<span class="chip">未写</span>';
    const missing = chapters.filter((c) => c.status === 'empty').length;
    $('main').innerHTML = `
      <div class="card"><div class="card-head"><div><h2>3. 章节正文</h2><p class="hint">逐章生成：依据大纲 + 角色圣经 + 前情摘要写初稿，再做「去 AI 味」改写。可在右侧直接编辑正文。</p></div>
        <div class="actions"><label class="chip" style="cursor:pointer"><input type="checkbox" id="optHumanize" checked> 生成后自动去 AI 味</label>
        <button class="btn primary" id="btnGenAllChapters" ${missing ? '' : 'disabled'}>一键生成剩余 ${missing} 章</button>
        <button class="btn" id="btnGoVisual">下一步：角色与分镜 →</button></div></div></div>
      <div class="layout-split">
        <div class="card"><h4>章节列表</h4><div class="chapter-list">${chapters.map((c) => `<div class="chapter-item ${c.index === state.chapterIndex ? 'active' : ''}" data-ch="${c.index}"><span class="ttl">${c.index}. ${esc(c.title || '')}</span><span class="meta">${(c.text || c.draft_text || '').replace(/\s/g, '').length} 字</span>${statusChip(c.status)}</div>`).join('')}</div></div>
        <div class="card">
          <div class="card-head"><div><h3>第 ${ch.index} 章 ${statusChip(ch.status)}</h3></div>
            <div class="actions">
              <button class="btn ${ch.status === 'empty' ? 'primary' : ''}" id="btnGenChapter">${ch.status === 'empty' ? '生成本章' : '重新生成本章'}</button>
              <button class="btn" id="btnHumanize" ${ch.status === 'empty' ? 'disabled' : ''}>去 AI 味改写（基于当前）</button>
              <button class="btn ghost" id="btnHumanizeDraft" ${ch.draft_text ? '' : 'disabled'}>基于初稿重新改写</button>
              <button class="btn ghost" id="btnViewDraft" ${ch.draft_text ? '' : 'disabled'}>查看初稿</button>
              <button class="btn primary" id="btnSaveChapter">保存</button></div></div>
          <label class="field">标题<input type="text" id="c_title" value="${esc(ch.title)}"></label>
          <label class="field" style="margin-top:8px">正文（${(ch.text || '').replace(/\s/g, '').length} 字）<textarea id="c_text" class="tall prose">${esc(ch.text)}</textarea></label>
          <label class="field" style="margin-top:8px">前情摘要（供后续章节参考）<textarea id="c_summary">${esc(ch.summary)}</textarea></label>
        </div></div>`;

    document.querySelectorAll('[data-ch]').forEach((el) => { el.onclick = () => { state.chapterIndex = +el.dataset.ch; renderChapters(); }; });
    const pid = p.id;
    $('btnGenAllChapters').onclick = async () => {
      const ok = await confirmDialog('一键生成剩余章节', `<p class="hint">将生成 ${missing} 章正文${$('optHumanize').checked ? '并逐章去 AI 味' : ''}。每章约 ${$('optHumanize').checked ? 3 : 2} 次模型调用（初稿 + 摘要${$('optHumanize').checked ? ' + 改写' : ''}），请确认。</p>`);
      if (ok) await runJob(api('POST', `/projects/${pid}/chapters/generate-all`, { humanize: $('optHumanize').checked, only_missing: true }));
    };
    $('btnGenChapter').onclick = async () => {
      if (ch.status !== 'empty' && !(await confirmDialog('重新生成本章', '<p class="hint">将覆盖本章当前正文与初稿。</p>'))) return;
      await runJob(api('POST', `/projects/${pid}/chapters/${ch.index}/generate`, { humanize: $('optHumanize').checked }));
    };
    $('btnHumanize').onclick = async () => { if (await saveChapter(ch.index, true)) await runJob(api('POST', `/projects/${pid}/chapters/${ch.index}/humanize`, { source: 'current' })); };
    $('btnHumanizeDraft').onclick = async () => runJob(api('POST', `/projects/${pid}/chapters/${ch.index}/humanize`, { source: 'draft' }));
    $('btnViewDraft').onclick = () => modal(`第 ${ch.index} 章初稿（去 AI 味之前）`, `<textarea class="tall prose" readonly>${esc(ch.draft_text)}</textarea>`);
    $('btnSaveChapter').onclick = async () => { if (await saveChapter(ch.index)) { toast('已保存', 'ok'); renderChapters(); } };
    $('btnGoVisual').onclick = () => { state.step = 'visual'; render(); };
  }

  async function saveChapter(index, silent = false) {
    try {
      await api('PUT', `/projects/${state.project.id}/chapters/${index}`, { title: $('c_title').value.trim(), text: $('c_text').value, summary: $('c_summary').value });
      await loadProject(state.project.id, false);
      return true;
    } catch (e) { toast(e.message, 'error'); return false; }
  }

  // ---------------- 4. 角色与分镜 ----------------
  function renderVisual() {
    const p = state.project;
    const written = p.chapters.filter((c) => c.status !== 'empty');
    if (!written.length) { $('main').innerHTML = '<div class="card"><h2>4. 角色与分镜</h2><div class="empty">请先生成至少一章正文。</div></div>'; return; }
    if (!written.some((c) => c.index === state.visualChapter)) state.visualChapter = written[0].index;
    const v = p.visuals[state.visualChapter] || p.visuals[String(state.visualChapter)];
    const missingPlans = written.filter((c) => !(p.visuals[c.index] || p.visuals[String(c.index)])).length;
    $('main').innerHTML = `
      <div class="card"><div class="card-head"><div><h2>4. 角色设定与分镜提示词</h2><p class="hint">第二个模型（分镜模型）为每章生成：角色设定图提示词（全局复用，保证跨章节一致）、场景图、道具图、分镜首帧图与每个镜头的视频提示词。全部可编辑。</p></div>
        <div class="actions"><button class="btn" id="btnGoImages">下一步：图片生成 →</button></div></div></div>
      <div class="card"><div class="card-head"><h3>角色设定图提示词（全局）</h3><div class="actions"><button class="btn ${p.character_sheets.length ? '' : 'primary'}" id="btnGenChars">${p.character_sheets.length ? '重新生成角色设定' : '生成角色设定'}</button><button class="btn" id="btnSaveChars" ${p.character_sheets.length ? '' : 'disabled'}>保存角色设定</button></div></div>
        <div class="grid-2">${p.character_sheets.map((c, i) => `<div class="char-card"><div class="head"><b>${esc(c.name)}</b>${c.asset ? '<span class="chip ok">已出图</span>' : ''}</div>
          <label class="field">外貌关键词（会复述到每个分镜提示词中）<textarea data-cs="${i}" data-k="description" style="min-height:60px">${esc(c.description)}</textarea></label>
          <label class="field" style="margin-top:6px">设定图提示词<textarea data-cs="${i}" data-k="image_prompt">${esc(c.image_prompt)}</textarea></label></div>`).join('') || '<div class="empty">还没有角色设定。点击「生成角色设定」。</div>'}</div></div>
      <div class="card"><div class="card-head"><div><h3>分镜方案</h3></div>
        <div class="actions"><select id="visualChapterSel">${written.map((c) => `<option value="${c.index}" ${c.index === state.visualChapter ? 'selected' : ''}>第 ${c.index} 章 ${esc(c.title)} ${(p.visuals[c.index] || p.visuals[String(c.index)]) ? '✓' : ''}</option>`).join('')}</select>
          <button class="btn ${v ? '' : 'primary'}" id="btnGenVisual">${v ? '重新生成本章分镜' : '生成本章分镜'}</button>
          <button class="btn" id="btnGenVisualAll" ${missingPlans ? '' : 'disabled'}>为剩余 ${missingPlans} 章生成分镜</button>
          ${v ? '<button class="btn primary" id="btnSaveVisual">保存本章分镜</button>' : ''}</div></div>
        ${v ? visualPlanHtml(v) : '<div class="empty">本章还没有分镜。</div>'}</div>`;

    const pid = p.id;
    $('btnGoImages').onclick = () => { state.step = 'images'; render(); };
    $('btnGenChars').onclick = async () => runJob(api('POST', `/projects/${pid}/characters/generate`));
    $('btnSaveChars').onclick = async () => {
      const list = JSON.parse(JSON.stringify(p.character_sheets));
      document.querySelectorAll('[data-cs]').forEach((el) => (list[+el.dataset.cs][el.dataset.k] = el.value.trim()));
      try { await api('PUT', `/projects/${pid}/characters`, list); await loadProject(pid, false); toast('已保存', 'ok'); renderVisual(); } catch (e) { toast(e.message, 'error'); }
    };
    $('visualChapterSel').onchange = (e) => { state.visualChapter = +e.target.value; renderVisual(); };
    $('btnGenVisual').onclick = async () => {
      if (v && !(await confirmDialog('重新生成本章分镜', '<p class="hint">会覆盖本章的场景/道具/镜头提示词，已生成的图片会丢失关联。</p>'))) return;
      await runJob(api('POST', `/projects/${pid}/chapters/${state.visualChapter}/visual/generate`));
    };
    $('btnGenVisualAll').onclick = async () => runJob(api('POST', `/projects/${pid}/visual/generate-all`, { only_missing: true }));
    if (v) {
      $('btnSaveVisual').onclick = async () => {
        const plan = collectVisual(v);
        try { await api('PUT', `/projects/${pid}/chapters/${state.visualChapter}/visual`, plan); await loadProject(pid, false); toast('已保存', 'ok'); renderVisual(); } catch (e) { toast(e.message, 'error'); }
      };
      document.querySelectorAll('[data-add-shot]').forEach((b) => { b.onclick = () => { const plan = collectVisual(v); plan.shots.push({ id: `sh_${Math.random().toString(36).slice(2, 14)}`, index: plan.shots.length + 1, scene: '', characters: [], action: '', dialogue: '', camera: '', duration_sec: p.settings.shot_duration_sec, image_prompt: '', video_prompt: '', image: null, video: null }); p.visuals[state.visualChapter] = plan; renderVisual(); }; });
      document.querySelectorAll('[data-del-shot]').forEach((b) => { b.onclick = () => { const plan = collectVisual(v); plan.shots.splice(+b.dataset.delShot, 1); plan.shots.forEach((s, i) => (s.index = i + 1)); p.visuals[state.visualChapter] = plan; renderVisual(); }; });
    }
  }

  function visualPlanHtml(v) {
    const itemList = (items, kind, label) => `<h4 style="margin-top:12px">${label}（${items.length}）</h4><div class="grid-2">${items.map((it, i) => `<div class="char-card"><div class="head"><input type="text" data-vi="${kind}" data-i="${i}" data-k="name" value="${esc(it.name)}" style="width:60%">${it.asset ? '<span class="chip ok">已出图</span>' : ''}</div>
      <label class="field">说明<input type="text" data-vi="${kind}" data-i="${i}" data-k="description" value="${esc(it.description)}"></label>
      <label class="field" style="margin-top:6px">图片提示词<textarea data-vi="${kind}" data-i="${i}" data-k="image_prompt">${esc(it.image_prompt)}</textarea></label></div>`).join('') || '<div class="empty">无</div>'}</div>`;
    const shots = v.shots.map((s, i) => `<div class="shot-card"><div>
        <div class="head"><b>镜头 ${s.index}</b><span>${s.image ? '<span class="chip ok">有首帧</span>' : '<span class="chip">无首帧</span>'}${s.video ? '<span class="chip ok">有视频</span>' : ''}<button class="btn small danger ghost" data-del-shot="${i}">删除</button></span></div>
        <div class="thumb" style="margin-top:8px">${s.image ? `<img src="${fileUrl(s.image)}" loading="lazy">` : '尚未生成首帧'}</div></div>
      <div class="fields">
        <label class="field">场景<input type="text" data-shot="${i}" data-k="scene" value="${esc(s.scene)}"></label>
        <label class="field">出场角色（逗号分隔）<input type="text" data-shot="${i}" data-k="characters" value="${esc(s.characters.join('，'))}"></label>
        <label class="field">景别 / 运镜<input type="text" data-shot="${i}" data-k="camera" value="${esc(s.camera)}"></label>
        <label class="field">时长（秒）<select data-shot="${i}" data-k="duration_sec"><option value="5" ${s.duration_sec === 5 ? 'selected' : ''}>5</option><option value="10" ${s.duration_sec === 10 ? 'selected' : ''}>10</option></select></label>
        <label class="field full">画面内容<input type="text" data-shot="${i}" data-k="action" value="${esc(s.action)}"></label>
        <label class="field full">台词<input type="text" data-shot="${i}" data-k="dialogue" value="${esc(s.dialogue)}"></label>
        <label class="field full">首帧图提示词<textarea data-shot="${i}" data-k="image_prompt">${esc(s.image_prompt)}</textarea></label>
        <label class="field full">视频提示词（图生视频）<textarea data-shot="${i}" data-k="video_prompt" style="min-height:60px">${esc(s.video_prompt)}</textarea></label>
      </div></div>`).join('');
    return `${itemList(v.scenes, 'scenes', '场景')}${itemList(v.props, 'props', '道具')}
      <div class="card-head" style="margin-top:14px"><h4>分镜镜头（${v.shots.length}，合计 ${v.shots.reduce((a, s) => a + s.duration_sec, 0)} 秒）</h4><button class="btn small" data-add-shot>＋ 添加镜头</button></div>${shots}
      <label class="field" style="margin-top:8px">导演备注<textarea id="v_notes" style="min-height:50px">${esc(v.notes)}</textarea></label>`;
  }

  function collectVisual(v) {
    const plan = JSON.parse(JSON.stringify(v));
    document.querySelectorAll('[data-vi]').forEach((el) => (plan[el.dataset.vi][+el.dataset.i][el.dataset.k] = el.value.trim()));
    document.querySelectorAll('[data-shot]').forEach((el) => {
      const s = plan.shots[+el.dataset.shot];
      const k = el.dataset.k;
      if (k === 'characters') s.characters = el.value.split(/[,，、;；]/).map((x) => x.trim()).filter(Boolean);
      else if (k === 'duration_sec') s.duration_sec = +el.value;
      else s[k] = el.value.trim();
    });
    plan.notes = $('v_notes') ? $('v_notes').value : plan.notes;
    plan.shots.forEach((s, i) => (s.index = i + 1));
    return plan;
  }

  // ---------------- 5. 图片 ----------------
  function renderImages() {
    const p = state.project;
    const chapterKeys = Object.keys(p.visuals || {}).map(Number).sort((a, b) => a - b);
    if (!chapterKeys.length && !p.character_sheets.length) { $('main').innerHTML = '<div class="card"><h2>5. 图片生成</h2><div class="empty">请先在「角色与分镜」生成提示词。</div></div>'; return; }
    const kindsLabel = { characters: '角色设定图', scenes: '场景图', props: '道具图', storyboard: '分镜首帧图' };
    const ratio = p.settings.aspect_ratio;
    $('main').innerHTML = `
      <div class="card"><div class="card-head"><div><h2>5. 图片生成</h2><p class="hint">当前图片厂商：<b>${esc(PROVIDER_LABEL[state.config.selection.image_provider])}</b>（${esc(state.config.models.wanx)} / ${esc(state.config.models.jimeng_image)}）。先看预估数量，再点击生成。单张可随时重新生成。</p></div>
        <div class="actions"><button class="btn" id="btnGoVideo">下一步：视频与剧集 →</button></div></div>
        <div class="row" style="align-items:flex-end">
          <label class="field">范围<select id="imgChapter"><option value="all" ${state.imageChapter === 'all' ? 'selected' : ''}>全部章节</option>${chapterKeys.map((k) => `<option value="${k}" ${String(state.imageChapter) === String(k) ? 'selected' : ''}>第 ${k} 章</option>`).join('')}</select></label>
          <div class="field">类型<div style="display:flex;gap:8px;flex-wrap:wrap;padding-top:6px">${Object.entries(kindsLabel).map(([k, l]) => `<label class="chip" style="cursor:pointer"><input type="checkbox" data-kind="${k}" ${state.imageKinds.includes(k) ? 'checked' : ''}> ${l}</label>`).join('')}</div></div>
          <label class="field">&nbsp;<label class="chip" style="cursor:pointer"><input type="checkbox" id="imgOnlyMissing" checked> 只生成缺失的</label></label>
          <button class="btn primary" id="btnGenImages">预估并生成图片</button></div>
        <div class="estimate" id="imgEstimate"></div></div>
      ${gallery('角色设定图', p.character_sheets.map((c) => ({ id: c.id, name: c.name, prompt: c.image_prompt, asset: c.asset, portrait: true })))}
      ${chapterKeys.filter((k) => state.imageChapter === 'all' || String(k) === String(state.imageChapter)).map((k) => { const v = p.visuals[k]; return gallery(`第 ${k} 章 · 场景`, v.scenes.map((x) => ({ id: x.id, name: x.name, prompt: x.image_prompt, asset: x.asset }))) + gallery(`第 ${k} 章 · 道具`, v.props.map((x) => ({ id: x.id, name: x.name, prompt: x.image_prompt, asset: x.asset }))) + gallery(`第 ${k} 章 · 分镜首帧`, v.shots.map((s) => ({ id: s.id, name: `镜头 ${s.index}`, prompt: s.image_prompt, asset: s.image }))); }).join('')}`;

    const pid = p.id;
    const body = () => ({ chapter_index: state.imageChapter === 'all' ? null : +state.imageChapter, kinds: state.imageKinds, only_missing: $('imgOnlyMissing').checked });
    const refreshEstimate = async () => { try { const e = await api('POST', `/projects/${pid}/images/estimate`, body()); $('imgEstimate').innerHTML = estimateHtml([[e.count, '待生成图片数'], [e.by_kind.characters, '角色'], [e.by_kind.scenes, '场景'], [e.by_kind.props, '道具'], [e.by_kind.storyboard, '分镜首帧'], [`≈ ¥${e.estimated_cost_cny}`, `预估费用（单价 ¥${e.unit_cost_cny}/张，可在 .env 修改）`]]); } catch (e) { $('imgEstimate').textContent = e.message; } };
    $('imgChapter').onchange = (e) => { state.imageChapter = e.target.value; renderImages(); };
    document.querySelectorAll('[data-kind]').forEach((cb) => { cb.onchange = () => { state.imageKinds = [...document.querySelectorAll('[data-kind]:checked')].map((x) => x.dataset.kind); refreshEstimate(); }; });
    $('imgOnlyMissing').onchange = refreshEstimate;
    $('btnGenImages').onclick = async () => {
      const e = await api('POST', `/projects/${pid}/images/estimate`, body()).catch((err) => { toast(err.message, 'error'); return null; });
      if (!e) return;
      if (!e.count) { toast('没有需要生成的图片'); return; }
      const mock = state.config.selection.image_provider === 'mock';
      if (await confirmDialog('确认生成图片', `<p class="hint">将调用 <b>${esc(PROVIDER_LABEL[state.config.selection.image_provider])}</b> 生成 <b>${e.count}</b> 张图片${mock ? '（模拟模式，不产生费用）' : `，预估费用约 <b>¥${e.estimated_cost_cny}</b>`}。</p>`)) await runJob(api('POST', `/projects/${pid}/images/generate`, body()));
    };
    document.querySelectorAll('[data-regen]').forEach((b) => { b.onclick = async () => { if (await confirmDialog('重新生成这张图', '<p class="hint">将重新生成这一张图片并替换（若是分镜首帧，对应镜头的视频也需要重做）。</p>')) await runJob(api('POST', `/projects/${pid}/images/generate`, { chapter_index: null, kinds: ['characters', 'scenes', 'props', 'storyboard'], only_missing: false, item_ids: [b.dataset.regen] })); }; });
    document.querySelectorAll('[data-view]').forEach((img) => { img.onclick = () => modal(img.alt, `<img src="${img.src}" style="max-width:100%"><p class="hint" style="margin-top:8px">${esc(img.dataset.prompt)}</p>`); });
    $('btnGoVideo').onclick = () => { state.step = 'video'; render(); };
    refreshEstimate();
  }

  function gallery(title, items) {
    if (!items.length) return '';
    return `<div class="card"><h3>${esc(title)}（${items.filter((i) => i.asset).length}/${items.length} 已出图）</h3><div class="media-grid">${items.map((it) => `<div class="media-card ${it.portrait ? 'portrait' : ''}">
      <div class="thumb">${it.asset ? `<img src="${fileUrl(it.asset)}" alt="${esc(it.name)}" data-view data-prompt="${esc(it.prompt)}" loading="lazy" style="cursor:zoom-in">` : '未生成'}</div>
      <div class="body"><div class="name">${esc(it.name)}</div><div style="color:var(--muted);font-size:12px;max-height:54px;overflow:hidden">${esc(it.prompt)}</div>
      <div class="foot">${it.asset ? `<a class="btn small ghost" href="${fileUrl(it.asset)}" target="_blank">打开</a>` : ''}<button class="btn small" data-regen="${it.id}">${it.asset ? '重新生成' : '生成'}</button></div></div></div>`).join('')}</div></div>`;
  }

  function estimateHtml(items) {
    return items.map(([v, l]) => `<div class="item"><b>${esc(v)}</b><span>${esc(l)}</span></div>`).join('');
  }

  // ---------------- 6. 视频与剧集 ----------------
  async function renderVideo() {
    const p = state.project;
    const main = $('main');
    const vp = state.config.selection.video_provider;
    main.innerHTML = `
      <div class="card"><div class="card-head"><div><h2>6. 视频与剧集</h2><p class="hint">剧集按章节划分（默认 1 章 = 1 集）。每集的视频生成需<b>手动触发</b>，执行前会显示镜头数量与预估费用。当前视频厂商：<b>${esc(PROVIDER_LABEL[vp])}</b>（${esc(vp === 'kling' ? state.config.models.kling : vp === 'jimeng' ? state.config.models.jimeng_video : 'mock')}）。</p></div>
        <div class="actions"><label class="field">每集章节数<input type="number" id="cpe" min="1" value="${p.settings.chapters_per_episode}" style="width:90px"></label><button class="btn ${p.episodes.length ? '' : 'primary'}" id="btnDefineEpisodes">${p.episodes.length ? '重新划分剧集' : '划分剧集'}</button></div></div></div>
      <div id="episodeList">${p.episodes.length ? '' : '<div class="empty">还没有划分剧集。点击「划分剧集」。</div>'}</div>`;
    $('btnDefineEpisodes').onclick = async () => {
      if (p.episodes.length && !(await confirmDialog('重新划分剧集', '<p class="hint">章节分组不变的剧集会保留已拼接的成片。</p>'))) return;
      try { await api('POST', `/projects/${p.id}/episodes/define`, { chapters_per_episode: +$('cpe').value || 1 }); await loadProject(p.id); } catch (e) { toast(e.message, 'error'); }
    };
    if (!p.episodes.length) return;
    const estimates = await Promise.all(p.episodes.map((e) => api('GET', `/projects/${p.id}/episodes/${e.index}/estimate`).catch(() => null)));
    $('episodeList').innerHTML = p.episodes.map((ep, i) => episodeHtml(ep, estimates[i])).join('');
    p.episodes.forEach((ep, i) => {
      const est = estimates[i];
      const g = (id) => $(`${id}_${ep.index}`);
      g('epTitle').onchange = async () => { const list = JSON.parse(JSON.stringify(p.episodes)); list[i].title = g('epTitle').value.trim(); try { await api('PUT', `/projects/${p.id}/episodes`, list); await loadProject(p.id, false); toast('已保存', 'ok'); } catch (e) { toast(e.message, 'error'); } };
      g('btnGenVideos').onclick = async () => {
        if (!est) return;
        if (est.shots_missing_image) { toast(`还有 ${est.shots_missing_image} 个镜头没有首帧图，请先到「图片生成」出图`, 'error'); return; }
        const mock = vp === 'mock';
        const ok = await confirmDialog(`生成第 ${ep.index} 集视频`, `<div class="estimate">${estimateHtml([[est.pending_video_count, '待生成视频段数'], [`${est.pending_video_seconds} 秒`, '合计时长'], [mock ? '¥0' : `≈ ¥${est.estimated_cost_cny}`, `预估费用（单价 ¥${est.unit_cost_cny}/段）`]])}</div><p class="hint">厂商：<b>${esc(PROVIDER_LABEL[vp])}</b>${mock ? '（模拟模式）' : ''}。视频生成较慢，每段通常需 1~5 分钟，请耐心等待。</p>`);
        if (ok) await runJob(api('POST', `/projects/${p.id}/episodes/${ep.index}/videos/generate`, { only_missing: true }));
      };
      g('btnRender').onclick = async () => runJob(api('POST', `/projects/${p.id}/episodes/${ep.index}/render`));
      document.querySelectorAll(`[data-regen-shot-ep="${ep.index}"]`).forEach((b) => { b.onclick = async () => { if (await confirmDialog('重新生成这段视频', '<p class="hint">将重新调用视频厂商生成这个镜头的视频并替换。</p>')) await runJob(api('POST', `/projects/${p.id}/episodes/${ep.index}/videos/generate`, { only_missing: false, shot_ids: [b.dataset.shot] })); }; });
    });
  }

  function episodeHtml(ep, est) {
    const p = state.project;
    const shots = ep.chapter_indices.flatMap((ci) => ((p.visuals[ci] || p.visuals[String(ci)] || { shots: [] }).shots.map((s) => ({ ci, s }))));
    const statusChip = { pending: '<span class="chip">未开始</span>', videos_partial: '<span class="chip warn">部分视频</span>', videos_done: '<span class="chip ok">视频齐全</span>', rendered: '<span class="chip ok">已成片</span>' }[ep.status];
    return `<div class="episode-card">
      <div class="card-head"><div style="display:flex;align-items:center;gap:10px"><input type="text" id="epTitle_${ep.index}" value="${esc(ep.title)}" style="width:280px">${statusChip}<span class="chip">章节：${ep.chapter_indices.join('、')}</span></div>
        <div class="actions"><button class="btn ${est && est.pending_video_count ? 'primary' : ''}" id="btnGenVideos_${ep.index}" ${est && est.shot_count ? '' : 'disabled'}>生成本集视频（${est ? est.pending_video_count : 0} 段待生成）</button>
        <button class="btn ${est && est.ready_to_render ? 'primary' : ''}" id="btnRender_${ep.index}" ${est && est.ready_to_render ? '' : 'disabled'}>${ep.video ? '重新拼接成片' : '拼接成片'}</button>
        ${ep.video ? `<a class="btn" href="${fileUrl(ep.video)}" download>下载成片</a>` : ''}</div></div>
      ${est ? `<div class="estimate">${estimateHtml([[est.shot_count, '镜头总数'], [est.shots_with_image, '已有首帧'], [est.shots_with_video, '已有视频'], [`${est.total_seconds} 秒`, '成片预计时长'], [`≈ ¥${est.estimated_cost_cny}`, '剩余视频预估费用']])}${est.chapters_without_plan.length ? `<div class="item" style="color:var(--danger)"><b>!</b><span>第 ${est.chapters_without_plan.join('、')} 章还没有分镜</span></div>` : ''}</div>` : ''}
      ${ep.video ? `<video controls src="${fileUrl(ep.video)}"></video>` : ''}
      <details style="margin-top:10px"><summary style="cursor:pointer;color:var(--muted)">镜头列表（${shots.length}）</summary><div class="media-grid" style="margin-top:10px">${shots.map(({ ci, s }) => `<div class="media-card"><div class="thumb">${s.video ? `<video src="${fileUrl(s.video)}" controls preload="metadata"></video>` : s.image ? `<img src="${fileUrl(s.image)}" loading="lazy">` : '无首帧'}</div>
        <div class="body"><div class="name">第 ${ci} 章 · 镜头 ${s.index} · ${s.duration_sec}s</div><div style="color:var(--muted);font-size:12px;max-height:54px;overflow:hidden">${esc(s.video_prompt)}</div>
        <div class="foot">${s.image ? `<button class="btn small" data-regen-shot-ep="${ep.index}" data-shot="${s.id}">${s.video ? '重新生成视频' : '生成视频'}</button>` : ''}</div></div></div>`).join('')}</div></details></div>`;
  }

  // ---------------- 厂商设置 ----------------
  function openSettings() {
    const c = state.config;
    const opts = (kind, field) => c.options[kind].map((o) => `<option value="${o.name}" ${c.selection[field] === o.name ? 'selected' : ''} ${o.available ? '' : 'disabled'}>${PROVIDER_LABEL[o.name] || o.name}${o.available ? '' : '（未配置密钥）'}</option>`).join('');
    const ks = c.key_status;
    const kv = (k, v) => `<div class="k">${k}</div><div>${v}</div>`;
    modal('厂商设置', `
      <p class="hint">密钥只能在项目根目录的 <code>.env</code> 文件中配置（复制 <code>.env.example</code>），修改后需重启程序。这里只切换各阶段使用的厂商。</p>
      <div class="grid-2">
        <label class="field">文本大模型（大纲 / 正文 / 去 AI 味）<select id="s_llm">${opts('llm', 'llm_provider')}</select></label>
        <label class="field">分镜模型（第二个模型：角色/场景/分镜/视频提示词）<select id="s_vllm">${opts('llm', 'visual_llm_provider')}</select></label>
        <label class="field">图片生成<select id="s_img">${opts('image', 'image_provider')}</select></label>
        <label class="field">视频生成<select id="s_vid">${opts('video', 'video_provider')}</select></label>
      </div>
      <h4 style="margin-top:14px">密钥状态（只显示是否已配置）</h4>
      <div class="kv">${kv('DEEPSEEK_API_KEY', ks.deepseek ? '✅ 已配置' : '— 未配置')}${kv('DASHSCOPE_API_KEY', ks.dashscope ? '✅ 已配置（Qwen + 万相）' : '— 未配置')}${kv('VOLC_ACCESS_KEY / SECRET', ks.volc ? '✅ 已配置（即梦）' : '— 未配置')}${kv('KLING_ACCESS_KEY / SECRET', ks.kling ? '✅ 已配置（可灵）' : '— 未配置')}
        ${kv('ffmpeg', c.ffmpeg_ok ? '✅ 可用' : '❌ 未找到，请安装并设置 FFMPEG_PATH')}${kv('数据目录', `<code>${esc(c.data_dir)}</code>`)}
        ${kv('模型', `DeepSeek: ${esc(c.models.deepseek)} · Qwen: ${esc(c.models.qwen)} · 万相: ${esc(c.models.wanx)} · 即梦图: ${esc(c.models.jimeng_image)} · 即梦视频: ${esc(c.models.jimeng_video)} · 可灵: ${esc(c.models.kling)}`)}</div>
      <div style="display:flex;justify-content:flex-end;margin-top:14px"><button class="btn primary" id="btnSaveProviders">保存</button></div>`, (box) => {
      box.querySelector('#btnSaveProviders').onclick = async () => {
        try {
          state.config = await api('PUT', '/config', { llm_provider: $('s_llm').value, visual_llm_provider: $('s_vllm').value, image_provider: $('s_img').value, video_provider: $('s_vid').value });
          renderBadges(); closeModal(); toast('已切换厂商', 'ok'); render();
        } catch (e) { toast(e.message, 'error'); }
      };
    });
  }

  // ------------------------------------------------------------------
  // 事件绑定与启动
  // ------------------------------------------------------------------
  document.querySelectorAll('#stepNav button').forEach((b) => { b.onclick = () => { state.step = b.dataset.step; render(); }; });
  $('projectSelect').onchange = (e) => loadProject(e.target.value).catch((err) => toast(err.message, 'error'));
  $('btnNewProject').onclick = () => {
    modal('新建项目', `<label class="field">项目名称<input type="text" id="np_name" value="我的短剧" autofocus></label><div style="display:flex;justify-content:flex-end;margin-top:12px"><button class="btn primary" id="np_ok">创建</button></div>`, (box) => {
      box.querySelector('#np_ok').onclick = async () => {
        try { const p = await api('POST', '/projects', { name: $('np_name').value.trim() || '未命名项目' }); closeModal(); await loadProjects(); state.step = 'settings'; await loadProject(p.id); } catch (e) { toast(e.message, 'error'); }
      };
    });
  };
  $('btnDeleteProject').onclick = async () => {
    if (!state.project) return;
    if (await confirmDialog('删除项目', `<p class="hint">确定删除「${esc(state.project.name)}」及其所有小说、图片、视频文件？此操作不可恢复。</p>`)) {
      try { await api('DELETE', `/projects/${state.project.id}`); state.project = null; await loadProjects(); await loadProject(state.projects[0]?.id); } catch (e) { toast(e.message, 'error'); }
    }
  };
  $('btnSettings').onclick = openSettings;
  $('modalClose').onclick = closeModal;
  $('modal').onclick = (e) => { if (e.target === $('modal')) closeModal(); };

  (async () => {
    try {
      await loadConfig();
      await loadProjects();
      const last = localStorage.getItem('n2d:lastProject');
      const pick = state.projects.find((p) => p.id === last)?.id || state.projects[0]?.id;
      await loadProject(pick);
      // 若有运行中的任务，接管显示
      if (state.project) {
        const jobs = await api('GET', `/projects/${state.project.id}/jobs`);
        const running = jobs.find((j) => j.status === 'running' || j.status === 'pending');
        if (running) runJob(Promise.resolve(running));
      }
    } catch (e) { toast(`初始化失败：${e.message}`, 'error'); render(); }
  })();
})();
