# khub v0.2.4 测试报告

> 日期: 2026-07-10
> 分支: m1 (commit 66afbbb)
> 运行: `python3 -m pytest -q --tb=no -v`

---

## 执行结果

```
238 passed, 2 skipped in 39.10s
```

## 模块明细

| 测试文件 | 测试数 | 通过 | 跳过 |
|----------|--------|------|------|
| test_api.py | 16 | 16 | 0 |
| test_api_systems.py | 5 | 5 | 0 |
| test_cli.py | 6 | 6 | 0 |
| test_clinical.py | 2 | 2 | 0 |
| test_clinical_twin_llm.py | 3 | 3 | 0 |
| test_cover.py | 2 | 2 | 0 |
| test_db.py | 3 | 3 | 0 |
| test_desktop.py | 3 | 3 | 0 |
| test_exam.py | 3 | 3 | 0 |
| test_exam_gen_llm.py | 3 | 3 | 0 |
| test_extractors.py | 2 | 2 | 0 |
| test_ha.py | 31 | 31 | 0 |
| test_ha_drill.py | 5 | 5 | 0 |
| test_health.py | 1 | 1 | 0 |
| test_ima.py | 4 | 4 | 0 |
| test_ima_notes.py | 4 | 4 | 0 |
| test_ima_probe.py | 3 | 2 | 1 |
| test_ima_push.py | 4 | 4 | 0 |
| test_ingest.py | 2 | 2 | 0 |
| test_ingest_ebook.py | 2 | 2 | 0 |
| test_integration_e2e.py | 3 | 3 | 0 |
| test_llm.py | 3 | 3 | 0 |
| test_llm_provider.py | 4 | 4 | 0 |
| test_normalizer.py | 6 | 6 | 0 |
| test_obsidian.py | 1 | 1 | 0 |
| test_ops.py | 1 | 1 | 0 |
| test_pii.py | 12 | 12 | 0 |
| test_quip.py | 2 | 2 | 0 |
| test_rag.py | 22 | 22 | 0 |
| test_rag_stream.py | 6 | 6 | 0 |
| test_replication.py | 37 | 36 | 1 |
| test_retrieval.py | 2 | 2 | 0 |
| test_retrieval_ann.py | 4 | 4 | 0 |
| test_scheduler.py | 5 | 5 | 0 |
| test_search_ranking.py | 3 | 3 | 0 |
| test_search_ui.py | 5 | 5 | 0 |
| test_security.py | 9 | 9 | 0 |
| test_serve_http.py | 1 | 1 | 0 |
| test_stats.py | 2 | 2 | 0 |
| test_storage.py | 3 | 3 | 0 |
| test_sync_engine.py | 3 | 3 | 0 |
| test_sync_status.py | 5 | 5 | 0 |
| test_watch.py | 2 | 2 | 0 |

## 跳过项说明

- `test_ima_probe::test_ima_probe_real_api` — 需要真实 IMA API 凭据
- `test_replication::test_replication_s3_replica` — 需要 S3 凭据

## 3 轮 Code Review 修复汇总

| 轮次 | P0 发现 | 修复 |
|------|---------|------|
| R1 | pyproject.toml 依赖不全 | 新增 crypto/s3/all optional-group |
| R1 | RAG 空上下文仍调 LLM | ask()/ask_stream() 空 sources 及早返回 |
| R3 | Dockerfile `&& \` 残留语法错误 | 移除多余的管道续行符 |

## 结论

**238 passed, 2 skipped — 发布就绪。**
