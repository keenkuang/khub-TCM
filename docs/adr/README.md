# Architecture Decision Records — khub

本目录记录 khub 项目的重要架构决策。每条 ADR 包含上下文、决策、替代方案、理由和影响。

---

## ADR-001: CLI 用 argparse 而非 click

- **日期**: 2026-07-09
- **状态**: 已采纳

### 上下文
M1 CLI 需要支持 `sync` / `query` / `ingest` / `ls` / `conflicts` / `version` 六个子命令。选择 CLI 框架时考虑了 argparse 和 click。

### 决策
使用 Python 标准库 `argparse`，零额外依赖。

### 替代方案
- **click**: 功能更丰富（自动帮助、类型转换、测试支持），但增加一个运行时依赖

### 理由
- 标准库内建，零安装成本
- 六个子命令的复杂度 argparse 完全胜任
- `pip install khub` 不需要额外拉取依赖

### 影响
- CLI 测试使用 `subprocess.run` 而非 click 的 CliRunner
- M2 增加子命令仍可继续使用 argparse，无需切换

---

## ADR-002: `_now()` 使用毫秒级 UTC 时间戳

- **日期**: 2026-07-09
- **状态**: 已采纳

### 上下文
`db.py` 中的 `_now()` 函数生成时间戳用于 `documents.updated_at`、`document_versions.updated_at` 等字段。原计划用 `%Y-%m-%dT%H:%M:%S` 秒级精度。

### 决策
改为 `%Y-%m-%dT%H:%M:%S.%fZ`（毫秒级 + UTC 标识），避免同一秒写入多个文档时时间戳碰撞。

### 替代方案
- 保持秒级精度 + 用自增 ID 排序（可接受但增加了理解成本）
- 使用 `time.time_ns()` 纳秒级整数（精度过剩，不利于可读性）

### 理由
- 毫秒级精度足以区分同一秒的多次写入
- ISO 8601 格式便于人工阅读和外部工具解析
- 带 `Z` 明确表示为 UTC，避免时区混淆

### 影响
- 时间戳长度从 19 字符变为 24 字符
- 现有代码中所有 `_now()` 调用点自动受益
- 兼容 ISO 8601 标准

---

## ADR-003: CanonicalDoc 用 hash 字段存储内容指纹，不增加 etag 字段

- **日期**: 2026-07-09
- **状态**: 已采纳

### 上下文
`OcrAdapter.normalize()` 需要将 `RawDoc.etag`（在 OCR 适配器中是内容 SHA256 哈希）传递到 `CanonicalDoc`，但 `CanonicalDoc` 没有 `etag` 字段，导致 TypeError。

### 决策
将 `raw.etag` 映射到 `CanonicalDoc.hash`，不增加 `etag` 字段。`CanonicalDoc` 是中枢内部模型，不应携带源特定的 etag。

### 替代方案
- **增加 etag 字段**: 让中枢模型携带源级概念，破坏架构纯洁性
- **修改 normalize 签名**: 增加 etag 参数（增加调用方负担）

### 理由
- `CanonicalDoc.hash` 用于内容去重和变更检测，语义等价
- 源级 etag 应保留在 `sync_states` 表中（已有 `etag` 列）
- 架构分层原则：中枢模型不应感知源级细节

### 影响
- `OcrAdapter.normalize()` 中 `etag=raw.etag` 改为 `hash=raw.etag`
- 在 `test_ocr_adapter.py` 中增加断言验证 `canon.hash == raw.etag`

---

## ADR-004: 密钥走环境变量，不进 config.yaml

- **日期**: 2026-07-09
- **状态**: 已采纳

### 上下文
各适配器需要 API 密钥（IMA、Quip 等）。M1 虽只有 OCR 适配器不需要密钥，但架构需为 M2 做准备。

### 决策
API 密钥/令牌通过环境变量传入，不进 `config.yaml` 文件，不进版本控制。

### 替代方案
- **config.yaml 直接存储**: 容易被误提交到 git，且与个人工具共享代码不便
- **密钥环**: `python-keyring` 集成系统密钥链（安全但增加依赖和复杂度，留 M2+）
- **本地 .env 文件**: 同样不进版本控制，但需要增加文件读取逻辑

### 理由
- 环境变量是 Unix 惯例，与 CI/CD、Docker、systemd 天然集成
- 零额外依赖
- `.gitignore` 中已排除 `.env`，可配合 `dotenv` 使用

### 影响
- `config.py` 提供 `secret()` 辅助函数封装 `os.environ.get()`
- 文档中需说明哪些环境变量需要设置
- M2+ 可考虑密钥环集成作为增强

---

## ADR-005: M1 仅实现 OCR push-in 源，Obsidian 只做 stub

- **日期**: 2026-07-09
- **状态**: 已采纳

### 上下文
设计规格中 M1 需支持 OCR 入库适配器和 Obsidian 适配器，但 Obsidian 尚未安装。

### 决策
- OCR 适配器：完整实现（pull / normalize / push 抛 NotImplementedError）
- Obsidian 适配器：接口定义 + 未配置时报错（`pull/push` 抛 RuntimeError）

### 替代方案
- **OCR + Obsidian 都完整实现**: Obsidian 未安装，无法验证
- **Obsidian 适配器推迟到 M2**: 设计规格显式要求 M1

### 理由
- OCR 适配器已通过测试验证，M1 即可端到端使用
- Obsidian stub 已定义完整接口契约，安装后非侵入补全实现
- `_ensure()` + 非配置时报错确保预期管理清晰

### 影响
- `cli.py` 中 `ingest` 命令直接可用，`sync` 为占位
- M2 补全 Obsidian 实现时，接口不变，只需补 `pull/push` 主体逻辑

---

## ADR-006: FTS5 使用 trigram tokenizer 支持中文检索

- **日期**: 2026-07-09
- **状态**: 已采纳

### 上下文
FTS5 默认的 `unicode61` tokenizer 按空白和标点分词，对中文不友好。`khub query "伤寒论"` 可能匹配不到包含"伤寒论"的文档。

### 决策
使用 trigram tokenizer（`tokenize='trigram'`）作为中文分词方案。trigram 以三个字符为切分单位，天然支持 CJK 文本检索。

### 替代方案
- **unicode61 + tokenchars**: 需要自定义 tokenizer，处理不完整
- **jieba 分词器**: 需安装第三方库且 FTS5 不支持外部分词器
- **LIKE 查询降级**: 性能差、不支持高亮片段

### 理由
- trigram 是 FTS5 内建 tokenizer，零额外依赖
- 对中文检索效果可接受（`"伤寒论"` 匹配 `"伤寒" + "寒论"` 两个 trigram）
- 在 `test_db.py` 中增加中文检索验证测试，确认效果

### 影响
- `docs_fts` 创建语句改为 `CREATE VIRTUAL TABLE docs_fts USING fts5(..., tokenize='trigram')`
- 原 `unicode61` 方案的英文/数字分词效果不变（trigram 对英文同样有效）
- 索引大小约增加 2-3 倍（对个人知识库规模可接受）

---

## ADR-007: SQLite 启用 WAL 模式 + busy_timeout

- **日期**: 2026-07-09
- **状态**: 已采纳

### 上下文
M1 虽为单用户 CLI，但 M2 需要支持多线程 Web UI 访问。默认的 delete 日志模式在多线程并发时容易出现 "database is locked" 错误。

### 决策
在 `Store.__init__()` 中启用 WAL 模式并设置 5s busy_timeout。

### 替代方案
- **保持默认 journal_mode=delete**: 单用户场景可行，但 M2 需改动
- **连接池 + 重试**: 更复杂，M1 过度设计

### 理由
- WAL 模式允许并发读/写，且读不阻塞写
- busy_timeout=5000 让 SQLite 自动重试 5s，避免应用层透传锁错误
- M1 即启用不影响任何已有功能，但为 M2 铺路

### 影响
- `Store.__init__()` 增加两行 PRAGMA 设置
- DB 文件目录会多出 `-wal` 和 `-shm` 文件（SQLite WAL 产物）

---

## ADR-008: DB 文件创建后设置权限 600

- **日期**: 2026-07-09
- **状态**: 已采纳

### 上下文
SQLite 数据库包含全部文档全文和版本历史，默认文件权限由 umask 决定，可能为 644（其他用户可读）。

### 决策
在 `Store.__init__()` 创建 DB 文件后（首次初始化时）执行 `os.chmod(path, 0o600)`。

### 替代方案
- **不处理**: 依靠用户 umask（不可靠）
- **文档说明建议**: 依赖用户自觉（执行不可靠）
- **加密数据库**: sqlcipher3 需要额外依赖和密钥管理（M2+ 评估）

### 理由
- 操作简单，一行代码解决数据泄露风险
- 不阻塞其他功能
- 对本地个人工具，600 是合理的安全基线

### 影响
- DB 文件创建后仅属主可读写
- M2+ 评估 sqlcipher3 时，600 权限可作为额外安全层

---

## ADR-009: M1 暂不引入适配器工厂，记录 TODO 给 M2

- **日期**: 2026-07-09
- **状态**: 已采纳

### 上下文
架构评审指出当前 CLI 中硬编码了 `OcrAdapter` 和 `ObsidianAdapter` 的实例化，M2 新增源时需要修改多处代码。

### 决策
M1 继续使用当前硬编码方式，在 `cli.py` 和 `adapters/__init__.py` 中记录 TODO 注释，明确"适配器工厂推迟到 M2（当适配器数量 ≥ 3 时）"。

### 替代方案
- **M1 即引入工厂**: 设计上更干净，但增加了 M1 不必要的前置工作
- **M1 即实现 config 驱动的自动发现**: 过度设计

### 理由
- M1 仅 2 个适配器（OCR 实现 + Obsidian stub），硬编码可维护
- M2 将增至 4 个适配器（+ima、Quip），届时工厂模式的价值才显现
- YAGNI：不为 M2 的扩展预支 M1 的实现成本

### 影响
- `cli.py` 中的 `if type == "ocr"` 判断在 M2 需重构为工厂调用
- 该决策计入 ADR，方便 M2 发起者了解上下文
