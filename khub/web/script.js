// ── 核心状态 ──
const box = document.getElementById('results');
let currentPage = 0;
const PER_PAGE = 20;
let lastQuery = '';
let lastSource = '';

// ── 工具函数 ──
function esc(s) { return (s || '').replace(/[&<>]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' }[c])); }

function highlight(s, term) {
  s = esc(s); if (!term) return s;
  const re = new RegExp(esc(term).replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), 'gi');
  return s.replace(re, m => '<mark>' + m + '</mark>');
}

function toast(msg) {
  let el = document.getElementById('toast');
  if (!el) {
    el = document.createElement('div'); el.id = 'toast'; el.className = 'toast';
    document.body.appendChild(el);
  }
  el.textContent = msg; el.classList.add('show');
  setTimeout(() => el.classList.remove('show'), 3000);
}

function renderSkeletons(count, type) {
  box.innerHTML = '';
  const types = { list: 'skeleton-list', detail: 'skeleton-title skeleton-text skeleton-text-short' };
  const classes = types[type] || 'skeleton-list';
  for (let i = 0; i < count; i++) {
    const d = document.createElement('div'); d.className = 'skeleton ' + classes.split(' ')[0];
    if (type === 'detail') { d.className = 'skeleton skeleton-title'; box.appendChild(d);
      for (let j = 0; j < 3; j++) { const s = document.createElement('div'); s.className = 'skeleton skeleton-text'; box.appendChild(s); } }
    else box.appendChild(d);
  }
}

// ── 卡片渲染 ──
function card(d, clickable, highlightTerm) {
  const el = document.createElement('div'); el.className = 'card';
  el.innerHTML = '<h3>' + highlight(d.title || d.doc_id || '', highlightTerm) + '</h3>' +
    (d.snippet ? '<div class="snip">' + highlight(d.snippet, highlightTerm) + '</div>' : '') +
    '<div class="meta">' + esc(d.doc_id || '') + (d.updated_at ? ' · ' + esc(d.updated_at) : '') +
    (d.conflict ? ' <span class="tag">冲突</span>' : '') + '</div>';
  if (clickable && d.doc_id) { el.style.cursor = 'pointer'; el.onclick = () => loadDoc(d.doc_id, d.title); }
  return el;
}

// ── 分页 ──
function renderPagination(total, page, perPage, query, source) {
  const lastPage = Math.max(0, Math.ceil(total / perPage) - 1);
  if (total <= perPage) return null;
  const wrap = document.createElement('div'); wrap.className = 'pagination';
  const from = page * perPage + 1;
  const to = Math.min((page + 1) * perPage, total);
  const go = (p) => { currentPage = p; if (query) search(query, source); };

  const btn = (txt, disabled, fn) => {
    const b = document.createElement('button'); b.textContent = txt;
    if (disabled) b.disabled = true; else b.onclick = fn; return b;
  };
  wrap.appendChild(btn('首页', page === 0, () => go(0)));
  wrap.appendChild(btn('‹ 上一页', page === 0, () => go(page - 1)));
  const info = document.createElement('span'); info.className = 'page-info';
  info.textContent = '第 ' + from + '-' + to + ' / 共 ' + total + ' 篇';
  wrap.appendChild(info);
  wrap.appendChild(btn('下一页 ›', page >= lastPage, () => go(page + 1)));
  wrap.appendChild(btn('末页', page >= lastPage, () => go(lastPage)));
  return wrap;
}

// ── 加载/渲染函数 ──
async function loadDoc(id, title) {
  renderSkeletons(1, 'detail');
  try {
    const r = await fetch('/documents/' + encodeURIComponent(id)).then(x => x.json());
    if (r.error) { box.innerHTML = '<p class="meta">' + esc(r.error) + '</p>'; return; }
    const backLink = '<p style="margin-bottom:8px"><a href="#" onclick="loadAll();return false">← 返回列表</a></p>';
    let html = backLink;
    html += '<div id="doc-header"><h2>' + esc(r.title || id) + '</h2>' +
      '<p class="meta">' + esc(r.canonical_id) + ' · ' + r.version_count + ' 版本 · ' + (r.updated_at || '') + ' · 格式: ' + esc(r.format || '') + '</p>' +
      '<div class="edit-actions"><button onclick="editDoc(\'' + esc(r.canonical_id) + '\',\'' + esc(r.title) + '\')">编辑</button></div></div>';
    if (r.format === 'html') {
      const safe = (r.content || '').replace(/<script[\s\S]*?<\/script>/gi, '');
      html += '<div class="doc-content">' + safe + '</div>';
    } else {
      html += '<div class="doc-content" style="white-space:pre-wrap">' + esc(r.content) + '</div>';
    }
    box.innerHTML = html + backLink;
  } catch (e) { box.innerHTML = '<p class="meta">加载失败: ' + esc(e.message) + '</p>'; }
}

async function search(q, source) {
  if (q === undefined) q = document.getElementById('q').value.trim();
  if (!q) return;
  lastQuery = q;
  lastSource = source !== undefined ? source : document.getElementById('sourceFilter').value;
  renderSkeletons(3, 'list');
  try {
    const r = await fetch('/search?q=' + encodeURIComponent(q) + '&page=' + currentPage + '&per=' + PER_PAGE + '&source=' + encodeURIComponent(lastSource)).then(x => x.json());
    box.innerHTML = '';
    if (!r.total) { box.innerHTML = '<p class="meta">无结果</p>'; return; }
    const h = document.createElement('h2'); h.textContent = '命中 ' + r.total + ' 篇';
    box.appendChild(h);
    r.hits.forEach(d => box.appendChild(card(d, true, q)));
    const pag = renderPagination(r.total, currentPage, PER_PAGE, q, lastSource);
    if (pag) box.appendChild(pag);
  } catch (e) { box.innerHTML = '<p class="meta">搜索失败: ' + esc(e.message) + '</p>'; }
}

async function semantic() {
  const q = document.getElementById('q').value.trim(); if (!q) return;
  renderSkeletons(3, 'list');
  try {
    const r = await fetch('/semantic?q=' + encodeURIComponent(q)).then(x => x.json());
    box.innerHTML = '';
    const h = document.createElement('h2'); h.textContent = '语义检索（向量 / ANN）'; box.appendChild(h);
    if (!r.length) { box.innerHTML += '<p class="meta">无结果</p>'; return; }
    const docs = await fetch('/documents').then(x => x.json());
    const titles = {}; docs.forEach(d => titles[d.canonical_id] = d.title);
    r.forEach(d => {
      const el = document.createElement('div'); el.className = 'card';
      el.innerHTML = '<h3>' + esc(titles[d.doc_id] || d.doc_id) + '</h3><div class="meta">' + esc(d.doc_id) + ' · 相似度 ' + d.score + '</div>';
      el.style.cursor = 'pointer'; el.onclick = () => loadDoc(d.doc_id, titles[d.doc_id] || d.doc_id); box.appendChild(el);
    });
  } catch (e) { box.innerHTML = '<p class="meta">检索失败: ' + esc(e.message) + '</p>'; }
}

async function loadAll() {
  renderSkeletons(3, 'list');
  try {
    const r = await fetch('/documents').then(x => x.json());
    box.innerHTML = '';
    const h = document.createElement('h2'); h.textContent = '全部文档'; box.appendChild(h);
    if (!r.length) { box.innerHTML += '<p class="meta">暂无文档</p>'; return; }
    r.forEach(d => box.appendChild(card({ doc_id: d.canonical_id, title: d.title, updated_at: d.updated_at })));
  } catch (e) { box.innerHTML = '<p class="meta">加载失败: ' + esc(e.message) + '</p>'; }
}

async function loadConflicts() {
  renderSkeletons(3, 'list');
  try {
    const r = await fetch('/conflicts').then(x => x.json());
    box.innerHTML = '';
    const h = document.createElement('h2'); h.textContent = '冲突文档'; box.appendChild(h);
    if (!r.length) { box.innerHTML += '<p class="meta">无冲突</p>'; return; }
    r.forEach(d => box.appendChild(card(d)));
  } catch (e) { box.innerHTML = '<p class="meta">加载失败: ' + esc(e.message) + '</p>'; }
}

async function loadStats() {
  try {
    const r = await fetch('/stats').then(x => x.json());
    const s = document.getElementById('stats');
    let html = '<div class="stat-card" style="background:#e8f5e9;padding:8px 14px;border-radius:8px;text-align:center;min-width:70px"><div style="font-size:20px;font-weight:700">' + r.total + '</div><div style="font-size:11px;color:#555">总计</div></div>';
    const srcMap = { obsidian: '秘方', ima: 'IMA', imanote: 'IMA笔记', quip: 'Quip', library: '电子书' };
    for (const [k, v] of Object.entries(srcMap)) {
      const cnt = r.sources[k] || 0;
      if (cnt > 0) html += '<div class="stat-card" style="background:#e3f2fd;padding:8px 14px;border-radius:8px;text-align:center;min-width:60px"><div style="font-size:16px;font-weight:700">' + cnt + '</div><div style="font-size:11px;color:#555">' + v + '</div></div>';
    }
    html += '<div class="stat-card" style="background:#fff3e0;padding:8px 14px;border-radius:8px;text-align:center;min-width:60px"><div style="font-size:16px;font-weight:700">' + r.today + '</div><div style="font-size:11px;color:#555">今日</div></div>';
    s.innerHTML = html;
  } catch (e) { /* stats optional */ }
}

// ── 文档编辑 ──
function editDoc(id, title) {
  const header = document.getElementById('doc-header');
  const contentEl = box.querySelector('.doc-content');
  const origTitle = title;
  const origContent = contentEl ? contentEl.textContent : '';

  header.querySelector('.edit-actions').innerHTML = '';
  header.querySelector('h2').outerHTML = '<input class="edit-title" id="edit-title" value="' + esc(title) + '">';
  const textarea = document.createElement('textarea');
  textarea.className = 'edit-content'; textarea.value = origContent;
  if (contentEl) contentEl.replaceWith(textarea);

  const actions = document.createElement('div'); actions.className = 'edit-actions';
  actions.innerHTML = '<button onclick="saveDoc(\'' + esc(id) + '\')">保存</button>' +
    '<button class="ghost" onclick="loadDoc(\'' + esc(id) + '\',\'' + esc(title) + '\')">取消</button>';
  header.appendChild(actions);
}

async function saveDoc(id) {
  const title = document.getElementById('edit-title').value.trim();
  const content = document.querySelector('.edit-content').value;
  if (!title) { toast('标题不能为空'); return; }
  try {
    const r = await fetch('/documents/' + encodeURIComponent(id), {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ title: title, content: content })
    });
    const data = await r.json();
    if (r.ok) { toast('保存成功'); loadDoc(id, title); }
    else toast('保存失败: ' + (data.error || r.status));
  } catch (e) { toast('保存失败: ' + e.message); }
}

// ── 冲突解决 ──
async function loadConflictView(id) {
  renderSkeletons(1, 'detail');
  try {
    const doc = await fetch('/documents/' + encodeURIComponent(id)).then(x => x.json());
    if (doc.error) { box.innerHTML = '<p class="meta">' + esc(doc.error) + '</p>'; return; }
    const vers = await fetch('/documents/' + encodeURIComponent(id) + '/versions').then(x => x.json());
    if (vers.length < 2) { box.innerHTML = '<p class="meta">数据异常：冲突标记但只有一个版本</p>'; return; }
    const v1 = vers[vers.length - 2], v2 = vers[vers.length - 1];
    const c1 = await fetch('/documents/' + encodeURIComponent(id) + '/versions/' + v1.version_id).then(x => x.json());
    const c2 = await fetch('/documents/' + encodeURIComponent(id) + '/versions/' + v2.version_id).then(x => x.json());
    const back = '<p><a href="#" onclick="loadConflicts();return false">← 返回冲突列表</a></p>';
    box.innerHTML = back + '<h2>冲突解决：' + esc(doc.title || id) + '</h2>';
    const grid = document.createElement('div'); grid.className = 'conflict-grid';
    [c1, c2].forEach((c, i) => {
      const pane = document.createElement('div'); pane.className = 'conflict-pane';
      pane.innerHTML = '<div class="pane-header">版本 ' + c.version_id + ' · ' + (c.updated_at || '') + '</div>' +
        '<div class="pane-content">' + esc(c.content) + '</div>';
      grid.appendChild(pane);
    });
    box.appendChild(grid);
    const actions = document.createElement('div'); actions.className = 'conflict-actions';
    actions.innerHTML = '<button onclick="resolveVersion(\'' + esc(id) + '\',' + c1.version_id + ')">保留左</button>' +
      '<button onclick="resolveVersion(\'' + esc(id) + '\',' + c2.version_id + ')">保留右</button>' +
      '<button class="ghost" onclick="loadConflicts()">稍后处理</button>';
    box.appendChild(actions);
  } catch (e) { box.innerHTML = '<p class="meta">加载冲突视图失败: ' + esc(e.message) + '</p>'; }
}

async function resolveVersion(id, keepVersionId) {
  try {
    const r = await fetch('/documents/' + encodeURIComponent(id) + '/resolve', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ keep_version: keepVersionId })
    });
    const data = await r.json();
    if (r.ok) { toast('冲突已解决'); loadConflicts(); }
    else toast('解决失败: ' + (data.error || r.status));
  } catch (e) { toast('解决失败: ' + e.message); }
}

// ── AI 助手对话框 ──
const aiState = { open: false, streaming: false, abortController: null };
const aiMsgs = document.getElementById('ai-msgs');
const aiInput = document.getElementById('ai-q');
function aiToggle() {
  aiState.open = !aiState.open;
  document.getElementById('ai-panel').classList.toggle('open', aiState.open);
  if (aiState.open && aiInput) aiInput.focus();
}
function aiAddMsg(role, text, streaming) {
  const d = document.createElement('div');
  d.className = 'msg ' + role;
  if (streaming) d.innerHTML = '<span class="streaming-text">' + esc(text) + '</span>';
  else d.innerHTML = esc(text).replace(/\n/g, '<br>');
  aiMsgs.appendChild(d); aiMsgs.scrollTop = aiMsgs.scrollHeight; return d;
}
function aiAppendToken(msgEl, token) {
  const t = msgEl.querySelector('.streaming-text');
  if (t) t.textContent += token; else msgEl.textContent += token;
  aiMsgs.scrollTop = aiMsgs.scrollHeight;
}
function aiRenderSources(msgEl, sources) {
  if (!sources || !sources.length) return;
  const d = document.createElement('div'); d.className = 'sources';
  d.innerHTML = '📖 ';
  sources.forEach(s => {
    d.innerHTML += '<a href="#" onclick="loadDoc(\'' + esc(s.id) + '\',\'' + esc(s.title) + '\');return false">' + esc(s.title) + '</a><span style="color:#999">(' + s.score + ')</span> ';
  });
  msgEl.appendChild(d);
}
async function aiAsk() {
  const q = aiInput.value.trim();
  if (!q || aiState.streaming) return;
  aiAddMsg('user', q); aiInput.value = '';
  const aiBubble = aiAddMsg('ai', '', true);
  aiState.streaming = true;
  try {
    const resp = await fetch('/ask', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question: q, k: 5, stream: true })
    });
    const reader = resp.body.getReader();
    const decoder = new TextDecoder();
    let buf = '', sourcesReceived = false;
    while (true) {
      const { done, value } = await reader.read(); if (done) break;
      buf += decoder.decode(value, { stream: true });
      const parts = buf.split('\n\n'); buf = parts.pop() || '';
      for (const block of parts) {
        const lines = block.split('\n');
        const ev = lines.find(l => l.startsWith('event: '));
        const dl = lines.find(l => l.startsWith('data: '));
        if (!dl) continue;
        const event = ev ? ev.slice(7).trim() : '';
        const data = JSON.parse(dl.slice(6));
        if (event === 'sources' && !sourcesReceived) { aiRenderSources(aiBubble, data.sources); sourcesReceived = true; }
        else if (event === 'token') { aiAppendToken(aiBubble, data.token); }
        else if (event === 'error') { aiAppendToken(aiBubble, '[错误: ' + data.error + ']'); }
      }
    }
  } catch (e) { aiAppendToken(aiBubble, '[请求失败: ' + e.message + ']'); }
  finally { aiState.streaming = false; }
}

// ── 深色模式 ──
function initTheme() {
  const saved = localStorage.getItem('khub-theme');
  if (saved) document.documentElement.dataset.theme = saved;
}
function toggleTheme() {
  const current = document.documentElement.dataset.theme;
  const next = current === 'dark' ? 'light' : 'dark';
  document.documentElement.dataset.theme = next;
  localStorage.setItem('khub-theme', next);
}

// ── 初始化 ──
initTheme();
loadStats();
document.getElementById('q').addEventListener('keydown', e => { if (e.key === 'Enter') search(); });
document.getElementById('ai-send').addEventListener('click', aiAsk);
aiInput.addEventListener('keydown', e => { if (e.key === 'Enter') aiAsk(); });
loadAll();
