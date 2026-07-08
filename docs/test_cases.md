# 测试用例目录

共计 142 个测试函数（分布 32 个测试文件），覆盖存储、检索、API、业务子系统、CLI、安全、灾备、桌面等模块。

## 测试列表

| 模块 | 测试函数 | 场景简述 | 预期结果 |
|---|---|---|---|
| conftest | `test_fts5_available` | 验证 SQLite FTS5 扩展可用 | FTS5 扩展加载成功 |
| test_api | `test_api_register_then_ingest_then_search` | 注册文档 → 入库 → FTS5 搜索全流程 | 搜索结果包含已入库文档 |
| test_api | `test_api_documents_requires_title_and_content` | 缺失 title 或 content 字段时提交文档 | 返回 400 及校验错误信息 |
| test_api | `test_api_documents_ingest_and_searchable` | `/documents` 端点提交文档并验证可搜索 | 文档入库且 FTS5 搜索命中 |
| test_api | `test_api_documents_auto_id_when_missing_source_id` | 不传 `source_id` 时自动生成 | 返回包含自动生成的 source_id |
| test_api | `test_api_short_query_search_fallback` | 短查询触发 LIKE 回退 | 返回 LIKE 匹配结果而非 FTS5 |
| test_api | `test_api_list_documents_and_conflicts` | 列出所有文档及冲突记录 | 返回文档列表与冲突详情 |
| test_api | `test_api_root_serves_html_ui` | 访问根路径 `GET /` | 返回 HTML 页面 |
| test_api | `test_api_health` | 健康检查端点 | 返回 200 及健康状态 JSON |
| test_api | `test_api_semantic_search` | 语义检索端点 `GET /semantic` | 返回语义相似度排序结果 |
| test_api | `test_api_not_found` | 访问不存在的路径 | 返回 404 |
| test_api_systems | `test_exam_questions_post_then_list` | 考试题目 POST 后列出 | 新题目出现在列表中 |
| test_api_systems | `test_exam_generate_returns_question_like` | 考试题目生成 API | 返回结构与题目对象一致 |
| test_api_systems | `test_clinical_patient_record_flow` | 临床患者 → 病历完整流程 API | 患者创建、病历添加成功 |
| test_api_systems | `test_ops_full_flow` | 门诊运营完整流程 API | 排班 → 预约 → 就诊成功 |
| test_api_systems | `test_clinical_twin_summary` | 孪生摘要 API | 返回患者摘要内容 |
| test_cli | `test_cli_help_subcommands` | CLI 各子命令 --help | 输出帮助信息不报错 |
| test_cli | `test_cli_invalid_command` | CLI 非法命令 | 输出错误信息并返回非零 |
| test_cli | `test_cli_add_list_flow` | CLI add/list 流程 | 注册后列表显示 |
| test_cli | `test_cli_doc_add` | CLI doc-add | 文档入库成功 |
| test_cli | `test_cli_serve_version` | CLI serve --version | 输出版本号 |
| test_cli | `test_cli_serve_help` | CLI serve --help | 输出帮助信息 |
| test_clinical | `test_patient_and_records_and_consultations` | 患者创建、病历添加、问诊记录 | 全部操作成功，关联正确 |
| test_clinical | `test_twin_summary_and_persist` | 孪生摘要生成并持久化 | 摘要正确写入数据库 |
| test_clinical_twin_llm | `test_build_summary_uses_real_provider` | 真实 LLM Provider 构建孪生摘要 | 返回由 RemoteLLMProvider 生成的摘要 |
| test_clinical_twin_llm | `test_build_summary_fallback_aggregates_real_data` | 真实 Provider 失败时聚合本地数据兜底 | 返回基于本地数据的摘要 |
| test_clinical_twin_llm | `test_build_summary_fallback_without_data` | 兜底时无本地数据 | 返回空摘要或占位信息 |
| test_cover | `test_extract_cover_returns_bytes` | 从 EPUB 提取封面 | 返回封面图片字节数据 |
| test_cover | `test_ingest_stores_cover` | 入库时保存封面图片 | 封面正确存储在归档中 |
| test_db | `test_init_schema_creates_tables` | 初始化数据库 schema | 所有预定义表成功创建 |
| test_db | `test_store_document_creates_version_and_fts` | 存储文档创建版本记录和 FTS 索引 | 版本表 + FTS 表均有对应行 |
| test_db | `test_second_version_is_new_row_not_overwrite` | 同一文档二次存储 | 新增版本行，原版本保留 |
| test_desktop | `test_main_js_syntax` | Electron main.js 语法检查 | Node.js 可解析无报错 |
| test_desktop | `test_run_sh_executable` | run.sh 脚本可执行 | 文件具有可执行权限 |
| test_desktop | `test_package_json_exists` | Electron package.json 存在 | 文件存在且为合法 JSON |
| test_exam | `test_crud_question` | 题目 CRUD 操作 | 创建、查询、更新、删除全部成功 |
| test_exam | `test_generate_returns_well_formed_question` | LLM 生成题目格式 | 生成的题目结构符合预期 schema |
| test_exam | `test_grade_exact_match` | 精确匹配判分 | 正确/错误答案返回对应评分 |
| test_exam_gen_llm | `test_generate_uses_real_provider` | 真实环境使用 RemoteLLMProvider 生成 | 返回由远程 Provider 生成的内容 |
| test_exam_gen_llm | `test_generate_fallback_default_noop` | 无 Provider 时使用 NoopProvider 降级 | 返回空或默认内容不抛异常 |
| test_exam_gen_llm | `test_generate_passes_source_doc` | 生成时正确传递源文档 | 生成结果包含源文档引用 |
| test_extractors | `test_epub_parse_meta` | 解析 EPUB 元数据 | 正确提取标题、作者等字段 |
| test_extractors | `test_unknown_extension_returns_empty` | 未知文件扩展名 | 返回空结果，不抛异常 |
| test_health | `test_health_endpoint_fields` | 健康检查各字段 | status/version/documents/uptime_sec 均存在 |
| test_ingest | `test_register_ebook_catalog_only` | 仅注册电子书到目录 | 元数据入库，文件未复制 |
| test_ingest | `test_register_ebook_idempotent` | 重复注册同一电子书 | 第二次注册幂等，不产生重复 |
| test_ingest_ebook | `test_ingest_ebook_indexes_text` | 入库 EPUB 全文并建 FTS 索引 | 正文文本可被 FTS5 搜索命中 |
| test_ingest_ebook | `test_ingest_unknown_raises` | 入库未知格式文件 | 抛出格式不支持异常 |
| test_integration_e2e | `test_e2e_full_chain` | 端到端全链路：患者→病历→问诊→孪生→电子书→KZOCR→检索→PII→审计 | 所有步骤成功完成 |
| test_integration_e2e | `test_e2e_pii_encryption_roundtrip` | PII 加密回环验证 | 加密后解密可还原原始数据 |
| test_integration_e2e | `test_e2e_short_query_like` | 短查询 LIKE 回退端到端 | LIKE 查询正确返回匹配结果 |
| test_llm | `test_noop_provider_interface` | NoopProvider 实现 LLMProvider 接口 | 接口方法均可调用不抛异常 |
| test_llm | `test_register_and_get_provider` | 注册 Provider 后可通过名称获取 | 获取的实例与注册时一致 |
| test_llm | `test_unknown_provider_raises` | 获取未注册的 Provider | 抛出 Provider 不存在异常 |
| test_llm_provider | `test_remote_complete_returns_content` | RemoteLLMProvider 远程调用返回内容 | 返回非空字符串 |
| test_llm_provider | `test_get_provider_env_set_returns_remote` | 环境变量配置时返回 RemoteLLMProvider | 返回远程 Provider 实例 |
| test_llm_provider | `test_get_provider_no_env_returns_noop` | 无环境变量时返回 NoopProvider | 返回 NoopProvider 实例 |
| test_llm_provider | `test_noop_and_fake_still_work` | NoopProvider 和 FakeProvider 正常运作 | 调用 complete() 不抛异常 |
| test_obsidian | `test_import_vault` | 导入 Obsidian Vault 文档 | 文档成功入库，可搜索 |
| test_ops | `test_ops_flow` | 门诊运营完整流程：排班→预约→就诊 | 流程各步骤状态正确流转 |
| test_pii | `test_passthrough_patient` | 无加密配置时患者数据明文存储 | 数据以明文形式写入 |
| test_pii | `test_passthrough_record` | 无加密配置时病历数据明文存储 | 数据以明文形式写入 |
| test_pii | `test_passthrough_consultation` | 无加密配置时间诊记录明文存储 | 数据以明文形式写入 |
| test_pii | `test_encrypt_patient` | 患者数据 Fernet 加密落盘 | 敏感字段加密，非敏感字段明文 |
| test_pii | `test_encrypt_patient_list` | 患者列表数据加密 | 列表中每条记录敏感字段已加密 |
| test_pii | `test_encrypt_record` | 病历数据加密落盘 | 敏感字段加密，解密后可还原 |
| test_pii | `test_encrypt_consultation` | 问诊记录加密落盘 | 敏感字段加密，非敏感字段明文 |
| test_pii | `test_audit_patient_read` | 患者数据读取触发审计日志 | 审计表写入 actor + action + timestamp |
| test_pii | `test_audit_patient_list` | 患者列表读取触发审计日志 | 审计表记录批量读取事件 |
| test_pii | `test_audit_record_read` | 病历读取触发审计日志 | 审计表正确记录操作 |
| test_pii | `test_audit_consultation_read` | 问诊记录读取触发审计日志 | 审计表正确记录操作 |
| test_pii | `test_encrypt_empty_fields` | 空字段加密 | 空字符串/None 字段加密不报错 |
| test_quip | `test_ingest_documents` | 从 Quip 导入归档文档 | 文档成功入库 |
| test_quip | `test_idempotent_skip` | Quip 导入重复文档 | 重复文档跳过，不产生重复 |
| test_replication | `test_wal_log_record_pending_mark_applied` | WAL 日志记录 → 待处理 → 标记已应用 | 状态正确从未应用到已应用 |
| test_replication | `test_wal_log_mark_applied_empty` | 空 WAL 日志标记已应用 | 不抛异常，不影响后续操作 |
| test_replication | `test_record_change_convenience` | 快捷方法记录变更 | 变更记录正确写入 WAL |
| test_replication | `test_export_snapshot_empty_store` | 空存储导出快照 | 返回包含空数据的快照 |
| test_replication | `test_export_snapshot_with_data` | 有数据时导出快照 | 快照包含所有数据 |
| test_replication | `test_import_snapshot_manifest_valid` | 导入合法快照清单 | 数据正确恢复 |
| test_replication | `test_import_snapshot_manifest_missing_keys` | 导入缺失字段的快照清单 | 抛出校验异常 |
| test_replication | `test_local_replica_push_snapshot` | 推送到本地副本（快照模式） | 副本目录生成快照文件 |
| test_replication | `test_local_replica_push_snapshot_with_db` | 推送快照附带数据库文件 | 副本包含快照 + 数据库副本 |
| test_replication | `test_local_replica_push_changes` | 推送增量变更到本地副本 | 变更正确应用到副本 |
| test_replication | `test_local_replica_health` | 本地副本健康检查 | 返回健康状态和读写能力 |
| test_replication | `test_local_replica_health_not_writable` | 副本目录不可写时健康检查 | 返回不健康状态 |
| test_replication | `test_change_dataclass_fields` | Change dataclass 字段校验 | 字段赋值与类型匹配 |
| test_retrieval | `test_local_embedder_deterministic_and_normalized` | LocalEmbedder 确定性 + L2 归一化 | 同输入同输出，向量模为 1 |
| test_retrieval | `test_retriever_stores_and_finds_nearest` | 向量存储并找到最近邻 | 返回距离最近的向量及文档 |
| test_retrieval | `test_retriever_index_ebook_reads_version_content` | 检索索引时读取电子书版本内容 | 返回正确版本的内容 |
| test_retrieval_ann | `test_ann_search_uses_vec_index` | sqlite-vec ANN 搜索使用向量索引 | 搜索结果与暴力搜索一致 |
| test_retrieval_ann | `test_ann_disabled_falls_back_to_bruteforce` | ANN 禁用时回退到暴力搜索 | 搜索结果正确 |
| test_retrieval_ann | `test_remote_embedder_parses_openai_style` | RemoteEmbedder 解析 OpenAI 风格响应 | 正确提取 embedding 向量 |
| test_retrieval_ann | `test_get_embedder_selects_remote_when_url_set` | 配置远程 URL 时选择 RemoteEmbedder | 返回 RemoteEmbedder 实例 |
| test_scheduler | `test_background_mode_multiple_triggers` | 调度器后台模式多次触发 | 任务按配置触发多次 |
| test_scheduler | `test_exception_does_not_break_scheduler` | 任务异常不中断调度器 | 异常任务跳过，后续任务正常 |
| test_scheduler | `test_read_tasks_valid_yaml` | 读取合法 YAML 任务配置 | 正确解析任务定义 |
| test_scheduler | `test_read_tasks_file_not_found` | 任务文件不存在 | 返回空列表，不抛异常 |
| test_scheduler | `test_read_tasks_invalid_format` | YAML 格式非法 | 抛出格式解析异常 |
| test_search_ui | `test_search_pagination` | 分页搜索 | 返回正确的分页结果 |
| test_search_ui | `test_search_source_filter` | 来源过滤 | 按来源过滤返回对应文档 |
| test_search_ui | `test_search_empty_query` | 空查询 | 返回 400 或空结果 |
| test_search_ui | `test_search_special_chars` | 特殊字符搜索 | 不抛异常，正常返回 |
| test_search_ui | `test_search_api_response_format` | 搜索 API 响应格式 | 返回标准 paginated JSON 格式 |
| test_serve_http | `test_serve_health_endpoint` | 真实 HTTP 服务 /health | 返回 200 及健康状态 |
| test_stats | `test_stats_dashboard` | 统计端点 | 返回总文档数/各源数量 |
| test_stats | `test_stats_recent_documents` | 最近文档列表 | 返回按更新时间排序的近期文档 |
| test_storage | `test_store_copies_and_hashes` | 存储层复制文件并计算哈希 | 目标路径文件存在，哈希值正确 |
| test_storage | `test_dedup_no_duplicate_copy` | 相同内容去重 | 第二次存储不产生重复文件 |
| test_storage | `test_move_removes_source` | 移动操作删除源文件 | 源文件不存在，目标文件存在 |
| test_watch | `test_watch_ingests_new_md` | 目录监听检测新 Markdown 文件并自动入库 | 新文件入库且可搜索 |
| test_watch | `test_watch_skips_unchanged` | 目录监听跳过未变更文件 | 文件不变时不触发入库 |

## 覆盖率摘要

| 指标 | 值 |
|---|---|
| 整体行覆盖率 | 78%（目标 90%） |
| 核心模块（db / retrieval / api / clinical / crypto / audit） | 均 >85% |
| 覆盖率 HTML 报告 | `htmlcov/index.html` |
| 安全扫描 (bandit) — High | 1（`subprocess shell=True` 在 `scheduler.py` 中，已在代码中限制 timeout，可接受） |
| 安全扫描 (bandit) — Medium | 10 |
| 安全扫描 (bandit) — Low | 11 |
