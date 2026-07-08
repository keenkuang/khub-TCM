# API 参考

> REST API 基址：`http://127.0.0.1:8765`（默认绑定 127.0.0.1，端口由 `--port` 指定）

所有请求均使用 JSON 编码。请求头 `Content-Type: application/json`。响应默认为 `application/json; charset=utf-8` 格式。

## API 端点一览

| 方法 | 路径 | 说明 | 请求体 | 响应示例 |
|------|------|------|--------|----------|
| GET | `/` | Web UI 首页 | — | HTML 页面 |
| GET | `/stats` | 数据看板统计 | — | `{"total":1861, "sources":{"obsidian":1711,...}, "today":0, "recent":[...]}` |
| GET | `/health` | 健康检查 | — | `{"status":"ok","version":"0.2.0","documents":42,"uptime_sec":3600.0}` |
| GET | `/ebooks` | 列出电子书 | — | `[{"canonical_id":"sha256-xxx","title":"伤寒论",...}]` |
| POST | `/ebooks/register` | 注册电子书 | `{"path":"...", "move":false}` | `{"canonical_id":"sha256-xxx"}` |
| POST | `/ebooks/{cid}/ingest` | 入库电子书 | — | `{"canonical_id":"sha256-xxx","version_id":3}` |
| GET | `/documents` | 列出全部文档 | — | `[{"canonical_id":"sha256-xxx","title":"伤寒论",...}]` |
| GET | `/conflicts` | 列出冲突文档 | — | `[{"canonical_id":"sha256-xxx","title":"伤寒论"}]` |
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
  "version": "0.2.0",
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
