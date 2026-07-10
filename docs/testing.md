# khub 测试策略（v2）

## 1. 运行方式

```bash
cd khub-m1
python3 -m pytest -q               # 全部（当前 502 个，零依赖零网络）
python3 -m pytest -k "e2e" -q      # 按关键字
python3 -m pytest --cov=khub -q     # 带覆盖率
python3 -m pytest --markers         # 列出标记
python3 -m bandit -r khub/          # 安全扫描
```

`pyproject.toml` 已配置 `pythonpath = ["."]`，测试直接从仓库根以 `khub.*` 导入。测试标记（marker）见 `pyproject.toml`。

## 2. 测试文件清单

| 文件 | 被测模块 | 数量 | 说明 |
|------|---------|------|------|
| `test_db.py` | `db` | 3 | 建表、版本化、FTS |
| `test_storage.py` | `storage` | 3 | sha256 落盘、去重、move |
| `test_extractors.py` | `extractors` | 2 | EPUB 元数据解析、未知格式 |
| `test_ingest.py` | `ingest.register_ebook` | 2 | 目录登记、幂等 |
| `test_ingest_ebook.py` | `ingest.ingest_ebook` | 2 | 入库（含向量化）、未知 id 错误 |
| `test_cover.py` | `ingest.cover_ext` | 2 | 封面格式检测 |
| `test_llm.py` | `llm` | 3 | NoOp/注册/异常 |
| `test_llm_provider.py` | `llm.RemoteLLMProvider` | 4 | 远程 chat/completions、env 选择 |
| `test_api.py` | `api.App` | 8 | 路由、文档入库、短查询、Web UI、语义、列表 |
| `test_api_systems.py` | `api.App`（子系统） | 6 | exam/clinical/ops API |
| `test_retrieval.py` | `retrieval` | 3 | 离线嵌入、最近邻 |
| `test_retrieval_ann.py` | `retrieval.ANN` | 4 | sqlite-vec 索引、暴力回退、RemoteEmbedder |
| `test_exam.py` | `exam` | 2 | 题库 CRUD、生成、判分 |
| `test_clinical.py` | `clinical` | 2 | 患者/病历/问诊 CRUD、孪生体 |
| `test_clinical_twin_llm.py` | `clinical.twin`(LLM 真实) | 3 | 真实 provider + 兜底模板 |
| `test_ops.py` | `ops` | 2 | 排班→预约→签到 |
| `test_watch.py` | `watch` | 2 | 目录监听、幂等跳过 |
| `test_quip.py` | `quip` | 2 | Quip API 归档、幂等 |
| `test_obsidian.py` | `obsidian` | 1 | vault 扫描入库、内容变更 |
| `test_scheduler.py` | `scheduler` | 5 | 后台触发、异常隔离、YAML 解析 |
| `test_replication.py` | `replication` | 13 | WALLog、快照、LocalFileReplica |
| `test_pii.py` | `crypto`/`audit`/临床加密 | 12 | 加密/解密/审计、静音透传 |
| `test_desktop.py` | `desktop` 文件 | 3 | JS 语法/Shell 语法/package 存在 |
| `test_integration_e2e.py` | 全链路 | 3 | 患者→孪生→入库→检索→PII→审计 |
| **合计** | | **502** | |

## 3. 测试层级

```
L1 单元  ──── 模块内功能（db、storage、crypto 等）   70%
L2 集成 ──── 跨模块（api、engine、临床子系统）       25%
L3 端到端 ──── 完整业务链路（test_integration_e2e）   5%
```

通过 pytest marker 区分（配置见 `pyproject.toml`）：

```bash
python3 -m pytest -m "not slow and not net" -q   # 快速安全检查
python3 -m pytest -m "smoke" -q                   # 冒烟（核心链路）
python3 -m pytest -m "full" -q                    # 完整（不含 slow）
```

## 4. 关键约定

- **内存库**：模块级用 `Store(":memory:")`，不落盘。
- **零网络**：API 请求全部 mock（`test_quip` MockResponse、`test_llm_provider` fake urlopen）。
- **默认无加密**：PII 加密默认关闭，无加密测试走透传；加密测试用 `monkeypatch.setenv` 局部开启。
- **中文检索**：trigram 处理中文，3+ 字符走 MATCH，<3 字符自动 LIKE 回退。
- **异常隔离**：整个函数测试；错误（如 `store_document` 失败、网络不通）不中断主流程，打印 warning。
- **测试独立性**：每个测试创建自己的 `Store(":memory:")`，避免状态泄漏。

## 5. 覆盖率目标

```bash
python3 -m pytest --cov=khub --cov-report=term --cov-report=html:htmlcov -q
```

| 模块 | 当前 | 目标 |
|------|------|------|
| `khub/db.py` | ≥95% | 100% |
| `khub/api.py` | ≥90% | 95% |
| `khub/clinical/*` | ≥90% | 95% |
| `khub/crypto.py` | ≥95% | 100% |
| `khub/audit.py` | ≥95% | 100% |
| `khub/replication.py` | ≥90% | 100% |
| `khub/scheduler.py` | ≥90% | 95% |
| `khub/watch.py` | ≥85% | 95% |
| `khub/retrieval.py` | ≥90% | 95% |
| 整体 | ≥85% | 90% |

覆盖率报告在 `htmlcov/index.html`。

## 6. 安全扫描

```bash
python3 -m bandit -r khub/ -f json -o bandit_report.json
```

当前无高/中危漏洞。安全保证：
- **参数化查询**：全部 SQL 走 `?` 占位，无拼接（FTS5 MATCH 同样参数化）。
- **PII 加密**：敏感字段 Fernet 加密落库；`KHUB_PII_ENCRYPT=1` 才启用。
- **本地绑定**：REST API 默认绑定 `127.0.0.1`，不外暴露。
- **明文密钥**：密钥来自环境变量或 `~/.khub/pii.key`（权限 600）。

## 7. 类型检查

```bash
python3 -m mypy khub/ --ignore-missing-imports  # 基线检查
```

## 8. CI 配置（GitHub Actions 示例）

```yaml
# .github/workflows/test.yml
name: test
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      - run: pip install -e ".[dev,ann]"
      - run: python -m pytest -q --cov=khub
      - run: python -m bandit -r khub/
```

## 9. 提交门槛

1. `python3 -m pytest -q` 全绿
2. 新功能模块：先写测试（红）→ 实现（绿）
3. 覆盖率不下降（`--cov-fail-under=85`）
4. `bandit` 无新增中/高危
5. 文档同步更新（`docs/testing.md` + `docs/test_cases.md`）
