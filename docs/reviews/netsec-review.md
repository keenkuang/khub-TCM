# khub M1 — 网络安全审查报告

- **日期：** 2026-07-09
- **范围：** M1 实现计划 + 设计规格（SQLite 存储 / OCR 适配器 / Sync 引擎 / CLI）
- **方法：** 静态代码审查（基于规格与实现计划，代码尚未完全落地）

---

## 1. 凭据管理（Credential Management）

- **Finding：** 凭据仅从环境变量读取（`os.environ.get`），不做加密存储或防护。
- **Severity：** medium
- **Details：** `config.py` 的 `secret()` 函数直接调用 `os.environ.get()`。环境变量在 Linux 上可能通过 `/proc/<PID>/environ`、core dump、子进程继承等方式泄露。对于本地 CLI 工具，M1 阶段此方案可接受，但需注意：
  - 无 `.env` 文件保护机制（如文件权限 600）。
  - 无运行中凭据内存清零。
- **Recommendation：** M1 至少做到：
  - 在 README 中明确告知用户通过 `export KHUB_TOKEN=xxx` 设置，并建议 shell 历史记录清理。
  - M1 代码落地时，若引入 `.env` 文件读取，务必将文件权限设为 `600`。
  - 记录到文档：CLI 进程运行时不要开启 core dump（`ulimit -c 0`）。
  - 长远规划（M2+）：考虑 `keyring` / `python-keyring` 集成（系统密钥链，如 macOS Keychain / Linux Secret Service / GNOME Keyring）。

---

## 2. SQL 注入（SQL Injection）

- **Finding：** SQL 层全部使用参数化查询（`?` 占位符），无字符串拼接。**不存在** SQL 注入风险。
- **Severity：** info（无风险）
- **Details：** 审查了 `db.py` 中所有 `execute()` 调用：
  - `store_document()` — 全部 `?` 参数化。
  - `search()` — `MATCH ?` 参数化（FTS5 语法由引擎处理，不产生 SQL 注入）。
  - `get_versions()`、`get_sync_state()`、`set_sync_state()`、`mark_conflict()`、`list_conflicts()` — 全部参数化。
  - `init_schema()` 中 `executescript()` 为纯 DDL，不含用户输入。
- **Recommendation：** 无。保持当前实践。若未来引入动态查询构造（如排序字段入参），需警惕。

---

## 3. 路径穿越（Path Traversal）

- **Finding：** `OcrAdapter` 的 `book_dir` 来源于用户（CLI `--book` 参数），未做路径校验，但当前威胁有限。
- **Severity：** low
- **Details：** `ocr.py:519` OcrAdapter 接受用户提供的 `book_dir`：
  ```python
  def __init__(self, book_dir: str):
      self.book_dir = Path(book_dir)
  ```
  `pull()` 中 `glob("*.md")` 和 `attachments` 子目录遍历均基于此路径。如果用户传入 `/etc` 或 `/home` 等路径，会读取系统 `.md` 文件入库。但：
  - khub 当前是本地 CLI 工具，操作者等同于机器所有者，攻击面仅限于操作者自身误用。
  - CLI 参数由操作者直接提供，不存在远程攻击者注入路径的渠道。
  - M2 Web UI 若增加文件上传/路径选择功能，**路径穿越风险将升级为 high**。
- **Recommendation：** M1 阶段可暂不处理，但建议在代码中预留路径校验函数（记录到 TODO 或 docstring），以便 M2 Web UI 加入时一并启用。未来在 `OcrAdapter.__init__` 中增加 `os.path.abspath()` + 检查路径是否为安全目录。

---

## 4. 静态数据加密（Data at Rest）

- **Finding：** SQLite 数据库完全无加密。文档正文、版本历史、元数据均以明文存储。
- **Severity：** medium
- **Details：**
  - 库文件 `khub.db` 包含所有文档全文、版本历史、同步状态。若 OCR 系统包含患者数据/处方等敏感信息，直接泄露。
  - 默认 SQLite 不提供透明加密。数据库文件权限由 umask 决定，可能为 `644`（其他用户可读）。
  - `attachments` 表中 `path` 字段存储的是磁盘上文件的**绝对路径**（`ocr.py:533`：`path=str(f)`），进一步泄露文件系统布局。
- **Recommendation：**
  - M1 建议：在 `Store.__init__` 中创建 DB 文件后，设置文件权限 `600`（`os.chmod(path, 0o600)`）。
  - 在文档中标注"本数据库含敏感内容，建议存放于加密文件系统（如 LUKS / eCryptfs）上"。
  - M2+ 评估引入 `sqlcipher3` 做数据库级透明加密（需用户提供 passphrase，存储在环境变量中）。
  - attachments 的 path 存储考虑改为相对路径（相对于 `book_dir`）而非绝对路径。

---

## 5. 依赖供应链（Dependency Supply Chain）

- **Finding：** PyYAML 依赖使用了 `>=6.0` 下限和 `safe_load()`，已知风险已规避。
- **Severity：** low
- **Details：**
  - `pyproject.toml` 指定 `PyYAML>=6.0`，版本下限合理（<6.0 存在 CVE-2020-14343，`yaml.load()` 允许任意代码执行）。
  - `config.py` 已使用 `yaml.safe_load()` 而非 `yaml.load()`——即使恶意注入 YAML 也不会触发 arbitrary code execution。
  - 依赖未固定上限，未来 `pip install` 升级可能引入兼容性风险，但非安全问题。
- **Recommendation：**
  - 保持 `yaml.safe_load()` 的使用（已做到）。
  - 建议加入 `pip-audit` 或 `safety` 到 CI/测试流程（M1 即可集成，轻量）。
  - 锁定依赖文件时考虑使用 `pip freeze > requirements.txt` 或 `pip-compile` 以获取可重现构建。

---

## 6. 输入验证（Input Validation）

- **Finding：** 适配器拉取的内容直接入库，无消毒/逃逸处理。FTS5 搜索输入的语法特殊性可能导致意外行为。
- **Severity：** medium
- **Details：**
  - **存储侧：** `store_document()` 直接将适配器返回的 `content` 写入 `document_versions.content` 和 FTS5 索引。若 OCR 产生的内容含有特殊控制字符或 BOM，可能影响检索准确性，但无安全风险。
  - **搜索侧：** `search()` 中 `MATCH ?` 虽是参数化，但 FTS5 MATCH 语法支持特殊操作符（`*`、`"`、`NEAR`、`NOT` 等）。恶意构造的搜索词可能导致：
    - FTS5 语法错误（拒绝服务）。
    - 性能消耗（通配符查询如 `a*` + 大索引）。
    - 无数据泄露风险（FTS5 不支持读取越权数据）。
  - **内容储存量限制：** `store_document()` 无大小校验，超大数据可能导致数据库膨胀或 OOM。虽为本地工具，但 `ingest` 命令由脚本触发（OCR 系统自动入库），可能意外导入大型文件。
- **Recommendation：**
  - 在 `store_document()` 中增加内容大小检查：`if len(doc.content) > MAX_DOC_SIZE: raise ValueError(...)`（建议 10MB）。
  - 在 `search()` 中捕获 FTS5 语法异常（`sqlite3.DatabaseError`），优雅降级为 LIKE 查询或返回"查询语法错误"。
  - M1 建议增加：FTS5 搜索词长度限制（如不超过 200 字符）。

---

## 7. 访问控制（Access Control）

- **Finding：** 仅本地 CLI，无多用户场景。主要风险来自文件系统权限。
- **Severity：** low
- **Details：**
  - 设计规格明确声明 "不做多用户/权限系统（纯个人使用）"，此边界清晰。
  - 主要现实风险：SQLite DB 文件默认权限下，同机器其他进程/用户可读取。常见场景：共享开发机、CI runner、容器内其他进程。
  - CLI 本身无认证，但本地运行的设计使得无需额外认证。
- **Recommendation：**
  - `Store.__init__` 中在创建数据库文件后执行 `os.chmod(path, 0o600)` 限制权限。
  - `config.yaml` 建议也置为 `600` 权限（虽不含密钥，但含敏感路径和主机名信息）。
  - 在 M1 文档中说明"建议在个人专用机器或加密文件系统上使用"。

---

## 8. 配置中的密钥泄露（Secrets in Config）

- **Finding：** `config.yaml.example` 不包含实际密钥，凭据明确走环境变量。无密钥泄露风险。
- **Severity：** info（无风险）
- **Details：**
  - `config.yaml.example` 中所有凭据项以注释形式标注环境变量名（`# creds via env: IMA_TOKEN`），不包含值。
  - `config.py` 的 `secret()` 函数仅读取环境变量，不会写入配置文件。
  - 无需担心误提交凭据到版本控制。
- **Recommendation：** 无。当前方案正确。建议在 `.gitignore` 中显式加入 `config.yaml`（仅提交 `config.yaml.example`），以防用户误操作。

---

## 汇总与优先级

| # | Finding | Severity | 建议优先级 |
|---|---------|----------|-----------|
| 4 | 静态数据无加密 | medium | **M1 需处理**（至少设置 600 权限） |
| 1 | 凭据仅环境变量 | medium | **M1 标注风险**，M2 考虑密钥链 |
| 6 | 输入无校验 | medium | **M1 需处理**（大小限制 + FTS5 异常） |
| 3 | 路径穿越 | low | M1 可暂缓，M2 Web UI 前必须修复 |
| 5 | 依赖供应链 | low | 建议 M1 即加入 `pip-audit` |
| 7 | 访问控制 | low | M1 设置 DB 文件 600 即可 |
| 2 | SQL 注入 | info | 无需处理 |
| 8 | 配置密钥泄露 | info | 无需处理（已正确实现） |

### M1 必做项（合并即可）

1. 在 `Store.__init__` 创建 DB 文件后执行 `os.chmod(path, 0o600)`。
2. 在 `store_document()` 中校验内容大小上限。
3. 在 `search()` 中增加 FTS5 语法异常捕获与搜索词长度限制。
4. 将以上安全注意事项写入 M1 交付文档/README。

---

*审查人：security-reviewer（CodeBuddy 自动审查）*
*审查依据：khub 设计规格（2026-07-07）与 M1 实现计划（2026-07-07）*
