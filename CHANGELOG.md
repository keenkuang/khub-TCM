# 变更日志

## [0.6.0] — 2026-07-10

### 开放平台与插件系统

**跃升至 0.6.x 系列——从封闭应用升级为开放平台。**

#### 插件系统
- `khub/plugins/base.py`：`PluginBase` 抽象类，定义 `on_startup`/`on_request`/`on_shutdown` 生命周期接口
- `khub/plugins/registry.py`：插件注册表（自动发现/加载/生命周期管理/请求拦截）
- `khub/plugins/examples/hello.py`：示例插件，在每次请求时记录日志
- `GET /api/plugins` 端点 + `khub plugin-list` CLI 子命令
- 服务启动时自动发现并加载插件

#### Webhook 事件推送
- `webhook_subscriptions` + `webhook_deliveries` 表（接 WAL 复制）
- 支持 6 种事件类型：`document.created`、`appointment.created`、`consultation.created`、`followup.due`、`course.enrolled`、`record.created`
- HMAC-SHA256 签名验证 + 异步投递 + 投递记录持久化
- REST 端点（订阅/取消/列表）+ CLI 子命令

#### OpenAPI 文档
- `GET /api/openapi.json` — OpenAPI 3.0.3 规范
- `GET /api/docs` — Swagger UI 交互式文档页（CDN 加载）

### 测试
- 新增 11 个测试（插件 5 + Webhook 6），全部通过

## [0.5.1] — 2026-07-10

### 私有化部署与 OEM 产品化

#### 一键安装
- `install.sh`：自动检测 OS（Ubuntu/Debian/CentOS），安装 Python/SQLite，创建 khub 用户和数据目录，pip 安装，数据库初始化，配置 systemd 服务
- 单命令部署：`curl -fsSL https://raw.githubusercontent.com/keenkuang/khub-TCM/master/install.sh | bash`

#### Docker 生产完善
- Dockerfile 多阶段构建（builder → runtime），减小镜像体积
- docker-compose.yml 追加生产配置：`restart: always`、`logging`（json-file, 10m/3 文件）、健康检查

#### Helm Chart（K8s 部署）
- 标准 Helm chart 结构：Chart.yaml、values.yaml、templates/（deployment/service/configmap/ingress/pvc/_helpers）
- 可配置副本数、镜像、域名、存储大小、环境变量

#### 白标定制
- `KHUB_BRAND_NAME` / `KHUB_BRAND_LOGO` 环境变量
- `GET /api/info` 返回品牌信息（名称/版本/logo/uptime）
- Web UI 前端动态读取品牌信息设置页面标题和 logo

### 测试
- 新增 `/api/info` 端点测试

## [0.5.0] — 2026-07-10

### 中医知识图谱与推理引擎

**跃升至 0.5.x 系列——从业务管理升级为知识智能。**

#### 知识图谱模型
- 5 张业务表：`kg_herbs`（60+ 中药，含四气五味归经功效毒性）、`kg_formulas`（20 经典方剂，含组成/出处/功效）、`kg_syndromes`（14 证型，含八纲分类/症状/舌脉/治法）、`kg_methods`（8 治法）、`kg_relations`（通用关系边，支撑推理）
- 全部接 WAL 复制触发

#### 种子数据
- 60+ 常用中药（桂枝汤/麻黄汤/六味地黄丸 等全部组成药物）
- 20 经典方剂（伤寒论/温病条辨/太平惠民和剂局方 等来源）
- 14 证型（八纲+脏腑辨证，含典型症状舌脉）
- 8 治法（汗吐下和温清消补）
- 证型→方剂关系边（syndrome→formula 的 indicates 关联）

#### 推理引擎（`inference.py`）
- 四层推导链：证型 → 治法 → 方剂 → 中药 → 归经 → 禁忌
- `infer(store, syndrome_name)` 返回治法列表、推荐方剂、关键中药、归经、禁忌中药
- 纯规则驱动（基于 `kg_relations` 关系边），零外部依赖

#### 方剂相似度
- Jaccard 相似度算法（基于组成中药集合的交并比）
- `formula_similarity(store, name1, name2)` 返回 0-1 相似度分数

#### 接口
- REST：5 个端点（`GET /api/kg/infer?syndrome=`、`GET /api/kg/herbs`、`GET /api/kg/formulas`、`GET /api/kg/syndromes`、`GET /api/kg/similarity?f1=&f2=`）
- CLI：`kg-infer`、`kg-herbs [--channel] [--nature]`、`kg-formulas [--category]`、`kg-similarity <f1> <f2>`

### 测试
- 新增 7 个测试（中药 CRUD/搜索、方剂 CRUD/相似度、推理引擎）全部通过

## [0.4.1] — 2026-07-10

### 小程序客户端

#### 后端补充
- `GET /ops/appointments` 支持 `?patient_id=` 参数过滤
- 新增 `GET /clinical/consultations?patient_id=` 端点

#### 小程序前端（`miniapp/`）
- **登录页**：用户名密码 → `/auth/login` → token 缓存
- **首页**：患者端四入口（预约/摘要/趋势/问诊）+ 医生端患者列表
- **预约列表**：按患者/医生身份显示预约记录
- **孪生摘要**：健康摘要 + 时间线（患者视角）
- **健康趋势**：体质画像 + 证型演变 + 治疗序列
- `utils/api.js`：统一 REST 封装 + Bearer token 自动注入

### 测试
- 新增 2 个测试（appointments patient_id 过滤 + consultations 端点）
- 小程序端 20 个文件（WXML+WXSS+JS）

## [0.4.0] — 2026-07-10

### 临床智能增强（四线合一）

**跃升至 0.4.x 系列——从数据管理升级为智能分析。**

#### 临床知识图谱（`analysis.py`）
- `build_syndrome_formula_matrix(store)`：全库/按患者统计（辨证→方剂）关联频次矩阵
- `analyze_constitution_evolution(store, pid)`：患者证型变化序列、去重计数、首末对比

#### 孪生可视化（`visualize.py`）
- `get_health_trends(store, pid)`：返回时间线 + 治疗序列 + 体质画像的结构化数据（前端渲染用）
- `_infer_constitution()`：朴素规则体质推断（7 种偏颇体质关键词匹配）

#### AI 辅助辨证（`diagnosis.py`）
- `_SYNDROME_FORMULA_MAP`：14 种证型 ↔ 50+ 经典方剂离线知识库
- `suggest_formula(syndrome, provider)`：LLM 推荐 + 离线知识库降级
- `check_incompatibility(formulas)`：十八反十九畏基础配伍检查（10 对禁忌）

#### 疗效追踪（`tracking.py`）
- `evaluate_efficacy(store, pid)`：就诊频次 + 随访依从性 → 疗效评估（good/needs_improvement/consistent/early_stage）

#### 接口
- REST：5 个端点（`GET /clinical/analysis/{id}/matrix|evolution`、`GET /clinical/tracking/{id}`、`GET /clinical/trends/{id}`、`POST /clinical/diagnosis/suggest`）
- CLI：`clinical-matrix`、`clinical-trends`、`clinical-suggest`、`clinical-tracking`

### 测试
- 新增 8 个测试（analysis 2 + diagnosis 4 + tracking 2），全部通过

## [0.3.2] — 2026-07-10

### 数据隔离（0.3.x 迭代三）

#### scope_filter 函数
- `khub/auth.py` 新增 `scope_filter(user, resource, alias) -> (WHERE_clause, params)`：按角色+资源返回 SQL 过滤条件
- admin/全局 token：无限制（`""`）
- patient/guardian：仅自己的数据（`id=?` / `patient_id=?`）
- doctor/nurse/intern：限制到有记录的患者
- receptionist：全部患者（仅基本）

#### 隔离应用
- `khub/clinical/patients.py` `list_patients(store, user=None)` — scope 拼接到 WHERE
- `khub/clinical/records.py` `list_records(store, patient_id=None, user=None)` — 多条件 AND
- `khub/clinical/consultations.py` `list_consultations(store, patient_id=None, user=None)` — 同上
- `khub/ops/store.py` `list_appointments(store, ..., user=None)` — 新增 doctor/status 过滤 + scope
- `khub/api.py` — `GET /clinical/patients` + `GET /ops/appointments` 传入 `current_user`

### 测试
- 新增 8 个 scope_filter 测试：admin/patient/doctor/guardian/none/alias/未登录
- 全部 24 通过

## [0.3.1] — 2026-07-10

### RBAC 权限框架（0.3.x 迭代二）

#### 权限模型
- `PERMISSIONS` 字典定义 8 角色（admin/doctor/nurse/intern/receptionist/patient/guardian/security）对 12 类资源的读写权限
- `check_permission(user, resource, action)` —— 端点级权限检查函数
- `admin` 角色及 `KHUB_API_TOKEN`（global token）跳过所有检查

#### API 端点级权限
- `dispatch()` 入口自动将路径映射为资源名、HTTP method 映射为 action，逐请求检查权限
- 公开端点（`/auth/login`、`/web/`、`/health`）免检
- 权限不足返回 403

#### 用户管理
- REST：`GET /api/users`（用户列表）、`POST /api/users`（创建用户）、`PUT /api/users/{id}/role`（修改角色）
- CLI：`khub user-list`、`user-create`、`user-role`
- Web UI：系统管理面板（仅 admin 可见），用户列表/创建/角色修改

### 测试
- 新增 9 个权限测试：5 角色权限断言 + 空用户 + list_users + update_role
- 全部 16 通过

## [0.3.0] — 2026-07-10

### 多用户鉴权基础（0.3.x 迭代一）

**正式跃升至 0.3.x 系列——从单用户工具升级为多用户平台。**

### 新增

#### 用户系统
- `users` 表（`khub/db.py`）：用户名/密码哈希(PBKDF2-SHA256)/角色/状态
- `auth_tokens` 表：token 持久化存储（有效期 7 天，可撤销）
- 首次启动自动创建 admin 用户（`KHUB_ADMIN_PASSWORD` 环境变量设定密码，缺省生成随机密码）

#### 登录与鉴权
- `khub/auth.py` 鉴权模块：`hash_password`/`verify_password`/`authenticate`/`issue_token`/`validate_token`/`revoke_token`
- API 鉴权重构：`dispatch()` 入口从单 `KHUB_API_TOKEN` 改为调用 `get_current_user()`，支持 Bearer JWT + 向后兼容 `KHUB_API_TOKEN`
- `POST /auth/login` / `POST /auth/logout` / `GET /auth/me` 端点

#### Web 登录页
- 独立 `khub/web/login.html`：用户名/密码表单，POST 登录后存 token 至 localStorage
- `script.js`：`getToken()`/`checkLogin()`/`logout()`；所有 fetch 自动注入 `Authorization: Bearer` header
- 首页无 token 时自动重定向到登录页

#### CLI 登录
- `khub login <username>`：交互输入密码，保存 token 至 `~/.khub/credentials`（权限 600）
- `khub logout`：清除凭证文件
- `khub whoami`：显示当前用户

### 向后兼容
- `KHUB_API_TOKEN` 仍可用，作为超级管理员 token 通行所有请求
- 首次 admin 密码不设环境变量则自动生成并打印到控制台
- 所有存量 `KHUB_API_TOKEN` 用户无需修改配置即可继续使用

### 测试
- 新增 `tests/test_auth.py`（8 个测试）：密码哈希、用户创建、登录成功/失败、token 签发/验证/撤销
- 修复 3 处预存 bug（api.py `/search`、`/clinical/extract`、`/api/wechat/followers`）

## [0.2.11] — 2026-07-10

### 桌面体验增强
- **修复端口双启动 bug**：`cli.py --electron` 模式不再自启后端，由 Electron `main.js` 统一管理（通过 `KHUB_PORT` 环境变量传递端口）
- **托盘图标**：从 `nativeImage.createEmpty()` 空白占位替换为实际 PNG 图标
- **Ollama 本地模型检测**：Electron 启动时自动探测本地 Ollama（`127.0.0.1:11434`），成功则注入 `KHUB_LLM_URL` 环境变量
- **系统菜单**：新增 File（打开本地库/退出）和 Help（关于）菜单

### 微信公众号发布系统
- 3 张业务表：`wechat_articles`（文章素材）、`wechat_schedules`（发布排期）、`wechat_followers`（粉丝），均接 WAL 复制
- `khub/wechat/auth.py`：Token 管理器（appid+secret → access_token，缓存 + 过期前 120 秒自动刷新）
- `khub/wechat/api.py`：微信平台 API 封装（素材上传 `upload_news`、群发 `send_mass`、粉丝拉取 `get_followers`/`batchget_user_info`）
- `khub/wechat/store.py`：文章/排期/粉丝 CRUD（`add_article`/`list_articles`/`add_schedule`/`scan_due_schedules`/`sync_followers`）
- REST 端点：`POST/GET /api/wechat/articles`、`POST /api/wechat/schedules`、`GET /api/wechat/followers`
- CLI：`wechat-article-add/list`、`wechat-schedule`、`wechat-publish --due`、`wechat-sync-followers`

### 测试
- 新增 10 个测试（微信 7 + 桌面 3），全部通过

## [0.2.10] — 2026-07-10

### 课程运营管理系统

新增完整业务模块，遵循「业务模块只加表」与现有模块模式（ops 轻量单文件模板）：

#### 课程（courses）
- 4 张业务表：`courses`（课程）、`lessons`（课时）、`enrollments`（学员报名）、`grades`（成绩/考核），均接 WAL 复制
- 课程 CRUD：名称/教师/时间/容量/价格/状态
- 课时管理：按课程组织，含日期/时间/地点/讲义
- 学员报名：姓名/电话，容量检查（超限报错）
- 成绩录入：按学员+课时记录分数/评语

#### 接口
- REST API：9 个端点（`/api/courses` 系列，含课程详情/课时/报名/成绩）
- CLI：7 个子命令（`course-create/list/info`、`lesson-add/list`、`enroll`、`grade`）
- Web UI：导航栏「课程」面板，课程列表/详情/创建/报名/添加课时（`showView('course')`）

### 测试
- 新增 `tests/test_course.py`（9 个测试）：课程 CRUD、课时、报名/容量满、成绩录入、联表计数

## [0.2.9] — 2026-07-10

### RAG 检索增强生成

- **上下文截断完善**：`_assemble_context` 从单层等分改为两层算法（先等分，超长时逐步移除低分来源，每源至少 100 字符底线）
- **来源过滤**：`RAGEngine.ask/ask_stream/_fetch_sources` 统一支持 `source_filter`（字符串/列表），`GET /ask` 返回 sources 增强为含 `title`、`doc_id`、`score`、`source` 字段
- **问诊助手接入 RAG**：`khub/clinical/consult_chat.py` 的 `chat()` 自动通过 `RAGEngine` 获取知识片段拼入 prompt，RAG 失败不打断问诊

### 知识库增强

#### 标签系统（`khub/tags.py`）
- 新增 `doc_tags` 表（接 WAL），支持 `add_tag`/`remove_tag`/`list_tags`/`get_doc_tags`
- REST 端点：`POST/DELETE /documents/{id}/tags`、`GET /tags`、`GET /documents/{id}/tags`
- Web UI：文档详情标签圆角徽章（可点击 × 删除）、输入框回车添加、搜索标签下拉筛选（`&tag=` 参数）

#### 收藏/书签（`khub/favorites.py`）
- 新增 `favorites` 表（接 WAL），`toggle_favorite`/`list_favorites`/`is_favorite`
- REST 端点：`POST /documents/{id}/favorite`、`GET /favorites`
- Web UI：文档详情/搜索结果星标按钮（☆/★）、收藏列表页

#### Markdown 后端渲染
- `GET /documents/{id}` 中 format==`markdown` 时自动调用 `markdown.markdown` 渲染为 HTML
- `markdown` 可选依赖（`[md]` 组，`markdown>=3.4`），缺失时原样返回

### 测试
- 新增 8 个测试（RAG 截断/source_filter 4 个 + 标签 4 个 + 收藏 4 个）
- 全量测试通过

## [0.2.8] — 2026-07-10

### 线 A：Web UI + 运营子系统增强

#### Web UI 体验升级
- 修复 PUT 编辑 format 降级 bug（编辑 HTML 文档不再降级为 plain）
- 运营 Web UI：导航栏「运营」入口、排班表、预约列表（含签到/取消按钮）、骨架屏加载
- 搜索体验增强：`AbortController` 消除快速搜索竞争、键盘快捷键（`/` 聚焦、`Escape` 清空）
- 移动端打磨：运营表格响应式、AI 面板全屏适配

#### 运营子系统增强
- 预约状态机补全：`cancel_appointment`(`cancelled`)、`mark_no_show`(`no_show`)、`complete_visit`(`completed`)、`reschedule_appointment`(原单 cancelled + 新单 booked)
- 排班冲突检测：`add_schedule` 检查同一 `(date, doctor, slot)` 占用
- CLI 补齐：`ops-list`、`ops-cancel`、`ops-reschedule`、`ops-schedule`
- 运营统计扩展：`/stats` 返回 `appointments_by_status`、`schedules_coverage`

### 线 B：运维可观测性

- **结构化日志**：`khub/log.py` 重写——默认 JSON/NDJSON 格式、`TimedRotatingFileHandler` 按天轮转、`KHUB_LOG_FORMAT=text` 回退纯文本、`KHUB_LOG_ROTATION` 控制保留天数
- **HTTP 访问日志恢复**：`Handler.log_message` 改为写入 `khub.api` 日志器（此前被设为 `pass` 静默丢弃）
- **`/health` 深度增强**：四维度检查（DB可达/FTS可查/磁盘可用空间>100MB/WAL堆积<1000），单项失败返回 `degraded`
- **`/stats` 扩展**：新增 `db_file_size_mb`、`wal_pending_count`、`table_rows.*`（4 张业务表）
- **`/metrics` Prometheus 端点**：受 `KHUB_METRICS_ENABLED=1` 控制，输出请求计数/文档数/DB 大小/WAL 堆积
- 配置文档补充：`KHUB_LOG_FORMAT`、`KHUB_LOG_ROTATION`、`KHUB_METRICS_ENABLED`

### 测试
- 新增 11 个测试：ops 状态机(4) + stats 扩展(1) + health(1) + metrics(2) + health 适配(1)
- 全量测试通过

## [0.2.7] — 2026-07-10

### 新增

#### 孪生摘要增强（`khub/clinical/twin_v2.py`）
- `build_summary_incremental(store, pid)`：基于 `twin_versions` 游标的增量摘要聚合，仅聚合新增条目，无增量时跳过返回既有摘要
- `get_timeline(store, pid)`：按日期排序的患者就诊/问诊时间线
- `get_syndrome_evolution(store, pid)`：历次辨证/舌脉演变序列
- `GET /twin/<pid>` 端点返回摘要 + 时间线 + 辨证脉络；`khub twin refresh [--full]` CLI 子命令

#### 问诊助手（`khub/clinical/consult_chat.py`）
- `start_session(store, pid)` / `chat(store, session_id, user_msg)`：会话管理 + 多轮 prompt 拼接（历史 + 孪生摘要 + 检索片段），历史按 6000 字截断防超上下文
- `POST /clinical/consult/chat` 端点（支持新会话/续会话）；`khub consult-chat <pid> [--message]` CLI（交互/单次模式）
- 消息内容经 `crypto.enc` 加密落盘，读取经 `audit.record` 留痕

#### 随访与复诊管理（`khub/clinical/followup.py`）
- `add_plan(store, pid, due_date, reason)` / `scan_due(store, as_of)` / `record_adherence(store, plan_id, attended)`
- `POST /clinical/followup`（建计划）、`GET /clinical/followup/scan`（扫描到期）；CLI：`followup-add` / `followup-scan` / `followup-adherence`
- MVP 仅库内状态标记（`active→due→done`），`auto_book` 可选调用 `ops.book_appointment`

#### 病历/问诊结构化抽取（`khub/clinical/extract.py`）
- `extract_structured(store, text)`：先走 LLM 返回 JSON（辨证/证型/方剂/治法），失败/LLM 回退时退词典/正则（`_SYNDROME_KEYWORDS` + 方剂/治法模式）
- `apply_struct(store, source, source_id, structured)`：写 `record_struct` 表；原始 `records`/`consultations` 列保持自由文本
- `POST /clinical/extract` 端点；CLI：`record-extract <id>` / `consult-extract <id>`

### 横切约定
- 新增 8 张临床业务表（`twin_versions` / `consult_sessions` / `consult_messages` / `followup_plans` / `followup_reminders` / `followup_adherence` / `record_struct` / `syndrome_vocab`），全部 `install_triggers` 接 WAL
- PII 字段经 `crypto.enc` 加密落盘 + `audit.record` 审计留痕；所有 LLM 路径走 `get_provider()`，`NoOpProvider` 返回占位模板

### 测试
- 新增测试文件：`tests/test_twin_v2.py` / `test_consult_chat.py` / `test_followup.py` / `test_extract.py`（共 19 个新测试）
- 全量 smoke：187 passed（+19 新用例）
- 发布验证：`pytest -q` 全部通过

### 文档
- `docs/superpowers/specs/2026-07-10-khub-0.2.7-design.md`：0.2.7 设计说明（四线并行，方案 A）
- `docs/superpowers/plans/2026-07-10-khub-0.2.7-plan.md`：0.2.7 实现计划（6 任务组）

## [0.2.6] — 2026-07-10

### 新增

#### 文档版本 Diff 对比
- `khub/diff.py`：零依赖 LCS 行级 diff（`diff_lines` / `diff_to_html`），统一 `\r\n` 换行避免误判
- `GET /documents/{id}/diff?v1=X&v2=Y`：返回 JSON + 并排 HTML；行数上限 5000 行防大文档 OOM（超限 413），负值版本拒绝
- 前端「比较」按钮（`version_count>=2` 时显示），加载相邻版本并排对比视图

#### 老问诊系统数据导入器
- `khub/importer.py`：`LegacyImporter` 支持 Excel(.xlsx) / HTML 表格，自动识别中文字段名映射至 患者/病历/问诊 内部字段
- `khub import-legacy --file <path> --sheet <名|索引> --dry-run`：CLI 子命令；`--dry-run` 仅解析预览不写入

### 安全加固
- EPUB 元数据/封面解析改用 `defusedxml`（`khub/extractors/epub.py`），消除恶意 OPF 触发的 XML 解析漏洞（XXE / 实体扩展）
- `defusedxml>=0.7` 提升为强制依赖（pyproject `dependencies`）

### 修复
- `khub/crypto.py`：修复 PII 密钥生成变量遮蔽 bug——`generate_key()` 结果正确写盘并返回（原实现写盘与返回非同一变量，密钥不一致）
- `khub/db.py`：`prune_wal` 环境变量解析由 `v not in (None, "")` 改为 `if v`，修正空串被误判为有效的边界
- 文档 Diff R1/R2 review 修复：行数上限 5000、负值版本拒绝、统一 `\r\n` 换行
- `replication.py`：类型注解补全（`fetch_snapshot -> dict | None`、`best_snapshot_for` 新增抽象方法、`replay_from` / `install_triggers` 参数 `int | None` 化）
- `api.py`：`/stats` 的 `sources` 字典类型注解；`/documents/{id}/diff` 端点新增
- `importer` 同步：复诊默认创建病历 + 过滤页脚行；SSL 证书生成测试修复
- 全仓 `except Exception` 静默分支补 `# nosec B110/B112` 精准标注，配合 bandit 审查

### 工具链 / 质量
- 新增 `khub/.bandit` 权威配置（默认 `bandit -r khub` 自动发现）；skips 仅保留 `B101/B404/B603/B607/B608/B310`（经验证的安全不变量），其余 Low（B105/B110/B112）以源码 `# nosec` 标注，保留 bandit 全局检测能力
- pyproject 注册 pytest marker（`smoke` / `full` / `slow` / `net`）；新增 `[tool.mypy]` 配置并修复 63 个 mypy 错误；`dev` 组加 `bandit/mypy`，新增 `importer` 可选组（`openpyxl`）

### 测试
- 新增 `tests/test_importer.py`（146 行，`LegacyImporter` Excel/HTML 导入）
- 测试套件扩展至 **283 passed**（CODEBUDDY.md 标注），较 0.2.5（+16）

### 文档
- 新增 `CODEBUDDY.md`、`docs/adr/`、`docs/risks/register.md`、`docs/reviews/*`（架构/网络安全/运维/产品/软件工程 多角色两轮评审）、`docs/review_diff_r1/r2.md`、`docs/superpowers/plans`

### CI / 发布工程
- `.github/workflows/ci.yml`：push/PR 触发 `bandit -r khub` 安全扫描 + `pytest -m "not slow and not net"` 核心用例
- CI 安装改为 `[dev,pdf,ann,crypto,importer]`，修复 openpyxl 缺失导致 `TestExcelImport` 失败
- 升级 `actions/checkout` v4→v7、`actions/setup-python` v5→v6，消除 Node.js 20 弃用警告

## [0.2.5] — 2026-07-10

### 新增

#### 数据看板与统计图表
- `/stats` 端点扩展：近 7 天入库趋势（weekly）、版本/向量数、冲突数
- 前端 SVG 条形图展示来源分布
- 前端 SVG 折线图展示每日入库趋势
- 最近文档列表（可点击加载详情）

#### 数据源同步状态面板
- `GET /sync-status` — 查询各数据源同步时间与状态
- 前端表格展示，绿/橙/灰颜色指示器

#### 限流器持久化（v0.4 AMEND C3）
- `khub/ratelimit.py` — SQLite 持久化令牌桶，重启状态不丢失
- `KHUB_RATE_LIMIT_RATE` / `KHUB_RATE_LIMIT_BURST` 环境变量配置
- API 层集成，超限返回 429

#### Docker 部署增强
- Dockerfile: python 3.12、非 root 用户、入口脚本
- docker-compose: 内部网络隔离、WAL 保留窗口配置
- nginx: CSP 头、限流（30r/m burst=20）
- `docs/deployment.md` 全面重写

### 安全加固
- CSP / X-Content-Type-Options / X-Frame-Options / HSTS / Referrer-Policy / Permissions-Policy
- 请求体上限 10MB（含负值 Content-Length 防护）
- Transfer-Encoding: chunked 拒绝
- 静态文件 MIME 类型正确映射
- 非 root 容器运行
- `cli.py` 回放状态打印的向量表名拼接前补 `re.fullmatch(r"\w+", model)` 校验，与 `retrieval._vec_table` 约定对齐，消除理论 SQL 标识符注入风险

### 修复
- `docs/test_security.py` — 9 项安全测试（CSP/限流/MIME/chunked）
- `docs/test_docker_build.py` + `test_docker_compose.py` — Docker 构建测试
- pyproject.toml 补全 crypto/s3 可选依赖组
- RAG 空上下文不再调用 LLM
- Dockerfile `&& \` 残留语法错误修复
- bandit 默认扫描修复：新增 `khub/.bandit`（此前 `bandit -r khub` 不读 pyproject 的 skips，形同虚设）；23 条 Low（B105/B110/B112）以源码行 `# nosec` 精准标注，30 条 Medium（B310/B608）经审查符合「标识符白名单 + 值参数化」安全不变量后由 skips 清零

### 测试
- 267 passed / 4 skipped（+43 个新增测试，测试覆盖率显著提升）

### CI / 发布工程
- 新增 `.github/workflows/ci.yml`：push/PR 触发 `bandit -r khub` 安全扫描与 `pytest -m "not slow and not net"` 核心用例（smoke）；默认 `bandit` 命令与核心测试在 CI 中可验证
- 修复 CI 安装漏装 `importer` 可选组（openpyxl），导致 `TestExcelImport` 6 用例 `ModuleNotFoundError`；安装改为 `[dev,pdf,ann,crypto,importer]`
- 升级 `actions/checkout` v4→v7、`actions/setup-python` v5→v6，消除 Node.js 20 弃用注解（GitHub Actions runner 已 Node 24）

## [0.2.4] — 2026-07-09

### HA/DR：端到端双节点 failover 演练

- `khub/ha/drill.py`：新增 `run_drill` / `format_drill`，将真实主库 A、备库 B 与共享 WAL 副本串成完整双机热备生命周期：稳态同步 → 对端双域死 → 备机自动提升（epoch+1）→ 脑裂双写 → epoch fencing 进 safe_mode → reconcile 分歧 → 重建恢复。支持 `--manual`（仅检测不提升）与 `--docs`（稳态写入数）。
- `khub/ha/controller.py`：新增 `FailoverController.cycle()` 公开入口，供演练与外部循环驱动。
- `khub/cli.py`：新增 `ha drill` 子命令，临时库生命周期由 `shutil.rmtree` 兜底清理。
- `tests/test_ha_drill.py`：端到端演练断言覆盖 6 阶段 + 手动模式。
- 文档与配置：`docs/config.md` 补充 `KHUB_WAL_KEEP` / `KHUB_WAL_KEEP_DAYS`；`README.md` 补充 `dr prune` CLI 条目；`pyproject.toml` / `__init__.py` 版本 bump 至 0.2.4。

## [0.2.3] — 2026-07-09

### HA/DR：I5 — WAL 归档窗口（防磁盘膨胀）

- `Store.prune_wal(keep=None, keep_days=None)`：仅删已推送（`applied=1`）的旧 WAL，**绝不删 pending（未推送）**；按 `KHUB_WAL_KEEP`（保留最近 N 条）或 `KHUB_WAL_KEEP_DAYS`（保留最近 D 天）归档窗口收敛；两者皆空则 no-op（默认保留全量，PITR 无界）。
- `ReplicationManager.push_pending` 在推送成功后自动调用 `prune_wal()`，使 WAL 在每次成功推送后按窗口收敛（清理必须在 push 之后，否则会丢 PITR/副本所需数据）。
- 新增 `khub dr prune`（`--keep` / `--keep-days` 覆盖环境变量）手动/按需归档；打印清理条数与剩余条数。
- 本地清理不影响 PITR：回放走副本 `replica.fetch_changes()` 而非本地 `replication_log`；清理后 SQLite 复用空闲页，文件大小随窗口收敛而非无限增长。
- 测试：4 条 prune 单测 + 1 条「push 后归档 + PITR 仍可从副本回放」集成验证。

## [0.2.2] — 2026-07-09

### HA/DR：WAL 解耦落地（M2/A5）与收尾清理

#### WAL 解耦（设计 §6 / M2 / A5）
- 业务写只写轻量 `wal_staging`（与主事务同提交、几乎不失败），由 `WalFlusher` 在独立连接上 best-effort 落 `replication_log` + `lsn_seq`；WAL 写失败仅 `logging.warning`，**绝不回滚业务写**，满足「WAL 写失败不阻塞主事务」。
- 文件库：`WalFlusher` 启 daemon 线程按 0.2s 轮询刷盘（独立连接，不阻塞业务连接）；`:memory:` 不启后台线程，靠显式 `store.flush_wal()` 驱动（测试/关闭前）。
- 触发器（Primary）与 `manual_record_change`（补记）统一走 `wal_staging` → `replication_log` 解耦路径，WAL 变最终一致，缺口由快照/PITR 兜底（明确取舍）。

#### 修复
- 修复 `replication.py` 漏 `import sqlite3`，导致文件库独立刷盘连接建立失败（WAL 不落盘）。
- `make_snapshot_db` 的 `PRAGMA wal_checkpoint(PASSIVE)` 改为 best-effort：并发 flusher 写事务持锁（`SQLITE_LOCKED`）不再阻断快照。
- 8 个测试在业务写后读 `replication_log` 未 `flush_wal()`，补显式刷盘以确定性断言。

#### 清理
- 删除 dead `Store._replicate`（触发器自动记账已替代，无残留双记）。

#### 测试
- 全测试 **184 passed / 2 skipped**（`tests/`，含 `test_ha.py` 31 passed）。

## [0.2.1] — 2026-07-09

### 修复（M1 代码评审）

#### 核心存储 / 并发
- `Store` 连接改为 `check_same_thread=False` + `isolation_level=None`，并用 `threading.RLock` 串行化所有写操作，修复 REST 服务（`ThreadingHTTPServer`）跨线程共享连接导致的 `ProgrammingError` 与并发写入损坏风险。
- 修复 `sqlite3.connect` 误用未展开的 `path`（曾导致 `~/x.db` 落到工作目录而非家目录的数据丢失隐患）。
- 修复 `transaction()` 与隐式事务冲突（显式 `BEGIN` + `isolation_level=None`，并修正 `replay_from` 缺失的 `BEGIN`，恢复回放中途异常整体 rollback）。
- 删除 `Store.search` 被新版分页 `search` 覆盖而产生的死代码，并保留 `search_old` 作为兼容薄封装（委托给新版 `search`）。
- 快照（`make_snapshot_db`）排除复制记账表 `replication_log` / `lsn_seq` / `ha_state`，避免恢复库复用主库 lsn 序列器与角色/锁状态，升主后产生重复/错乱 lsn。

#### 安全
- REST 鉴权从「仅写操作」扩展为「设置 `KHUB_API_TOKEN` 后所有端点（含读）均需 Bearer 令牌」，避免本地任意进程裸读病历/问诊 PII。
- ANN 向量表名由 `model` 经白名单（`[A-Za-z0-9_]`）校验，防建/删表 SQL 注入。
- 定时调度命令由 `shell=True` 改为 `shell=False`（`shlex` 拆词），防命令注入。
- PII Fernet 密钥在加载时即校验格式，非法密钥给出明确错误而非在写入时崩溃。
- 检索 `/search`、`/semantic` 的 `page`/`k` 参数非法时安全回退默认，避免 500。

#### 子系统正确性
- 考题生成：提示并要求模型以 JSON/标签格式返回，解析出题干/选项/答案/解析；无模型时退回占位题干。
- 考题判分：用户答错且配置 LLM 时真正调用 provider 复核，而非返回死逻辑。
- `cosine` 相似度对不等长向量显式校验，避免 `zip` 静默截断导致错误结果。
- `watch` 文件读取改用 `with open`，修复文件句柄泄露。

### 文档同步
- `pyproject.toml` 版本 0.1.0 → 0.2.1，并补 `khub.ha` 子包（此前漏装）；`khub/__init__.py` 版本同步。
- `systemd/khub.service`：将模板占位 `{{KHUB_BIN}}` 替换为实际可执行文件路径并说明渲染方式。
- `README.md`：CLI/REST 补全 `query`、`dr *`、`ha *`、`feishu-sync`、`ima-*` 等命令与 `/health`、`/stats`、`/documents/{cid}`、`/web/*` 端点；测试数 31 → 182；安全章节补充鉴权/注入防护。
- `docs/config.md`：新增 `KHUB_API_TOKEN`/`KHUB_PII_KEY_FILE`/`KHUB_EMBED_MODEL`/`IMA_*` 等环境变量；澄清核心**不读取**全局 `config.yaml`（仅调度器用 `tasks.yaml`）。
- `docs/api.md`：补充 `GET /documents/{cid}` 与 `/web/*` 端点，版本号同步。
- `docs/architecture.md`：模块表补齐 `sync_engine`/`crypto`/`audit`/`replication`/`ha`/`scheduler`/`watch`/`normalizer`/数据源适配器等；扩展点标记 ANN/加密/真实模型为「已实现」并补充并发安全说明。

### 测试
- 182 个测试全部通过（`tests/` 目录，2 个跳过），端到端覆盖全链路。

---

## [0.2.0] — 2026-07-07

### 新增

#### P0 — KZOCR 入库收尾
- `/documents` REST 端点支持 OCR 文档直接入库，配套 `doc-add` CLI 子命令
- 短查询自动降级为 SQL `LIKE` 回退，确保无向量索引时仍可检索
- 端到端验证链路：OCR 识别 → 入库 → 查询

#### P1 — 入库向量化与 Web UI
- 入库存档文件自动完成文本提取与向量化（FTS5 + 向量双索引）
- 轻量 Web UI：`GET /` 控制台、`GET /documents` 文档浏览、`GET /conflicts` 冲突管理
- `khub watch` 命令监听目录，新文件自动入库

#### P2 — 向量检索升级
- `sqlite-vec` ANN 近似最近邻检索，替代暴力全量比对
- `RemoteEmbedder` 支持挂载真实嵌入模型（通过 HTTP API）
- `GET /semantic` 语义检索端点，WebUI 新增语义检索按钮

#### P3 — 真实 LLM 驱动
- `RemoteLLMProvider` 兼容 OpenAI `/v1/chat/completions` 接口
- `get_provider()` 默认返回远程真实模型（环境变量配置）
- 孪生摘要生成、考题生成默认由真实 LLM 驱动，带本地模板兜底

#### P4 — 安全与灾备
- PII 敏感字段 Fernet 对称加密落盘（患者/病历/问诊记录）
- 访问审计日志：记录每次 PII 读取操作的 `actor + action + timestamp`
- 灾备/热备规划接口：`ReplicationManager` + `WALLog` 变更日志 + `LocalFileReplica` 本地文件副本推送

#### P5 — 真实数据源接入
- Quip 归档文档导入（`khub quip ingest`）
- Obsidian Vault 导入（`khub obsidian import`）
- 定时调度器：YAML 任务定义、后台循环触发、异常隔离
- CLI 子命令：`quip`、`obsidian`、`scheduler`

#### M5 桌面 GUI
- Electron 桌面套壳：`desktop/main.js` + `package.json` + `run.sh`
- `khub desktop` CLI 命令支持浏览器模式和 Electron 原生窗口模式

### 测试
- 182 个测试全部通过（`tests/` 目录）
- 端到端集成测试覆盖全链路：患者→病历→问诊→孪生→电子书→KZOCR→检索→PII 加密→审计
- 整体行覆盖率 73%，核心模块 >85%

---

## [0.1.0] — 2026-07-07

### 新增

#### 设计与规划
- khub knowledge-hub 设计方案：架构、模块划分、数据流
- UI 分层设计：CLI / Web / GUI
- M1 实现计划（khub + writing-plans 双视角）
- 技术路线图扩展：EMR / 问诊模块
- 角色交互模型：医生 / 护士 / 规培生 / 前台 / 保安 / 患者 / 家属

#### 核心存储（M1）
- SQLite + FTS5 版本化存储引擎：文档多版本管理、全文检索
- `khub` 包结构：模块化分层（db / models / storage / api / cli）
- 数据库初始化 schema 与迁移
- 文档存储自动化测试

#### 电子书入库（M2）
- 受管库系统：注册、元数据管理、列表查询
- 文件存储层：归档复制、哈希去重、源文件移动
- EPUB 正文抽取与元数据解析
- 电子书封面提取（EPUB 完整支持，PDF best-effort）
- 未知格式优雅拒绝

#### 检索（M3）
- 离线 `LocalEmbedder`：确定性输出、L2 归一化向量
- 暴力向量检索：存储向量并返回最近邻
- 索引时读取电子书版本内容

#### 考试子系统（M5）
- 题目 CRUD（创建、查询、更新、删除）
- LLM 题目生成桩（`LLMProvider` 抽象接口）
- 自动判分（精确匹配）

#### 孪生子系统（M6）
- 患者管理（CRUD）
- 病历记录
- 问诊记录
- 孪生摘要生成与持久化

#### 门诊运营（M7）
- 排班管理
- 预约管理
- 就诊记录
- 运营流程端到端 CRUD

#### API 与 CLI
- REST API 挂载：注册 / 入库 / 检索 / 考试 / 孪生 / 运营
- CLI 命令封装：`khub` 命令行工具
- 健康检查端点

#### 基础架构
- 项目 README、架构文档、测试策略
- 打包脚本与构建系统
- LLMProvider 抽象：`NoopProvider` / `FakeProvider` / 注册机制
- 安全默认值

### 变更
- 初始版本，无前置变更

### 修复
- 初始版本，无前置修复
