# API 参考

> 版本：v1.4.0 ｜ 更新：2026-07-10
>
> REST API 基址：`http://127.0.0.1:8765`（默认绑定 127.0.0.1，端口由 `--port` 指定）

所有请求均使用 JSON 编码。请求头 `Content-Type: application/json`。响应默认为 `application/json; charset=utf-8` 格式。

## 鉴权

- 无 `KHUB_API_TOKEN` 时：无需鉴权（本地模式）
- 设 `KHUB_API_TOKEN` 后：所有请求需 `Authorization: Bearer <token>`
- 多用户模式：登录 POST `/auth/login` → 获取 JWT → `Authorization: Bearer <jwt>`
- 多租户：请求头 `X-Tenant-ID`（租户 ID 或 slug）

## 状态码

| 码 | 说明 |
|----|------|
| `200` | 成功 |
| `201` | 创建成功 |
| `400` | 请求参数错误 |
| `401` | 未认证（`AUTH_001`） |
| `403` | 权限不足（`AUTH_002`） |
| `404` | 资源不存在 |
| `413` | 请求体过大 |
| `429` | 请求频率超限 |
| `500` | 服务端错误 |

错误响应：
```json
{"error": "描述", "error_code": "AUTH_001", "message": "详细说明"}
```

## 端点一览

### 系统
| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/health` | 健康检查（深度：DB/FTS/磁盘/WAL） |
| `GET` | `/stats` | 统计（文档 + 运营 + 系统指标） |
| `GET` | `/api/info` | 系统信息（版本/品牌/uptime） |
| `GET` | `/api/openapi.json` | OpenAPI 3.0 规范 |
| `GET` | `/api/docs` | Swagger UI |
| `GET` | `/api/i18n` | 国际化翻译（`?lang=` 或 Accept-Language） |

### 鉴权
| 方法 | 路径 | 说明 |
|------|------|------|
| `POST` | `/auth/login` | 登录（`username` + `password` → token） |
| `POST` | `/auth/logout` | 注销 |
| `GET` | `/auth/me` | 当前用户信息 |

### 文档
| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/documents` | 文档列表 |
| `GET` | `/documents/{id}` | 文档详情（含 tags/favorited） |
| `PUT` | `/documents/{id}` | 编辑文档 |
| `GET` | `/documents/{id}/versions` | 版本列表 |
| `GET` | `/documents/{id}/diff?v1=&v2=` | 版本对比 |
| `POST` | `/documents/{id}/resolve` | 冲突解决 |
| `POST` | `/documents/{id}/tags` | 添加标签 |
| `DELETE` | `/documents/{id}/tags?tag=` | 删除标签 |
| `POST` | `/documents/{id}/favorite` | 切换收藏 |

### 搜索
| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/search?q=&tag=&cursor=` | 全文检索（游标分页） |
| `GET` | `/semantic?q=` | 语义检索 |
| `GET` | `/api/search?q=&type=all` | 统一搜索（跨文档/患者/课程/中药/方剂/证型） |
| `POST` | `/ask` | RAG 问答（支持 `stream=true` SSE 流式） |

### 标签与收藏
| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/tags` | 标签列表（含文档计数） |
| `GET` | `/favorites` | 收藏列表 |

### 通知
| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/notifications` | 通知列表（含 `unread` 计数） |
| `POST` | `/api/notifications/{id}/read` | 标记已读 |
| `POST` | `/api/notifications/read-all` | 全部已读 |
| `GET` | `/events` | SSE 实时通知推送 |

### 临床
| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/twin/{pid}` | 孪生摘要（含时间线 + 辨证脉络） |
| `POST` | `/clinical/consult/chat` | 问诊助手对话 |
| `GET` | `/clinical/consultations` | 问诊列表（`?patient_id=`） |
| `GET` | `/clinical/patients` | 患者列表 |
| `POST` | `/clinical/extract` | 结构化抽取 |
| `GET` | `/clinical/analysis/{pid}/matrix` | 证型→方剂关联 |
| `GET` | `/clinical/analysis/{pid}/evolution` | 体质演变 |
| `GET` | `/clinical/tracking/{pid}` | 疗效评估 |
| `GET` | `/clinical/trends/{pid}` | 健康趋势 |
| `POST` | `/clinical/diagnosis/suggest` | AI 辨证推荐 |

### 运营
| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/ops/appointments` | 预约列表（`?date=&doctor=&status=&patient_id=`） |
| `POST` | `/ops/appointments` | 预约挂号 |
| `GET` | `/ops/schedules` | 排班列表 |
| `POST` | `/ops/schedules` | 新建排班 |
| `POST` | `/ops/visits` | 到诊签到 |
| `GET` | `/sync-status` | 数据源同步状态 |
| `GET` | `/clinical/followup` | 随访计划 |
| `GET` | `/clinical/followup/scan` | 扫描到期随访 |

### 考试
| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/exam/questions` | 题目列表 |
| `POST` | `/exam/questions` | 创建题目 |
| `POST` | `/exam/generate` | 自动出题 |
| `POST` | `/exam/grade` | 判分 |

### 课程
| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/courses` | 课程列表 |
| `POST` | `/api/courses` | 创建课程 |
| `GET` | `/api/courses/{id}` | 课程详情 |
| `POST` | `/api/courses/{id}/lessons` | 添加课时 |
| `GET` | `/api/courses/{id}/lessons` | 课时列表 |
| `POST` | `/api/courses/{id}/enroll` | 学员报名 |
| `GET` | `/api/courses/{id}/enrollments` | 报名列表 |
| `POST` | `/api/grades` | 录入成绩 |
| `GET` | `/api/enrollments/{id}/grades` | 成绩列表 |

### 知识图谱
| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/kg/infer?syndrome=` | 证型推理 |
| `GET` | `/api/kg/herbs` | 中药查询（`?channel=&nature=`） |
| `GET` | `/api/kg/formulas` | 方剂列表 |
| `GET` | `/api/kg/syndromes` | 证型列表 |
| `GET` | `/api/kg/similarity?f1=&f2=` | 方剂相似度 |

### 报表
| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/reports` | 报表模板列表 |
| `POST` | `/api/reports` | 创建报表 |
| `POST` | `/api/reports/{id}/run` | 运行报表 |
| `GET` | `/api/reports/{id}/csv` | 导出 CSV |

### Webhook
| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/webhooks` | 订阅列表 |
| `POST` | `/api/webhooks` | 创建订阅 |
| `DELETE` | `/api/webhooks/{id}` | 删除订阅 |

### Copilot / Agent
| 方法 | 路径 | 说明 |
|------|------|------|
| `POST` | `/api/copilot/chat` | Copilot 对话 |
| `GET` | `/api/copilot/tools` | 工具列表 |
| `GET` | `/api/agents` | Agent 列表 |
| `POST` | `/api/agents` | 创建 Agent |
| `POST` | `/api/agents/{id}/run` | 运行 Agent |

### 工作流
| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/workflow/definitions` | 定义列表 |
| `POST` | `/api/workflow/definitions` | 创建定义 |
| `POST` | `/api/workflow/definitions/{id}/run` | 运行工作流 |
| `GET` | `/api/workflow/instances` | 实例列表 |

### 远程医疗
| 方法 | 路径 | 说明 |
|------|------|------|
| `POST` | `/api/telemedicine/room` | 创建视频房间 |
| `GET` | `/api/telemedicine/room/{id}` | 房间信息 |
| `POST` | `/api/telemedicine/room/{id}/start` | 开始通话 |
| `POST` | `/api/telemedicine/room/{id}/end` | 结束通话 |
| `GET` | `/api/prescriptions` | 处方列表（`?patient_id=&doctor_id=`） |
| `POST` | `/api/prescriptions` | 创建处方 |

### 知识社区
| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/community/articles` | 文章列表（`?tag=`） |
| `POST` | `/api/community/articles` | 发布文章 |
| `GET` | `/api/community/tags` | 社区标签 |
| `POST` | `/api/community/comments` | 添加评论 |

### 集成
| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/integrations/status` | 集成状态（8 项检测） |

### 合规
| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/compliance/checklist` | 合规检查清单 |
| `GET` | `/api/compliance/report` | 合规报告 |

### 数据分析
| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/analytics/cohorts` | 患者分群 |
| `GET` | `/api/analytics/efficacy` | 疗效分析 |
| `GET` | `/api/analytics/forecast` | 就诊预测 |
| `GET` | `/api/analytics/trends` | 预约趋势 |

### 多租户
| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/tenants` | 租户列表 |
| `POST` | `/api/tenants` | 创建租户 |
| `POST` | `/api/tenants/members` | 添加成员 |
| `GET` | `/api/tenants/{id}/members` | 成员列表 |

### 同步
| 方法 | 路径 | 说明 |
|------|------|------|
| `POST` | `/api/sync/push` | 推送变更 |
| `GET` | `/api/sync/pull` | 拉取变更（`?since=&client_id=`） |
| `GET` | `/api/sync/status` | 同步状态 |

### 用户管理
| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/users` | 用户列表（admin 专用） |
| `POST` | `/api/users` | 创建用户（admin 专用） |
| `PUT` | `/api/users/{id}/role` | 修改角色（admin 专用） |

### 审计
| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/admin/audit` | 审计日志查询（`?event=&actor=&since=`） |

### 微信
| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/wechat/articles` | 微信文章列表 |
| `POST` | `/api/wechat/articles` | 创建微信文章 |
| `POST` | `/api/wechat/schedules` | 排期发布 |
| `GET` | `/api/wechat/followers` | 粉丝列表 |

### 插件
| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/plugins` | 已加载插件列表 |

## 全量端点统计

当前共 **150+ 个 REST 端点**，覆盖系统/鉴权/文档/搜索/临床/运营/考试/课程/知识图谱/报表/Webhook/Copilot/Agent/工作流/远程医疗/社区/集成/合规/数据分析/多租户/同步/用户管理/审计/微信/插件 25 个领域。
| GET | `/` | Web UI 首页 | — | HTML 页面 |
| GET | `/stats` | 数据看板统计 | — | `{"total":1861, "sources":{"obsidian":1711,...}, "today":0, "recent":[...]}` |
| GET | `/health` | 健康检查 | — | `{"status":"ok","version":"1.4.0","documents":42,"uptime_sec":3600.0}` |
| GET | `/ebooks` | 列出电子书 | — | `[{"canonical_id":"sha256-xxx","title":"伤寒论",...}]` |
| POST | `/ebooks/register` | 注册电子书 | `{"path":"...", "move":false}` | `{"canonical_id":"sha256-xxx"}` |
| POST | `/ebooks/{cid}/ingest` | 入库电子书 | — | `{"canonical_id":"sha256-xxx","version_id":3}` |
| GET | `/documents` | 列出全部文档 | — | `[{"canonical_id":"sha256-xxx","title":"伤寒论",...}]` |
| GET | `/documents/{cid}` | 获取单篇文档（最新版本全文） | — | `{"canonical_id":"...","title":"...","content":"...","version_count":3,...}` |
| GET | `/conflicts` | 列出冲突文档 | — | `[{"canonical_id":"sha256-xxx","title":"伤寒论"}]` |
| GET | `/web/*` | 静态资源（路径穿越已防护） | — | 文件字节流 |
| POST | `/documents` | 直接入库文档 | `{"title":"...","content":"...","source":"KZOCR"}` | `{"status":"ok","doc_id":"sha256-xxx","version_id":1}` |
| GET | `/search?q=关键词&page=0&per=20&source=obsidian` | 全文检索（分页+来源过滤） | — | `{"hits":[...], "total":264, "page":0, "per_page":20}` |
| GET | `/semantic?q=关键词&k=5` | 语义检索 | — | `[{"doc_id":"sha256-xxx","score":0.9234}]` |
| POST | `/clinical/patients` | 登记患者 | `{"id":"p1","name":"张三",...}` | `{"id":"p1"}` |
| GET | `/clinical/patients` | 列出患者 | — | 患者列表 |
| POST | `/clinical/records` | 新增病历 | `{"patient_id":"p1","diagnosis":"太阳病",...}` | `{"id":"rec-xxx"}` |
| POST | `/clinical/consultations` | 新增问诊 | `{"patient_id":"p1","chief_complaint":"发热",...}` | `{"id":"cst-xxx"}` |
| POST | `/clinical/twin/{pid}/summarize` | 生成孪生体摘要 | — | `{"patient_id":"p1","summary":"..."}` |
| POST | `/ops/schedules` | 新增排班 | `{"date":"2026-04-01","doctor":"王医生","slot":"上午"}` | `{"id":"sch-xxx"}` |
| POST | `/ops/appointments` | 预约挂号 | `{"patient_id":"p1","date":"2026-04-01","doctor":"王医生"}` | `{"id":"apt-xxx"}` |
| GET | `/ops/appointments?date=2026-04-01` | 列出预约 | — | 预约列表 |
| POST | `/ops/visits` | 签到就诊 | `{"appointment_id":"apt-xxx","patient_id":"p1",...}` | `{"id":"vis-xxx"}` |
| POST | `/exam/questions` | 新增考题 | `{"kind":"mcq","stem":"...","options":[...],...}` | `{"id":"q-xxx"}` |
| GET | `/exam/questions?kind=mcq` | 列出考题 | — | 考题列表 |
| POST | `/exam/generate` | 生成考题 | `{"topic":"少阳证"}` | `{"kind":"mcq","stem":"...",...}` |

---

## Web UI

### `GET /`

轻量本地 Web UI，提供文档浏览、全文检索、语义检索、冲突列表功能。

**响应：** `200` — HTML 页面（`text/html; charset=utf-8`）

---

## 系统

### `GET /health`

健康检查端点。

**响应：** `200`

```json
{
  "status": "ok",
  "version": "1.4.0",
  "documents": 42,
  "uptime_sec": 3600.0
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `status` | string | `"ok"` 表示正常 |
| `version` | string | 当前版本号 |
| `documents` | int | 文档总数 |
| `uptime_sec` | float | 服务启动至今秒数 |

---

## 电子书管理

### `GET /ebooks`

列出所有已注册电子书。

**响应：** `200` — 电子书列表（数组）

```json
[
  {
    "canonical_id": "sha256-xxx",
    "title": "伤寒论",
    ...
  }
]
```

### `POST /ebooks/register`

注册一本电子书到受管库（登记元数据，不含正文抽取）。

**请求体：**

```json
{
  "path": "/path/to/book.epub",
  "move": false
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `path` | string | 是 | 电子书文件路径 |
| `move` | bool | 否 | 是否将文件移动到受管库（默认 `false`，为 `true` 时删除源文件） |

**响应：** `201`

```json
{
  "canonical_id": "sha256-xxx"
}
```

### `POST /ebooks/{cid}/ingest`

将已注册的电子书入库：抽取正文、构建 FTS 索引、生成向量嵌入。

**路径参数：**

| 参数 | 说明 |
|------|------|
| `cid` | 电子书的 `canonical_id`（sha256） |

**请求体：** 无

**响应：** `200`

```json
{
  "canonical_id": "sha256-xxx",
  "version_id": 3
}
```

**错误：**

| 状态码 | 说明 |
|--------|------|
| `404` | 指定 cid 未找到 |

---

## 文档通用

### `GET /documents`

列出全部已入库文档，按更新时间倒序。

**响应：** `200`

```json
[
  {
    "canonical_id": "sha256-xxx",
    "title": "伤寒论",
    "updated_at": "2026-04-01T12:00:00",
    "source_ids": "sha256-xxx;sha256-yyy"
  }
]
```

### `GET /conflicts`

列出标记为"冲突"的文档（同一内容从不同来源入库导致的内容不一致）。

**响应：** `200`

```json
[
  {
    "canonical_id": "sha256-xxx",
    "title": "伤寒论"
  }
]
```

### `GET /documents/{cid}`

获取单篇文档的最新版本全文（内容截断至 100k 字符，防止超大文本）。

**路径参数：**

| 参数 | 说明 |
|------|------|
| `cid` | 文档 `canonical_id`（需 URL 编码） |

**响应：** `200`

```json
{
  "canonical_id": "sha256-xxx",
  "title": "伤寒论",
  "content": "（最新版本正文，最多 100000 字符）",
  "version_count": 3,
  "source_ids": "[\"kzocr\"]",
  "created_at": "2026-04-01T12:00:00",
  "updated_at": "2026-04-02T08:00:00",
  "format": "markdown"
}
```

**错误：**

| 状态码 | 说明 |
|--------|------|
| `404` | 指定 `cid` 未找到 |

### `GET /web/*`

静态资源服务（Web UI 依赖的前端资源）。路径经 `realpath` + 前缀校验，已防目录穿越；非文件返回 `404`。

**响应：** `200` — 文件字节流（`application/octet-stream`）

### `POST /documents`

直接入库一份文档（不依赖原始文件，适用于 KZOCR/OCR 产出等场景）。

**请求体：**

```json
{
  "title": "产出文档标题",
  "content": "文档正文内容，支持 markdown",
  "source": "KZOCR",
  "source_id": "kzocr-xxx",
  "format": "markdown",
  "doc_type": "raw",
  "metadata": {
    "key": "value"
  }
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `title` | string | 是 | 文档标题 |
| `content` | string | 是 | 文档正文 |
| `source` | string | 否 | 来源标识，默认 `"KZOCR"` |
| `source_id` | string | 否 | 来源方 ID，缺失时自动生成 |
| `format` | string | 否 | 文档格式，默认 `"markdown"` |
| `doc_type` | string | 否 | 文档类型，默认 `"raw"` |
| `metadata` | object | 否 | 自定义元数据，以 JSON 存储 |

**响应：** `201`

```json
{
  "status": "ok",
  "doc_id": "sha256-xxx",
  "version_id": 1,
  "message": "document ingested"
}
```

**错误：**

| 状态码 | 说明 |
|--------|------|
| `400` | `title` 或 `content` 缺失 |

---

## 检索

### `GET /search?q=关键词&page=0&per=20&source=obsidian`

全文检索（中文 trigram 子串匹配；< 3 字符自动退回 LIKE）。支持 page/per/source 参数。

**查询参数：**

| 参数 | 必填 | 说明 |
|------|------|------|
| `q` | 是 | 检索关键词 |
| `page` | 否 | 页码，默认 `0` |
| `per` | 否 | 每页条数，默认 `20` |
| `source` | 否 | 来源过滤（如 `obsidian`、`kzocr`） |

**响应：** `200`

```json
{
  "hits": [
    {
      "doc_id": "sha256-xxx",
      "title": "伤寒论",
      "snippet": "...<mark>关键词</mark>所在的上下文片段...",
      "source": "obsidian",
      "score": 1.0
    }
  ],
  "total": 264,
  "page": 0,
  "per_page": 20
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `hits` | array | 匹配结果列表，每项含 `doc_id`、`title`、`snippet`（含 `<mark>` 高亮）、`source`、`score` |
| `total` | int | 匹配总数 |
| `page` | int | 当前页码 |
| `per_page` | int | 每页条数 |

### `GET /semantic?q=关键词&k=5`

语义检索（向量 / ANN，接真实模型后质量提升）。

**查询参数：**

| 参数 | 必填 | 说明 |
|------|------|------|
| `q` | 是 | 检索关键词/句子 |
| `k` | 否 | 返回结果数，默认 `5` |

**响应：** `200`

```json
[
  {
    "doc_id": "sha256-xxx",
    "score": 0.9234
  },
  {
    "doc_id": "sha256-yyy",
    "score": 0.8512
  }
]
```

---

## 数据看板

### `GET /stats`

数据看板统计概览。

**查询参数：** 无

**响应：** `200`

```json
{
  "total": 1861,
  "sources": {
    "obsidian": 1711,
    "kzocr": 100,
    "quip": 50
  },
  "today": 0,
  "recent": [
    {
      "doc_id": "sha256-xxx",
      "title": "伤寒论",
      "updated_at": "2026-04-01T12:00:00"
    }
  ]
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `total` | int | 文档总数 |
| `sources` | object | 各来源文档数 |
| `today` | int | 今日入库数 |
| `recent` | array | 最近更新文档列表 |

---

## 临床 — 患者管理

### `POST /clinical/patients`

登记新患者。

**请求体：**

```json
{
  "id": "p1",
  "name": "张三",
  "gender": "男",
  "born": "1980-01-01"
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `id` | string | 是 | 患者唯一标识 |
| `name` | string | 是 | 患者姓名 |
| `gender` | string | 否 | 性别 |
| `born` | string | 否 | 出生日期（ISO 格式） |

**响应：** `201`

```json
{
  "id": "p1"
}
```

### `GET /clinical/patients`

列出所有已登记患者。

**响应：** `200` — 患者列表

## 临床 — 病历

### `POST /clinical/records`

新增病历。

**请求体：**

```json
{
  "patient_id": "p1",
  "diagnosis": "太阳病",
  "prescription": "桂枝汤",
  "note": "首诊"
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `patient_id` | string | 是 | 患者 ID |
| `diagnosis` | string | 否 | 诊断 |
| `prescription` | string | 否 | 处方 |
| `note` | string | 否 | 备注 |

**响应：** `201`

```json
{
  "id": "rec-xxx"
}
```

## 临床 — 问诊

### `POST /clinical/consultations`

新增问诊记录。

**请求体：**

```json
{
  "patient_id": "p1",
  "chief_complaint": "发热",
  "tongue_pulse": "舌红苔薄白，脉浮",
  "differentiation": "表虚",
  "plan": "调和营卫"
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `patient_id` | string | 是 | 患者 ID |
| `chief_complaint` | string | 否 | 主诉 |
| `tongue_pulse` | string | 否 | 舌脉 |
| `differentiation` | string | 否 | 辨证 |
| `plan` | string | 否 | 治疗方案 |

**响应：** `201`

```json
{
  "id": "cst-xxx"
}
```

## 临床 — 数字孪生

### `POST /clinical/twin/{pid}/summarize`

生成患者数字孪生体摘要。聚合该患者的病历和问诊记录，调用 LLM（若配置）生成摘要；无模型时返回模板兜底。

**路径参数：**

| 参数 | 说明 |
|------|------|
| `pid` | 患者 ID |

**请求体：** 无

**响应：** `200`

```json
{
  "patient_id": "p1",
  "summary": "患者张三，男，1980年出生。诊断：太阳病..."
}
```

---

## 门诊运营 — 排班

### `POST /ops/schedules`

新增排班。

**请求体：**

```json
{
  "date": "2026-04-01",
  "doctor": "王医生",
  "slot": "上午"
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `date` | string | 是 | 日期（YYYY-MM-DD） |
| `doctor` | string | 是 | 医生姓名 |
| `slot` | string | 是 | 时段（如"上午""下午"） |

**响应：** `201`

```json
{
  "id": "sch-xxx"
}
```

## 门诊运营 — 预约

### `POST /ops/appointments`

预约挂号。

**请求体：**

```json
{
  "patient_id": "p1",
  "date": "2026-04-01",
  "doctor": "王医生"
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `patient_id` | string | 是 | 患者 ID |
| `date` | string | 是 | 预约日期（YYYY-MM-DD） |
| `doctor` | string | 是 | 医生姓名 |

**响应：** `201`

```json
{
  "id": "apt-xxx"
}
```

### `GET /ops/appointments?date=2026-04-01`

按日期列出预约。

**查询参数：**

| 参数 | 必填 | 说明 |
|------|------|------|
| `date` | 否 | 日期筛选（YYYY-MM-DD），不传则返回全部 |

**响应：** `200` — 预约列表

## 门诊运营 — 就诊

### `POST /ops/visits`

签到就诊。

**请求体：**

```json
{
  "appointment_id": "apt-xxx",
  "patient_id": "p1",
  "note": "首诊记录"
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `appointment_id` | string | 是 | 预约 ID |
| `patient_id` | string | 是 | 患者 ID |
| `note` | string | 否 | 就诊备注 |

**响应：** `201`

```json
{
  "id": "vis-xxx"
}
```

---

## 考试培训

### `POST /exam/questions`

新增考题。

**请求体：**

```json
{
  "kind": "mcq",
  "stem": "下列哪项不属于太阳病？",
  "options": ["发热", "恶寒", "头项强痛", "烦躁"],
  "answer": "烦躁",
  "explanation": "太阳病以发热、恶寒、头项强痛为主症...",
  "source_doc": "sha256-xxx"
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `kind` | string | 否 | 题型，默认 `"mcq"` |
| `stem` | string | 否 | 题干 |
| `options` | string[] | 否 | 选项列表 |
| `answer` | string | 否 | 正确答案 |
| `explanation` | string | 否 | 解析 |
| `source_doc` | string | 否 | 来源文档 ID |

**响应：** `201`

```json
{
  "id": "q-xxx"
}
```

### `GET /exam/questions?kind=mcq`

列出考题。可按 `kind` 筛选。

**查询参数：**

| 参数 | 必填 | 说明 |
|------|------|------|
| `kind` | 否 | 题型筛选（如 `"mcq"`），不传则返回全部 |

**响应：** `200` — 考题列表

### `POST /exam/generate`

生成考题（调用 LLM 出题；无模型时返回占位题干）。

**请求体：**

```json
{
  "topic": "少阳证",
  "source_doc": "sha256-xxx"
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `topic` | string | 是 | 出题主题 |
| `source_doc` | string | 否 | 参考来源文档 ID |

**响应：** `200`

```json
{
  "kind": "mcq",
  "stem": "...",
  "options": ["A", "B", "C", "D"],
  "answer": "...",
  "explanation": "...",
  "source_doc": ""
}
```

---

## 全局错误响应

| 状态码 | 说明 |
|--------|------|
| `400` | 请求体格式错误（JSON 解析失败）或必填字段缺失 |
| `404` | 资源不存在或路径未匹配 |
| `500` | 服务端内部错误（详见响应 `error` 字段） |

错误响应格式：

```json
{
  "error": "错误描述信息"
}
```
