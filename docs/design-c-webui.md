# Web UI 升级设计规格

> 设计者：designer-c  
> 日期：2026-07-09  
> 状态：初稿

---

## 1. 总体策略

### 方案评估

| 维度 | 方案 A：继续内嵌 HTML | 方案 B：提取为独立文件 |
|------|----------------------|----------------------|
| 修改范围 | 仅 `api.py` | `api.py` + 新建 `khub/web/` 目录 |
| 开发效率 | 低（单个文件膨胀，无语法高亮/格式化） | 高（独立文件，可用 IDE 完整支持） |
| 可维护性 | 差（HTML/CSS/JS 混在 Python 字符串中） | 好（关注点分离） |
| 路由复杂度 | 无变化 | 需在 `dispatch()` 中新增静态文件伺服 |
| 部署变化 | 无 | 多一个目录，无额外依赖 |
| 调试体验 | 无 sourcemap 支持 | 浏览器 DevTools 可直接定位源文件 |
| HTTP 缓存 | 不可用（每次返回完整内嵌页面） | 可对 CSS/JS 设置 Cache-Control |
| 增量迁移 | 可以逐步提取 | 方案 B 天然支持增量提取 |

### 推荐：方案 B（提取为独立文件，放在 `khub/web/` 目录）

理由：
1. 这是"升级"而非"小修小补"——extract 是一次性成本，后续所有修改的边际成本都会更低
2. 不会增加任何运行时依赖
3. 当前 `_html_page()` 已约 140 行，升级后预计 400+ 行，再内嵌不可接受
4. 不修改 `pyproject.toml` 的约束满足——`khub/web/` 只是 Python 包内的子目录

### 文件组织

```
khub/web/
├── index.html          # 主页面 HTML 骨架
├── style.css           # 全部样式
├── script.js           # 全部交互逻辑
└── htmx.min.js         # [可选] HTMX 14KB 压缩版，仅当决定引入
```

伺服方式：在 `App.dispatch()` 中新增 `GET /web/*` 路由（或直接在根路由处理），读取对应文件返回 `text/html` / `text/css` / `application/javascript`。

---

## 2. 具体升级项（按优先级）

### P0：核心体验

#### 2.1 移动端适配

**现状**：仅有 `viewport` meta 标签和 `flex-wrap`，但无任何断点设计。手机屏上按钮挤占、卡片间距过大。

**设计**：
- 基于 CSS media query 的两档断点：`≥768px`（平板/桌面）、`<768px`（手机）
- 手机端：搜索框全宽、按钮两行排列、卡片去除边框阴影用更薄的分割线
- 桌面端：保留当前卡片样式，略微增加 padding 和字号

**样式要点**：
```css
/* 桌面默认 */
.bar { display: flex; gap: 8px; }
.card { border-radius: 10px; padding: 14px 18px; }

/* 手机 ≤767px */
@media (max-width: 767px) {
  .bar { flex-direction: column; gap: 6px; }
  #q { width: 100%; box-sizing: border-box; }
  .bar button, .bar select { width: 100%; }
  .card { border-radius: 0; border-left: 0; border-right: 0; margin-bottom: 1px; }
  .wrap { padding: 0 8px; }
  #stats { gap: 6px; }
  #stats .stat-card { min-width: 55px; padding: 6px 10px; }
  header { padding: 10px 14px; }
}
```

#### 2.2 搜索高亮与来源筛选

**现状**：`highlight()` 函数已实现关键词高亮（`<mark>` 标签包裹）。来源筛选的 `<select>` 已存在，但 `search()` 函数已正确拼装 `source` 参数。**功能基本完善，只需 UI 微调：**
- 确保搜索结果中 `highlight()` 正确调用（当前已调用）
- 给 `<mark>` 添加样式：`background: #fef08a; padding: 0 2px; border-radius: 2px`
- 深色模式下适配高亮色

**无需修改逻辑代码**，仅 CSS 调整。

#### 2.3 分页控件

**现状**：仅有一个"下一页"按钮，无页码条、无跳转、无上一页。

**设计**：用纯 JS 构建分页条组件

```html
<div class="pagination">
  <button onclick="goPage(0)" ?disabled="page===0">首页</button>
  <button onclick="goPage(page-1)" ?disabled="page===0">‹ 上一页</button>
  <span class="page-info">第 {from}-{to} / 共 {total} 篇</span>
  <button onclick="goPage(page+1)" ?disabled="(page+1)*per >= total">下一页 ›</button>
  <button onclick="goPage(lastPage)" ?disabled="(page+1)*per >= total">末页</button>
</div>
```

- 重构 `search()`：移出分页渲染逻辑，由 `renderPagination()` 函数负责
- 在 `<h2>` 信息行下方插入分页条
- 当前 `PER_PAGE=20` 保持

---

### P1：新功能

#### 2.4 冲突解决视图（Side-by-Side Diff）

**现状**：`GET /conflicts` 返回冲突文档列表，点开进入详情页（显示最新版本原文），**无冲突对比和解决能力**。

**设计**：

**API 变更**：
- 新增 `GET /documents/{id}/versions` → 返回该文档所有版本列表，包含 `version_id`, `title`, `updated_at`, `format`。当前已通过 `get_versions()` 暴露给详情页，但未直接暴露为独立端点。
- 新增 `GET /documents/{id}/versions/{vid}` → 返回指定版本的完整内容。
- 新增 `POST /documents/{id}/resolve` → body: `{"keep_version": version_id}` → 将指定版本设为主版本，`conflict` 标记清 0。

**UI 设计**：
```
┌─────────────────────────────────────────────┐
│  冲突解决：{title}                           │
│  [← 返回列表]                               │
├──────────────────┬──────────────────────────┤
│  版本 {v1}        │  版本 {v2}              │
│  {updated_at}     │  {updated_at}            │
├──────────────────┼──────────────────────────┤
│  {content v1}    │  {content v2}            │
│  (只读，滚动)     │  (只读，滚动)            │
├──────────────────┴──────────────────────────┤
│  [保留左]  [保留右]  [稍后处理]              │
└─────────────────────────────────────────────┘
```

**交互**：
- 加载冲突文档后，自动获取其所有版本（≥2 个版本才产生冲突）
- 取最新的两个版本（或全部版本，若 >2 个则用下拉选择对比的版本）
- 两边内容区可独立滚动，同步滚动为加分项但 P1 不做
- "保留左"→ 调 `POST /documents/{id}/resolve` 传左版本 ID
- "保留右"→ 同理
- "稍后处理"→ 关闭视图，保留冲突标记
- 如果文档仅一个版本但有 `conflict=1`，显示提示 "数据异常：冲突标记但只有一个版本"

#### 2.5 文档编辑

**现状**：详情页（`loadDoc()`）为只读视图，无编辑入口。

**设计**：

**API 变更**：
- 新增 `PUT /documents/{id}` → body: `{"title": "...", "content": "..."}` → 调用 `store_document()` 创建新版本

**UI 设计**：

文档详情页增加"编辑"按钮：
```
[← 返回]   [编辑]     ← 新增编辑按钮
                                    ↓ 点击
标题变为 contenteditable / input
内容变为 <textarea> (plain) 或 contenteditable (html)
[保存] [取消]
```

**交互流程**：
1. 点击"编辑"→ 标题切换为 `<input type="text">`，内容切换为 `<textarea>`（plain 格式）或 contenteditable div（html 格式）
2. 用户修改后点击"保存"→ `PUT /documents/{id}` → 成功后刷新详情页（新版本）
3. 点击"取消"→ 恢复原始内容
4. 保存失败显示 toast 提示

---

### P2：视觉提升

#### 2.6 深色模式

**现状**：无深色模式，硬编码浅色背景。

**设计**：
- CSS 变量驱动主题色
- `prefers-color-scheme: dark` 自动检测 + 手动切换按钮
- 切换状态存 `localStorage`

**CSS 结构**：
```css
:root {
  --bg: #f6f7f9;
  --card-bg: #fff;
  --text: #222;
  --muted: #999;
  --border: #e5e7eb;
  --accent: #2563eb;
  --header-bg: #1f2937;
  --header-text: #fff;
  --mark-bg: #fef08a;
}
[data-theme="dark"] {
  --bg: #111827;
  --card-bg: #1f2937;
  --text: #e5e7eb;
  --muted: #9ca3af;
  --border: #374151;
  --accent: #3b82f6;
  --header-bg: #0f172a;
  --header-text: #e5e7eb;
  --mark-bg: #854d0e;
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) { /* 用深色变量 */ }
}
```

**UI**：在 header 右侧添加 ☀/🌙 切换按钮，点击切换 `document.documentElement.dataset.theme`。

#### 2.7 加载骨架屏

**现状**：加载中显示 "加载中..." 文字。

**设计**：
- 搜索/加载文档时，在 `#results` 区域渲染 3-5 个骨架卡片
- 骨架卡片用 CSS 动画（`@keyframes shimmer`）

```css
.skeleton { background: linear-gradient(90deg, var(--card-bg) 25%, var(--border) 50%, var(--card-bg) 75%); background-size: 200% 100%; animation: shimmer 1.5s infinite; border-radius: 10px; height: 80px; margin-bottom: 10px; }
@keyframes shimmer { 0% { background-position: 200% 0; } 100% { background-position: -200% 0; } }
```

- 加载完成后骨架被实际内容替换
- 区分三种骨架：搜索列表（窄条）、详情页（标题+多行内容）、统计卡片（小方块）

#### 2.8 字体与间距优化

- 行高从当前 `line-height: 1.5` → 内容区 `1.7`，标题区 `1.4`
- 卡片间距 `margin-bottom: 12px` → `14px`（桌面）、`8px`（手机）
- 搜索框增大字号 `15px` → `16px`（改善可读性）
- 文档内容区域增加最大宽度限制 `max-width: 70ch`（中文约 35 字符，英文约 70 字符），提升长行阅读体验

---

## 3. 架构决策

### 3.1 CSS 框架？

**结论：不使用任何 CSS 框架。**

- 当前样式约 15 行 CSS，升级后预计 200-300 行，完全可控
- 零额外依赖的约束优先
- 使用 CSS 自定义属性（变量）管理主题，可维护性足够

### 3.2 交互模式？

**结论：继续使用原生 JS（fetch API），暂不引入 HTMX。**

理由：
- 当前已用原生 JS + `fetch` 实现了完整 SPA 式交互
- 引入 HTMX 的好处主要体现在"渐进增强"和"声明式交互"——但本项目所有 CRUD 操作都已有对应的 JS 函数
- HTMX 14KB 虽小但仍是一个文件，额外增加伺服复杂度
- 如果未来需要更复杂的表单交互（如内联编辑多字段联动），可以考虑引入

**保留引入 HTMX 的场景清单**（这些场景下 HTMX 能显著减少 JS 代码量）：
- 文档编辑保存後自动刷新列表（需 hx-trigger + hx-target）
- 冲突解决后的列表自动更新
- 多字段表单的提交-验证-回显流

### 3.3 API 变更汇总

| 新端点 | 方法 | 用途 | 优先级 |
|--------|------|------|--------|
| `/web/*` | GET | 伺服静态文件（HTML/CSS/JS） | P0 |
| `/documents/{id}/versions` | GET | 返回文档所有版本列表 | P1 |
| `/documents/{id}/versions/{vid}` | GET | 返回指定版本内容 | P1 |
| `/documents/{id}/resolve` | POST | 标记冲突解决，保留指定版本 | P1 |
| `/documents/{id}` | PUT | 更新文档（创建新版本） | P1 |

**端点实现详细说明**：

```
GET /documents/{id}/versions
→ 200: [{"version_id": 1, "title": "...", "updated_at": "...", "format": "plain"}, ...]
实现：self.store.get_versions(cid) 已存在，直接返回

GET /documents/{id}/versions/{vid}
→ 200: {"version_id": 1, "title": "...", "content": "...", "format": "plain", "updated_at": "..."}
实现：从 document_versions 表按 doc_id + version_id 查询
  暂缺：db.py 中需要新增 get_version(cid, vid) 方法

POST /documents/{id}/resolve
→ Body: {"keep_version": 1}
→ 200: {"status": "ok"}
实现：
  1. 获取 keep_version 的完整内容
  2. 调用 store_document() 重新写入（产生新版本）
  3. UPDATE documents SET conflict=0 WHERE canonical_id=?
  但更好的做法：允许跳过版本写入，仅修改 conflict 标记
  需在 db.py 新增 resolve_conflict(cid, keep_version_id) 方法

PUT /documents/{id}
→ Body: {"title": "...", "content": "..."}
→ 200: {"status": "ok", "version_id": N}
实现：
  构建 CanonicalDoc，调用 store_document()
  注意：PUT /documents/{id} 的 {id} 即 canonical_id
```

### 3.4 无需修改的现有端点

| 端点 | 说明 |
|------|------|
| `GET /` | 改为 302 重定向到 `/web/index.html` |
| `GET /search` | 完全可用，分页已有 |
| `GET /documents` | 完全可用 |
| `GET /documents/{id}` | 完全可用 |
| `GET /conflicts` | 完全可用（冲突视图中使用） |
| `GET /stats` | 完全可用 |
| `GET /semantic` | 完全可用 |

---

## 4. 实现计划

### 步骤 1：创建 `khub/web/` 目录 + 静态文件伺服（约 1 小时）

**改哪些文件**：
- `khub/api.py`：
  - 在 `dispatch()` 中新增 `GET /web/*` 路由（在 `GET /` 之前或之后）
  - 读取 `khub/web/{filename}` 文件，根据扩展名设置 Content-Type
  - `GET /` 改为 302 → `/web/index.html`（或直接返回 index.html 内容）
- 新建 `khub/web/index.html`（从 `_html_page()` 提取 HTML 骨架）
- 新建 `khub/web/style.css`（提取当前 CSS）
- 新建 `khub/web/script.js`（提取当前 JS）

**改动要点**：
```python
# 在 dispatch() 中新增
if method == "GET" and path.startswith("/web/"):
    filename = path[len("/web/"):]
    if not filename or ".." in filename:
        return 404, {"error": "bad path"}
    filepath = os.path.join(os.path.dirname(__file__), "web", filename)
    if not os.path.isfile(filepath):
        return 404, {"error": "not found"}
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    ctype = {"html": "text/html; charset=utf-8",
             "css": "text/css; charset=utf-8",
             "js": "application/javascript; charset=utf-8"}.get(ext, "application/octet-stream")
    with open(filepath, encoding="utf-8") as f:
        return 200, f.read(), ctype
```

**代码量估计**：`api.py` 新增约 15 行 + 3 个新文件共约 200 行（纯提取，无新增逻辑）

**测试策略**：
- 启动服务 → 访问 `/web/index.html` → 确认页面正常渲染
- 访问 `/` → 确认重定向或直接返回页面
- 访问 `/web/../api.py` → 确认 404

---

### 步骤 2：移动端适配 + CSS 变量 + 骨架屏（约 2 小时）

**改哪些文件**：
- `khub/web/style.css`：全面重写为 CSS 变量驱动 + 加入 media query + 骨架屏样式
- `khub/web/index.html`：调整 HTML 结构（给 header 加 theme-toggle 按钮位置）
- `khub/web/script.js`：添加骨架渲染函数

**代码量估计**：CSS 增量约 120 行，JS 增量约 30 行，HTML 微调约 5 行

**测试策略**：
- Chrome DevTools 切换 Device Toolbar 测试 iPhone SE / iPad / Desktop
- 确认骨架屏在搜索/加载文档时显示
- 确认深色模式手动切换和系统检测

---

### 步骤 3：分页控件重构（约 1 小时）

**改哪些文件**：
- `khub/web/script.js`：重构 `search()` 函数，提取 `renderPagination()`

**代码量估计**：JS 新增约 40 行，移除约 10 行（重构而非重写）

**测试策略**：
- 搜索关键词 → 确认分页条渲染正确
- 首页/上一页/下一页/末页按钮行为
- 当结果 < PER_PAGE 时，分页条不显示
- 边界情况：page=0 时首页/上一页禁用

---

### 步骤 4：文档编辑功能（约 2 小时）

**改哪些文件**：
- `khub/api.py`：新增 `PUT /documents/{id}` 路由
- `khub/web/script.js`：在 `loadDoc()` 基础上增加编辑/保存/取消逻辑
- `khub/web/style.css`：编辑模式下的输入框样式

**API 变更**：
```python
if method == "PUT" and path.startswith("/documents/") and len(path) > len("/documents/"):
    cid = unquote(path[len("/documents/"):])
    doc = CanonicalDoc(
        canonical_id=cid,
        title=body.get("title", ""),
        content=body.get("content", ""),
        source="webui",
        source_id="",
        origin="webui",
        format=body.get("format", "plain"),
        updated_at=time.strftime("%Y-%m-%dT%H:%M:%S"),
    )
    version_id = self.store.store_document(doc)
    return 200, {"status": "ok", "version_id": version_id}
```

**代码量估计**：`api.py` 新增约 15 行，JS 新增约 50 行，CSS 新增约 10 行

**测试策略**：
- 打开文档详情 → 点击编辑 → 修改标题和内容 → 保存 → 确认新版本
- 取消编辑 → 内容恢复
- 保存返回的错误信息正确显示
- 对空标题/内容的 PUT 请求 → 400

---

### 步骤 5：冲突解决视图（约 3 小时）

**改哪些文件**：
- `khub/db.py`：新增 `get_version(cid, vid)`, `resolve_conflict(cid, keep_version_id)` 
- `khub/api.py`：新增 3 个端点
- `khub/web/script.js`：新增冲突对比视图渲染、并排比较、保留操作
- `khub/web/style.css`：并排布局样式（flex/grid + 独立滚动）

**代码量估计**：`db.py` 新增约 25 行，`api.py` 新增约 30 行，JS 新增约 80 行，CSS 新增约 40 行

**测试策略**：
- 构造一个多版本冲突文档 → 确认并排视图显示两个版本
- 保留左侧→ 确认冲突标记清除
- 保留右侧→ 同理
- 单版本冲突文档 → 显示提示
- 超长内容 → 确认左右各自滚动正常

---

### 步骤 6：深色模式 + 视觉微调（约 1 小时）

**改哪些文件**：
- `khub/web/style.css`：完成 dark theme 变量定义 + 所有组件适配
- `khub/web/index.html`：添加 theme-toggle 按钮
- `khub/web/script.js`：主题切换逻辑 + localStorage 存储

**代码量估计**：CSS 增量约 50 行，JS 增量约 20 行，HTML 约 5 行

**测试策略**：
- 系统深色模式 → 进入页面自动深色
- 手动切换 → 确认切换成功
- 刷新页面 → 确认上次选择持久化
- 深色模式下所有元素可见（尤其是 mark/highlight 和 tag 标签）

---

## 5. 依赖关系图

```
步骤 1（提取文件）
    ↓
步骤 2（移动端 + CSS 变量 + 骨架屏） ── 可独立于步骤 3/4/5
    ↓
步骤 3（分页控件） ── 可独立于步骤 4/5
    ↓
步骤 4（文档编辑） ── 需要步骤 1 完成
    ↓
步骤 5（冲突解决） ── 需要步骤 1，建议步骤 4 之后（共享编辑体验）
    ↓
步骤 6（深色模式） ── 需步骤 2 的 CSS 变量基础，可在任意步骤后并行
```

步骤 2/3 可并行。步骤 4/5 建议顺序执行（共享相关 JS 函数）。步骤 6 可在任意步骤后执行。

---

## 6. 不影响范围

以下内容不在本次升级范围内：
- exam/clinical/ops 等子系统的 UI（保持纯 API 接入）
- 前后端分离（仍由 Python 伺服 HTML）
- 引入测试框架（前端测试暂不引入）
- 构建工具链（无 webpack/vite）
- 路由框架（保持 if-else dispatch）
- 文档版本差异对比（非 diff 工具，仅并排显示，不逐行高亮差异）
