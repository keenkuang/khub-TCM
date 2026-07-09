# khub 测试计划

> 版本: 0.2.4
> 分支: master
> 日期: 2026-07-10

---

## 一、测试范围

### 模块清单

| 模块 | 测试文件 | 测试数 | 优先级 |
|------|----------|--------|--------|
| 核心存储 (db.py) | `test_db.py` | 3 | P0 |
| 全文检索 | `test_retrieval.py`, `test_retrieval_ann.py` | 11 | P0 |
| REST API | `test_api.py`, `test_api_systems.py` | 16 | P0 |
| CLI | `test_cli.py` | 8 | P0 |
| 电子书入库 | `test_ingest.py`, `test_ingest_ebook.py` | 3 | P0 |
| 提取器 | `test_extractors.py` | 1 | P0 |
| 同步引擎 | `test_sync_engine.py` | 3 | P0 |
| 数据源 Quip | `test_quip.py` | 2 | P1 |
| 数据源 Obsidian | `test_obsidian.py` | 2 | P1 |
| 数据源 IMA | `test_ima.py`, `test_ima_push.py`, `test_ima_notes.py`, `test_ima_probe.py` | 7 | P1 |
| 双机热备 | `test_ha.py`, `test_ha_drill.py` | 36 | P1 |
| 灾备复制 | `test_replication.py` | 37 | P1 |
| PII 加密 | `test_pii.py` | 6 | P1 |
| 审计 | `test_cover.py` | 1 | P1 |
| 临床子系统 | `test_clinical.py`, `test_clinical_twin_llm.py` | 4 | P1 |
| 考试子系统 | `test_exam.py`, `test_exam_gen_llm.py` | 4 | P1 |
| 门诊运营 | `test_ops.py` | 2 | P1 |
| 调度器 | `test_scheduler.py` | 6 | P1 |
| 桌面 GUI | `test_desktop.py` | 1 | P1 |
| 健康检查 | `test_health.py` | 1 | P1 |
| 搜索排名 | `test_search_ranking.py` | 1 | P1 |
| WebUI | `test_search_ui.py` | 1 | P1 |
| 服务 HTTP | `test_serve_http.py` | 2 | P1 |
| RAG 问答 | `test_rag.py`, `test_rag_stream.py` | 28 | P1 |
| 端到端集成 | `test_integration_e2e.py` | 2 | P1 |
| **新增：Docker 部署** | — | 0 | P1 |
| **新增：同步状态** | `test_sync_status.py` | 5 | P2 |
| **新增：安全测试** | `test_security.py` | 9 | P1 |

### 新增模块测试要求

#### Docker 部署（待补充）
- Dockerfile 构建成功
- docker-compose 启动/停止
- 健康检查通过
- nginx 反向代理正常
- 限流生效

## 二、测试策略

### 单元测试（已有）
- `python3 -m pytest -q` — 全量运行

### 集成测试（已有）
- `test_integration_e2e.py` — 全链路端到端
- `test_serve_http.py` — HTTP 服务层

### Docker 测试（新增，手动）
```bash
# 构建
docker compose build khub

# 启动
docker compose up -d

# 验证健康检查
curl -k https://localhost/health

# 验证限流
for i in $(seq 1 30); do curl -s -k https://localhost/health >/dev/null; done
# 第 31 次应返回 503

# 停止
docker compose down
```

## 三、测试执行计划

| 阶段 | 操作 | 预期 |
|------|------|------|
| phase-1 | `pytest -q` | 238 passed / 2 skipped |
| phase-2 | `docker compose build` | 构建成功 |
| phase-3 | `docker compose up` | 健康检查通过 |
| phase-4 | curl 测试限流 | 30r/m 限流正确 |
| phase-5 | `docker compose down` | 正常停止 |

## 四、测试报告

最终测试报告将在所有测试执行完成后生成，包含：
- 测试总数 / 通过 / 失败 / 跳过
- 失败用例详情
- 覆盖率数据
