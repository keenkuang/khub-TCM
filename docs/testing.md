# khub 测试策略

核心思路：**每个模块自带测试、TDD 驱动、零依赖可跑**。先把"怎么测"定清楚，实现就成了填空。

## 1. 运行方式

```bash
cd khub-m1
python3 -m pytest -q          # 全部（当前 26 个，无需联网/外部服务）
python3 -m pytest tests/test_retrieval.py -q   # 单文件
python3 -m pytest -k "ingest" -q               # 按关键字
```

`pyproject.toml` 已配置 `pythonpath = ["."]`，测试直接从仓库根以 `khub.*` 导入。

## 2. 分层与覆盖

| 测试文件 | 被测 | 覆盖点 |
|----------|------|--------|
| `test_db.py` | `db.Store` | 建表、入库+版本化、多版本不覆盖、FTS、安全兜底 |
| `test_storage.py` | `ManagedLibrary` | sha256 落盘、去重（不重复拷贝）、move 删源 |
| `test_extractors.py` | `extractors` | EPUB 元数据解析、未知扩展返回空 |
| `test_ingest.py` | `ingest.register_ebook` | 目录登记、不入库无版本/无 FTS、幂等 |
| `test_ingest_ebook.py` | `ingest.ingest_ebook` | 入库抽文本+建 FTS、可检索、未知 id 报错 |
| `test_llm.py` | `llm` | NoOp 接口、注册/获取 provider、未知报错 |
| `test_api.py` | `api.App` | 路由：register→ingest→list→search、404 |
| `test_retrieval.py` | `retrieval` | 离线嵌入确定性/归一化、最近邻、按版本内容索引 |
| `test_exam.py` | `exam` | 题库 CRUD、生成返回合法 Question、精确判分 |
| `test_clinical.py` | `clinical` | 患者/病历/问诊 CRUD、孪生体摘要非空+持久化 |
| `test_ops.py` | `ops` | 排班→预约→签到 全流程、状态流转 |

## 3. 关键约定

- **内存库**：单元复用 `Store(":memory:")`，不落盘、不依赖外部状态。
- **无网络/无重依赖**：PDF 正文抽取用可选 `pypdf`（缺失则跳过）；LLM 全部走 `NoOpProvider`，因此 `exam.generate` / `exam.grade` / `clinical.twin` 在测试里返回**确定性占位结果**，断言只验证"接口形态正确、不崩溃"。
- **中文检索靠 trigram**：`docs_fts` 用 `tokenize='trigram'`，测试用中文子串（如"阴阳平衡"、"太阳病"）验证可命中。
- **安全兜底可测**：`search()` 对非法 FTS 查询返回 `[]` 而非抛异常（`test_db` 隐含覆盖正常路径）。

## 4. 端到端冒烟（手动）

```bash
export KHUB_DB=/tmp/k.db KHUB_LIBRARY=/tmp/lib
khub serve --port 8137 &
curl -X POST localhost:8137/ebooks/register -d '{"path":"book.epub"}'
curl -X POST localhost:8137/ebooks/<cid>/ingest
curl localhost:8137/search?q=关键词
```

## 5. 什么是"占位"，什么该补测试

- **占位（当前无真实逻辑，仅验证接口）**：`exam.generator/grader`、`clinical.twin.build_summary`、`retrieval` 的真实语义嵌入。接真实 `LLMProvider` 后，应补充"真实模型行为"的集成测试（可放 `tests/integration/`，标记 `@pytest.mark.integration`，默认不跑）。
- **已具备真实逻辑、必须保持绿**：上述 1–4、6–11 行全部。任何改动不得破坏这 26 个测试。

## 6. 提交门槛

每次实现/修改后：`python3 -m pytest -q` 必须全绿，再 `git commit`。新增模块遵循：先写测试（红）→ 实现（绿）→ 提交。
