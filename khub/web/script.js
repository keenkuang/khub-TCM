// ── 登录状态管理 ──
function getToken() { return localStorage.getItem('khub_token'); }

// 所有 fetch 调用自动附带 Authorization header
const origFetch = window.fetch;
window.fetch = function(url, opts) {
  opts = opts || {};
  if (!opts.headers) opts.headers = {};
  const token = getToken();
  if (token) opts.headers['Authorization'] = 'Bearer ' + token;
  return origFetch.call(window, url, opts);
};

// 登录检查（首页加载时）
async function checkLogin() {
  const token = getToken();
  if (!token) { window.location.href = '/web/login.html'; return; }
  try {
    const r = await fetch('/auth/me');
    const j = await r.json();
    if (!r.ok) { localStorage.removeItem('khub_token'); window.location.href = '/web/login.html'; }
    if (j.user && j.user.role === 'admin') {
      document.getElementById('adminBtn').style.display = 'inline-block';
    }
  } catch(e) { /* 保留 token 继续尝试 */ }
}

async function logout() {
  const token = getToken();
  if (token) {
    try { await fetch('/auth/logout', {method:'POST'}); } catch(e) {}
  }
  localStorage.removeItem('khub_token');
  localStorage.removeItem('khub_user');
  window.location.href = '/web/login.html';
}

// ── 核心状态 ──
const box = document.getElementById('results');
let currentPage = 0;
const PER_PAGE = 20;
let lastQuery = '';
let lastSource = '';

// ── 工具函数 ──
function esc(s) { return (s || '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c])); }

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
    html += '<div id="doc-header" data-format="' + esc(r.format || 'plain') + '"><h2>' + esc(r.title || id) + '<span class="fav-star" onclick="toggleFav(\'' + esc(id) + '\')">' + (r.favorited ? '★' : '☆') + '</span></h2>' +
      '<p class="meta">' + esc(r.canonical_id) + ' · ' + r.version_count + ' 版本 · ' + (r.updated_at || '') + ' · 格式: ' + esc(r.format || '') + '</p>' +
      '<div class="edit-actions"><button onclick="editDoc(\'' + esc(r.canonical_id) + '\')">编辑</button>' +
      (r.version_count >= 2 ? '<button class="ghost" onclick="loadDiff(\'' + esc(r.canonical_id) + '\',' + r.version_count + ')">比较</button>' : '') +
      '</div></div>' +
      '<div class="doc-tags">' +
      (r.tags ? r.tags.map(t => '<span class="tag-badge">' + esc(t) + ' <a href="#" onclick="removeTag(\'' + esc(id) + "','" + esc(t) + '\');return false">×</a></span>').join('') : '') +
      '<input class="tag-input" placeholder="添加标签" onkeydown="if(event.key===\'Enter\')addTag(\'' + esc(id) + '\',this.value)"></div>';
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
  if (window._searchAbort) window._searchAbort.abort();
  window._searchAbort = new AbortController();
  if (q === undefined) q = document.getElementById('q').value.trim();
  if (!q) return;
  currentPage = 0;  // 新查询重置分页
  lastQuery = q;
  lastSource = source !== undefined ? source : document.getElementById('sourceFilter').value;
  renderSkeletons(3, 'list');
  try {
    const tagVal = document.getElementById('tagFilter') ? document.getElementById('tagFilter').value : '';
    const r = await fetch('/search?q=' + encodeURIComponent(q) + '&page=' + currentPage + '&per=' + PER_PAGE + '&source=' + encodeURIComponent(lastSource) + '&tag=' + encodeURIComponent(tagVal), { signal: window._searchAbort.signal }).then(x => x.json());
    box.innerHTML = '';
    if (!r.total) { box.innerHTML = '<p class="meta">无结果</p>'; return; }
    const h = document.createElement('h2'); h.textContent = '命中 ' + r.total + ' 篇';
    box.appendChild(h);
    r.hits.forEach(d => box.appendChild(card(d, true, q)));
    const pag = renderPagination(r.total, currentPage, PER_PAGE, q, lastSource);
    if (pag) box.appendChild(pag);
  } catch (e) { if (e.name !== 'AbortError') box.innerHTML = '<p class="meta">搜索失败: ' + esc(e.message) + '</p>'; }
}

async function semantic() {
  if (window._searchAbort) window._searchAbort.abort();
  window._searchAbort = new AbortController();
  const q = document.getElementById('q').value.trim(); if (!q) return;
  renderSkeletons(3, 'list');
  try {
    const r = await fetch('/semantic?q=' + encodeURIComponent(q), { signal: window._searchAbort.signal }).then(x => x.json());
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
  } catch (e) { if (e.name !== 'AbortError') box.innerHTML = '<p class="meta">检索失败: ' + esc(e.message) + '</p>'; }
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

async function loadSyncStatus() {
  renderSkeletons(3, 'list');
  try {
    const r = await fetch('/sync-status').then(x => x.json());
    box.innerHTML = '<h2>数据源同步状态</h2>';
    if (!r.length) { box.innerHTML += '<p class="meta">暂无同步记录</p>'; return; }
    const table = document.createElement('table');
    table.style.cssText = 'width:100%;border-collapse:collapse;margin-top:8px';
    table.innerHTML = '<thead><tr style="background:var(--card-bg,#f5f5f7)">' +
      '<th style="padding:8px;text-align:left;border-bottom:2px solid #ddd">来源</th>' +
      '<th style="padding:8px;text-align:left;border-bottom:2px solid #ddd">方向</th>' +
      '<th style="padding:8px;text-align:left;border-bottom:2px solid #ddd">最后同步</th>' +
      '<th style="padding:8px;text-align:left;border-bottom:2px solid #ddd">状态</th></tr></thead><tbody>';
    r.forEach(s => {
      const color = s.recent ? '#22c55e' : (s.last_sync_at ? '#f97316' : '#9ca3af');
      const label = s.recent ? '正常' : (s.last_sync_at ? '过期' : '从未同步');
      const dirMap = { pull: '拉取', push: '推送', both: '双向' };
      table.innerHTML += '<tr style="border-bottom:1px solid #eee">' +
        '<td style="padding:8px">' + esc(s.source_id) + '</td>' +
        '<td style="padding:8px">' + (dirMap[s.direction] || s.direction) + '</td>' +
        '<td style="padding:8px;color:#666">' + (s.last_sync_at || '-') + '</td>' +
        '<td style="padding:8px"><span style="display:inline-block;width:10px;height:10px;border-radius:50%;background:' + color + ';margin-right:6px;vertical-align:middle"></span>' +
        '<span style="vertical-align:middle">' + label + '</span></td></tr>';
    });
    table.innerHTML += '</tbody>';
    box.appendChild(table);
  } catch (e) { box.innerHTML = '<p class="meta">加载失败: ' + esc(e.message) + '</p>'; }
}

async function loadStats() {
  try {
    const r = await fetch('/stats').then(x => x.json());
    const s = document.getElementById('stats');

    // 【顶部数字卡片】
    const card = (label, value, bg) => '<div class="stat-card" style="background:' + bg + ';padding:8px 14px;border-radius:8px;text-align:center;min-width:70px"><div style="font-size:20px;font-weight:700">' + value + '</div><div style="font-size:11px;color:#555">' + label + '</div></div>';
    let html = card('总计', r.total, '#e8f5e9') + card('今日', r.today, '#fff3e0') +
      card('版本', r.versions, '#e3f2fd') + card('向量', r.embeddings, '#f3e5f5') +
      (r.conflicts ? card('冲突', r.conflicts, '#ffe0e0') : '');
    s.innerHTML = html;

    // 【来源分布 — SVG 条形图】
    const srcMap = { obsidian: '秘方', ima: 'IMA', imanote: 'IMA笔记', quip: 'Quip', library: '电子书', kzocr: 'KZOCR', feishu: '飞书', webui: 'WebUI' };
    const srcKeys = Object.keys(srcMap).filter(k => r.sources[k]);
    if (srcKeys.length) {
      const maxVal = Math.max(...srcKeys.map(k => r.sources[k]));
      let barHtml = '<div style="margin-top:14px"><h2 style="margin:0 0 6px">来源分布</h2><div style="display:flex;flex-direction:column;gap:4px">';
      srcKeys.forEach(k => {
        const pct = Math.round((r.sources[k] / maxVal) * 100);
        barHtml += '<div style="display:flex;align-items:center;gap:8px;font-size:13px">' +
          '<span style="width:48px;text-align:right;color:#555">' + (srcMap[k] || k) + '</span>' +
          '<div style="flex:1;height:20px;background:#e5e7eb;border-radius:4px;overflow:hidden">' +
          '<div style="width:' + pct + '%;height:100%;background:#2563eb;border-radius:4px;display:flex;align-items:center;justify-content:flex-end;padding-right:4px;box-sizing:border-box;min-width:fit-content">' +
          '<span style="font-size:11px;color:#fff;font-weight:600">' + r.sources[k] + '</span></div></div></div>';
      });
      barHtml += '</div></div>';
      s.innerHTML += barHtml;
    }

    // 【近 7 天趋势 — SVG 折线图】
    if (r.weekly && r.weekly.length) {
      const w = r.weekly;
      const svgW = 320, svgH = 120, pad = { top: 8, right: 8, bottom: 24, left: 30 };
      const chartW = svgW - pad.left - pad.right, chartH = svgH - pad.top - pad.bottom;
      const maxC = Math.max(1, ...w.map(d => d.count));
      const pts = w.map((d, i) => {
        const x = pad.left + (i / (w.length - 1 || 1)) * chartW;
        const y = pad.top + chartH - (d.count / maxC) * chartH;
        return x + ',' + y;
      });
      const polyline = pts.join(' ');
      // 填充区域
      const area = polyline + ' ' + (pad.left + chartW) + ',' + (pad.top + chartH) + ' ' + pad.left + ',' + (pad.top + chartH);
      let trendHtml = '<div style="margin-top:14px"><h2 style="margin:0 0 6px">近 7 天入库趋势</h2>' +
        '<svg viewBox="0 0 ' + svgW + ' ' + svgH + '" style="width:100%;max-width:' + svgW + 'px;height:auto;background:var(--card-bg);border-radius:8px">' +
        '<polygon points="' + area + '" fill="rgba(37,99,235,0.08)" stroke="none"/>' +
        '<polyline points="' + polyline + '" fill="none" stroke="#2563eb" stroke-width="2" stroke-linejoin="round"/>';
      w.forEach((d, i) => {
        const x = pad.left + (i / (w.length - 1 || 1)) * chartW;
        const y = pad.top + chartH - (d.count / maxC) * chartH;
        trendHtml += '<circle cx="' + x + '" cy="' + y + '" r="3" fill="#2563eb"/>';
      });
      // X 轴标签（日期缩略）
      w.forEach((d, i) => {
        const x = pad.left + (i / (w.length - 1 || 1)) * chartW;
        const label = d.date.slice(5); // MM-DD
        trendHtml += '<text x="' + x + '" y="' + (svgH - 4) + '" text-anchor="middle" font-size="9" fill="#999">' + label + '</text>';
      });
      // Y 轴标签
      trendHtml += '<text x="' + (pad.left - 6) + '" y="' + pad.top + '" text-anchor="end" font-size="9" fill="#999">' + maxC + '</text>' +
        '<text x="' + (pad.left - 6) + '" y="' + (pad.top + chartH) + '" text-anchor="end" font-size="9" fill="#999">0</text>';
      trendHtml += '</svg></div>';
      s.innerHTML += trendHtml;
    }

    // 【最近文档列表】
    if (r.recent && r.recent.length) {
      let recentHtml = '<div style="margin-top:14px"><h2 style="margin:0 0 6px">最近文档</h2><div style="display:flex;flex-direction:column;gap:4px">';
      r.recent.forEach(d => {
        recentHtml += '<div style="font-size:13px;padding:4px 0;border-bottom:1px solid var(--border)"><a href="#" onclick="loadDoc(\'' + esc(d.id) + '\',\'' + esc(d.title) + '\');return false" style="color:var(--accent);text-decoration:none">' + esc(d.title || d.id) + '</a> <span style="color:var(--muted);font-size:11px">' + (d.at || '') + '</span></div>';
      });
      recentHtml += '</div></div>';
      s.innerHTML += recentHtml;
    }
  } catch (e) { /* stats optional */ }
}

// ── 版本 Diff 对比 ──
async function loadDiff(id, versionCount) {
  renderSkeletons(1, 'detail');
  try {
    const vers = await fetch('/documents/' + encodeURIComponent(id) + '/versions').then(x => x.json());
    if (vers.length < 2) { box.innerHTML = '<p>版本不足，无法比较</p>'; return; }
    const last = vers[vers.length - 1], prev = vers[vers.length - 2];
    const r = await fetch('/documents/' + encodeURIComponent(id) + '/diff?v1=' + prev.version_id + '&v2=' + last.version_id).then(x => x.json());
    if (r.error) { box.innerHTML = '<p class="meta">' + esc(r.error) + '</p>'; return; }
    const back = '<p><a href="#" onclick="loadDoc(\'' + esc(id) + '\');return false">← 返回文档</a></p>';
    box.innerHTML = back +
      '<h2>版本对比：' + esc(r.canonical_id) + '</h2>' +
      '<p class="meta" style="margin-bottom:8px">版本 ' + r.v1 + ' (' + esc(r.v1_updated) + ') ↔ 版本 ' + r.v2 + ' (' + esc(r.v2_updated) + ') · 共 ' + r.changes + ' 处变动</p>' +
      '<div style="border:1px solid var(--border);border-radius:8px;overflow:hidden;max-height:600px;overflow-y:auto">' +
      '<div style="display:flex;background:var(--card-bg);border-bottom:1px solid var(--border);font-size:12px;color:var(--muted)">' +
      '<span style="width:40px;text-align:center;padding:4px 0">旧</span>' +
      '<span style="width:40px;text-align:center;padding:4px 0">新</span>' +
      '<span style="padding:4px 8px">内容</span></div>' +
      r.diff_html + '</div>';
  } catch (e) { box.innerHTML = '<p class="meta">加载失败: ' + esc(e.message) + '</p>'; }
}

// ── 文档编辑 ──
function editDoc(id, title) {
  const header = document.getElementById('doc-header');
  const contentEl = box.querySelector('.doc-content');
  const fmt = header ? header.dataset.format : 'plain';
  // HTML 格式用 innerHTML 保留标签；plain 用 textContent
  const origContent = contentEl ? (fmt === 'html' ? contentEl.innerHTML : contentEl.textContent) : '';

  header.querySelector('.edit-actions').innerHTML = '';
  header.querySelector('h2').outerHTML = '<input class="edit-title" id="edit-title" value="' + esc(title) + '">';
  const textarea = document.createElement('textarea');
  textarea.className = 'edit-content'; textarea.value = origContent;
  if (fmt === 'html') { textarea.style.fontFamily = 'monospace'; }
  if (contentEl) contentEl.replaceWith(textarea);

  const actions = document.createElement('div'); actions.className = 'edit-actions';
  actions.innerHTML = '<button onclick="saveDoc(\'' + esc(id) + '\')">保存</button>' +
    '<button class="ghost" onclick="loadDoc(\'' + esc(id) + '\',\'' + esc(title) + '\')">取消</button>';
  header.appendChild(actions);
}

async function saveDoc(id) {
  const title = document.getElementById('edit-title').value.trim();
  const content = document.querySelector('.edit-content').value;
  const header = document.getElementById('doc-header');
  const fmt = header ? header.dataset.format : 'plain';
  if (!title) { toast('标题不能为空'); return; }
  try {
    const r = await fetch('/documents/' + encodeURIComponent(id), {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ title: title, content: content, format: fmt })
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
    const [c1, c2] = await Promise.all([
      fetch('/documents/' + encodeURIComponent(id) + '/versions/' + v1.version_id).then(x => x.json()),
      fetch('/documents/' + encodeURIComponent(id) + '/versions/' + v2.version_id).then(x => x.json()),
    ]);
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
    if (!resp.ok) {
      const errData = await resp.json().catch(() => ({ error: resp.statusText }));
      aiAppendToken(aiBubble, '[请求失败: ' + (errData.error || resp.status) + ']');
      return;
    }
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

// ── 通知系统 ──
var notifSource = null;

function connectEvents() {
  if (notifSource) notifSource.close();
  try {
    notifSource = new EventSource('/events');
    notifSource.addEventListener('connected', function() { refreshNotifBadge(); });
    notifSource.onmessage = function(e) {
      try { var d = JSON.parse(e.data); refreshNotifBadge(); } catch(ex) {}
    };
    notifSource.onerror = function() { setTimeout(connectEvents, 5000); };
  } catch(e) {}
}

async function refreshNotifBadge() {
  var badge = document.getElementById('notifBadge');
  try {
    var r = await fetch('/api/notifications').then(function(x){return x.json();});
    if (r.unread > 0) { badge.style.display = 'inline'; badge.textContent = r.unread > 99 ? '99+' : r.unread; }
    else { badge.style.display = 'none'; }
    var list = document.getElementById('notifList');
    if (list && r.notifications) {
      list.innerHTML = r.notifications.slice(0,10).map(function(n){
        return '<div class="notif-item" style="padding:8px 12px;border-bottom:1px solid var(--border);cursor:pointer' + (n.read ? '' : ';background:var(--accent);color:#fff') + '">' +
          '<div style="font-size:13px">' + esc(n.title) + '</div>' +
          '<div style="font-size:11px;opacity:0.7">' + esc(n.created_at||'') + '</div></div>';
      }).join('') || '<div style="padding:12px;text-align:center;color:var(--muted)">暂无通知</div>';
    }
  } catch(e) {}
}

function toggleNotifications() {
  var panel = document.getElementById('notifPanel');
  panel.style.display = panel.style.display === 'none' ? 'block' : 'none';
  if (panel.style.display === 'block') refreshNotifBadge();
}

async function markAllRead() {
  try { await fetch('/api/notifications/read-all', {method:'POST'}); refreshNotifBadge(); } catch(e) {}
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

// ── 运营 UI ──
function showView(name) {
  ['ops','course','admin'].forEach(function(v){
    var el = document.getElementById(v+'-panel');
    if(el) el.style.display = name === v ? 'block' : 'none';
  });
  document.getElementById('results').style.display = name === 'ops' || name === 'course' || name === 'admin' ? 'none' : 'block';
  if (name === 'ops' || name === 'course' || name === 'admin') document.getElementById('stats').style.display = 'none';
  else document.getElementById('stats').style.display = 'flex';
}

function showToast(msg) { toast(msg); }

async function loadSchedules(date) {
  const box = document.getElementById('ops-content');
  box.innerHTML = '<p class="meta">加载中…</p>';
  const url = '/ops/schedules' + (date ? '?date=' + encodeURIComponent(date) : '');
  try {
    const r = await fetch(url).then(x => x.json());
    let html = '<h3>排班表</h3><table class="ops-table"><tr><th>日期</th><th>医生</th><th>时段</th></tr>';
    for (const s of (r.schedules || r)) {
      html += '<tr><td>' + esc(s.date||'') + '</td><td>' + esc(s.doctor||'') + '</td><td>' + esc(s.slot||'') + '</td></tr>';
    }
    html += '</table>';
    box.innerHTML = html;
  } catch(e) { box.innerHTML = '<p class="meta">加载失败: ' + esc(e.message) + '</p>'; }
}

async function loadAppointments(date, status) {
  const box = document.getElementById('ops-content');
  box.innerHTML = '<p class="meta">加载中…</p>';
  let params = new URLSearchParams();
  if (date) params.set('date', date);
  if (status) params.set('status', status);
  const url = '/ops/appointments' + (params.toString() ? '?' + params.toString() : '');
  try {
    const r = await fetch(url).then(x => x.json());
    const list = r.appointments || r;
    let html = '<h3>预约列表</h3><table class="ops-table"><tr><th>ID</th><th>患者</th><th>日期</th><th>医生</th><th>状态</th><th>操作</th></tr>';
    for (const a of list) {
      const sid = a.id || a.appointment_id;
      html += '<tr><td>' + esc(sid) + '</td><td>' + esc(a.patient_id||'') + '</td><td>' + esc(a.date||'') + '</td><td>' + esc(a.doctor||'') + '</td><td>' + esc(a.status||'') + '</td>';
      html += '<td>';
      if (a.status === 'booked') html += '<button onclick="doCheckin(' + sid + ')">签到</button> <button onclick="doCancel(' + sid + ')">取消</button>';
      else if (a.status === 'checked_in') html += '<button onclick="doComplete(' + sid + ')">完成</button> <button onclick="doNoShow(' + sid + ')">缺诊</button>';
      html += '</td></tr>';
    }
    html += '</table>';
    box.innerHTML = html;
  } catch(e) { box.innerHTML = '<p class="meta">加载失败: ' + esc(e.message) + '</p>'; }
}

async function doCheckin(id) {
  try {
    const r = await fetch('/ops/visits', {method:'POST', body:JSON.stringify({appointment_id:id}),
      headers:{'Content-Type':'application/json'}}).then(x=>x.json());
    showToast('签到成功'); loadAppointments();
  } catch(e) { showToast('签到失败'); }
}

async function doCancel(id) {
  showToast('取消功能需后端支持，请使用 CLI: khub ops-cancel ' + id);
}

async function doComplete(id) { showToast('完成功能待实现'); }
async function doNoShow(id) { showToast('标记缺诊待实现'); }

// ── 标签与收藏 ──
async function addTag(docId, tag) {
  if (!tag.trim()) return;
  await fetch('/documents/' + encodeURIComponent(docId) + '/tags', {
    method:'POST', body:JSON.stringify({tag}), headers:{'Content-Type':'application/json'}
  });
  loadDoc(docId);
}
async function removeTag(docId, tag) {
  await fetch('/documents/' + encodeURIComponent(docId) + '/tags?tag=' + encodeURIComponent(tag), {method:'DELETE'});
  loadDoc(docId);
}
async function toggleFav(docId) {
  await fetch('/documents/' + encodeURIComponent(docId) + '/favorite', {method:'POST'});
  loadDoc(docId);
}
async function loadFavorites() {
  const box = document.getElementById('results');
  box.innerHTML = '<h2>收藏夹</h2>';
  try {
    const r = await fetch('/favorites').then(x=>x.json());
    if (!r.favorites || !r.favorites.length) { box.innerHTML += '<p class="meta">暂无收藏</p>'; return; }
    let html = '<div class="card-list">';
    for (const f of r.favorites) html += '<div class="card" onclick="loadDoc(\'' + esc(f.doc_id) + '\')"><h3>' + esc(f.title||f.doc_id) + '</h3><p class="meta">' + esc(f.created_at||'') + '</p></div>';
    html += '</div>';
    box.innerHTML += html;
  } catch(e) { box.innerHTML += '<p class="meta">加载失败</p>'; }
}
async function loadTagFilter() {
  try {
    const r = await fetch('/tags').then(x=>x.json());
    const sel = document.getElementById('tagFilter');
    if (!sel) return;
    for (const t of (r.tags||[])) { const o = document.createElement('option'); o.value=t.tag; o.textContent=t.tag+' ('+t.count+')'; sel.appendChild(o); }
  } catch(e) {}
}

// ── 键盘快捷键 ──
document.addEventListener('keydown', function(e) {
  if (e.key === '/' && e.target.tagName !== 'INPUT' && e.target.tagName !== 'TEXTAREA') {
    e.preventDefault(); document.getElementById('q').focus();
  }
  if (e.key === 'Escape') {
    document.getElementById('q').value = '';
    document.getElementById('q').blur();
  }
});

// ── 初始化 ──
initTheme();
checkLogin().then(function() {
  connectEvents();
  loadStats();
  loadTagFilter();
  loadAll();
});
document.getElementById('q').addEventListener('keydown', e => { if (e.key === 'Enter') search(); });
document.getElementById('ai-send').addEventListener('click', aiAsk);
aiInput.addEventListener('keydown', e => { if (e.key === 'Enter') aiAsk(); });
// ── 课程 UI ──
async function loadCourses() {
  var box = document.getElementById('course-content');
  box.innerHTML = '<p class="meta">加载中…</p>';
  try {
    var r = await fetch('/api/courses').then(function(x){return x.json();});
    if (!r.courses || !r.courses.length) { box.innerHTML = '<p class="meta">暂无课程</p>'; return; }
    var html = '<table class="ops-table"><tr><th>ID</th><th>名称</th><th>教师</th><th>状态</th></tr>';
    r.courses.forEach(function(c){
      html += '<tr onclick="loadCourseDetail(' + c.id + ')" style="cursor:pointer"><td>' + c.id + '</td><td>' + esc(c.name) + '</td><td>' + esc(c.teacher||'') + '</td><td>' + esc(c.status) + '</td></tr>';
    });
    html += '</table>';
    box.innerHTML = html;
  } catch(e) { box.innerHTML = '<p class="meta">加载失败</p>'; }
}

async function loadCourseDetail(id) {
  var box = document.getElementById('course-content');
  box.innerHTML = '<p class="meta">加载中…</p>';
  try {
    var r = await fetch('/api/courses/' + id).then(function(x){return x.json();});
    var c = r.course;
    var html = '<h3>' + esc(c.name) + '</h3><p>' + esc(c.description||'') + '</p>';
    html += '<p class="meta">教师: ' + esc(c.teacher||'') + ' | 时间: ' + esc(c.start_date||'') + ' — ' + esc(c.end_date||'') + '</p>';
    html += '<p class="meta">已报名: ' + (c.enrolled_count||0) + '/' + (c.capacity||'不限') + ' | 价格: ' + (c.price||0) + '</p>';
    // 课时列表
    var lr = await fetch('/api/courses/' + id + '/lessons').then(function(x){return x.json();});
    html += '<h4>课时 <button onclick="showLessonForm(' + id + ')">添加课时</button></h4>';
    if (lr.lessons && lr.lessons.length) {
      html += '<table class="ops-table"><tr><th>日期</th><th>课时</th><th>时间</th><th>地点</th></tr>';
      lr.lessons.forEach(function(l){
        html += '<tr><td>' + esc(l.lesson_date) + '</td><td>' + esc(l.title) + '</td><td>' + esc(l.start_time||'') + '-' + esc(l.end_time||'') + '</td><td>' + esc(l.location||'') + '</td></tr>';
      });
      html += '</table>';
    } else { html += '<p class="meta">暂无课时</p>'; }
    // 报名列表
    var er = await fetch('/api/courses/' + id + '/enrollments').then(function(x){return x.json();});
    html += '<h4>学员 <button onclick="showEnrollForm(' + id + ')">报名</button></h4>';
    if (er.enrollments && er.enrollments.length) {
      html += '<table class="ops-table"><tr><th>姓名</th><th>电话</th><th>状态</th></tr>';
      er.enrollments.forEach(function(e){
        html += '<tr><td>' + esc(e.student_name) + '</td><td>' + esc(e.student_phone||'') + '</td><td>' + esc(e.status) + '</td></tr>';
      });
      html += '</table>';
    } else { html += '<p class="meta">暂无学员报名</p>'; }
    box.innerHTML = html;
  } catch(e) { box.innerHTML = '<p class="meta">加载失败: ' + esc(e.message) + '</p>'; }
}

function showCourseForm() {
  var box = document.getElementById('course-content');
  box.innerHTML = '<h3>创建课程</h3><div class="edit-form">' +
    '<p><input id="cf_name" placeholder="课程名称"></p>' +
    '<p><input id="cf_teacher" placeholder="授课教师"></p>' +
    '<p><input id="cf_start" placeholder="开课日期 (YYYY-MM-DD)"></p>' +
    '<p><input id="cf_end" placeholder="结课日期 (YYYY-MM-DD)"></p>' +
    '<p><input id="cf_capacity" placeholder="人数上限 (0=不限)" type="number"></p>' +
    '<p><textarea id="cf_desc" placeholder="课程简介" rows="3"></textarea></p>' +
    '<p><button onclick="doCreateCourse()">创建</button></p></div>';
}

async function doCreateCourse() {
  var body = {
    name: document.getElementById('cf_name').value,
    teacher: document.getElementById('cf_teacher').value,
    start_date: document.getElementById('cf_start').value,
    end_date: document.getElementById('cf_end').value,
    capacity: parseInt(document.getElementById('cf_capacity').value) || 0,
    description: document.getElementById('cf_desc').value,
  };
  try {
    var r = await fetch('/api/courses', {method:'POST', body:JSON.stringify(body), headers:{'Content-Type':'application/json'}}).then(function(x){return x.json();});
    showToast('课程 #' + r.course_id + ' 已创建');
    loadCourses();
  } catch(e) { showToast('创建失败'); }
}

function showLessonForm(courseId) {
  var title = prompt('课时标题：'); if (!title) return;
  var date = prompt('上课日期 (YYYY-MM-DD)：'); if (!date) return;
  var st = prompt('开始时间：') || '';
  var et = prompt('结束时间：') || '';
  var loc = prompt('地点：') || '';
  fetch('/api/courses/' + courseId + '/lessons', {method:'POST', body:JSON.stringify({title, lesson_date:date, start_time:st, end_time:et, location:loc}), headers:{'Content-Type':'application/json'}})
    .then(function(){ loadCourseDetail(courseId); showToast('课时已添加'); })
    .catch(function(){ showToast('添加失败'); });
}

function showEnrollForm(courseId) {
  var name = prompt('学员姓名：'); if (!name) return;
  var phone = prompt('联系电话：') || '';
  fetch('/api/courses/' + courseId + '/enroll', {method:'POST', body:JSON.stringify({student_name:name, student_phone:phone}), headers:{'Content-Type':'application/json'}})
    .then(function(r){ return r.json(); })
    .then(function(j){ if(j.enrollment_id) showToast('报名成功'); else showToast(j.error||'报名失败'); loadCourseDetail(courseId); })
    .catch(function(){ showToast('报名失败'); });
}

async function loadUsers() {
  var box = document.getElementById('admin-content');
  box.innerHTML = '<p class="meta">加载中…</p>';
  try {
    const r = await fetch('/api/users').then(x=>x.json());
    let html = '<h3>用户列表 <button onclick="showAddUserForm()">添加用户</button></h3>';
    html += '<table class="ops-table"><tr><th>ID</th><th>用户名</th><th>显示名</th><th>角色</th><th>状态</th><th>操作</th></tr>';
    for (const u of (r.users||[])) {
      html += '<tr><td>'+u.id+'</td><td>'+esc(u.username)+'</td><td>'+esc(u.display_name)+'</td><td>'+esc(u.role)+'</td><td>'+(u.active?'✓':'✗')+'</td>';
      html += '<td><select onchange="changeRole('+u.id+',this.value)"><option value="">改角色</option><option value="admin">admin</option><option value="doctor">doctor</option><option value="nurse">nurse</option><option value="receptionist">receptionist</option><option value="patient">patient</option></select></td></tr>';
    }
    html += '</table>';
    box.innerHTML = html;
  } catch(e) { box.innerHTML = '<p class="meta">加载失败</p>'; }
}

function showAddUserForm() {
  var box = document.getElementById('admin-content');
  box.innerHTML = '<h3>添加用户</h3><div class="edit-form">'+
    '<p><input id="nu_name" placeholder="用户名"></p>'+
    '<p><input id="nu_pass" type="password" placeholder="密码"></p>'+
    '<p><input id="nu_display" placeholder="显示名"></p>'+
    '<p><select id="nu_role"><option value="doctor">医生</option><option value="nurse">护士</option><option value="receptionist">前台</option><option value="patient">患者</option></select></p>'+
    '<p><button onclick="doAddUser()">创建</button></p></div>';
}

async function doAddUser() {
  var body = {
    username: document.getElementById('nu_name').value,
    password: document.getElementById('nu_pass').value,
    display_name: document.getElementById('nu_display').value,
    role: document.getElementById('nu_role').value,
  };
  try {
    await fetch('/api/users', {method:'POST', body:JSON.stringify(body), headers:{'Content-Type':'application/json'}});
    showToast('用户已创建'); loadUsers();
  } catch(e) { showToast('创建失败'); }
}

async function changeRole(uid, role) {
  if (!role) return;
  try {
    await fetch('/api/users/'+uid+'/role', {method:'PUT', body:JSON.stringify({role}), headers:{'Content-Type':'application/json'}});
    showToast('角色已更新'); loadUsers();
  } catch(e) { showToast('更新失败'); }
}

loadAll();
