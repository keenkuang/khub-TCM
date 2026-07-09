# Docker 部署架构 —— 第 3 轮评审

> f176e7a 修复验证 + 全量回归检查
> 评审人: CodeBuddy Code (architect role)
> 日期: 2026-07-10

---

## 一、f176e7a 修复验证

### 1.1 docker-entrypoint.sh —— `$@` → `$*` 回归

| 项目 | 现状 |
|------|------|
| R1 建议 | `"$@"` 保留参数边界 |
| bf3e90d 实现 | 裸 `$@`（无外层双引号） |
| f176e7a 变更 | `$@` → `$*` |
| 当前代码 | `exec dumb-init su -s /bin/sh app -c "python -m khub.cli $*"` |

**验证：✅ 回归正确，R2-H1 已修复**

- R2 安全评审（R2-H1）正确识别了 `$@` 在 `su -c "..."` 内的回退性：双引号内 `$@` 拆词，`su -c` 仅取第一个词，丢失 `--host/--port` 等后续参数
- `$*` 在双引号内将所有位置参数合并为单字符串，`su -c` 接收到完整命令 `python -m khub.cli serve --host 0.0.0.0 --port 8765` ✅
- CMD 当前为 4 个简单参数（无空格），`$*` 展开无歧义

### 1.2 nginx/khub-docker.conf —— 限流收紧

| 项目 | R1 实现 → f176e7a |
|------|-------------------|
| 速率 | `20r/s` → `30r/m`（40 倍收紧） |
| Burst | `50` → `10` |
| 模式 | `nodelay`（不变） |

**验证：✅ 变更正确，但架构影响需评估（见 §三）**

- 语法正确，`limit_req_zone` 与 `limit_req` 参数一致
- 30r/m = 平均 1 请求 / 2s，对单用户交互型应用（问卷录入、RAG 查询）足够
- `/health` 端点仍未加限流 —— 但 30r/m 是全局区，`/health` 共享同一计数

---

## 二、R1+R2 全量修复状态追踪

### 已修复并验证通过

| # | 问题 | 文件 | R1→bf3e90d→f176e7a 路径 | 状态 |
|---|------|------|--------------------------|------|
| C1 | 网络隔离 | docker-compose.yml | 无网络 → `khub-net` → 保留 | ✅ |
| B1/H1 | entrypoint 参数展开 | docker-entrypoint.sh | `$*` → `$@`(断) → `$*`(回归正确) | ✅ |
| H1/M2 | nginx 限流 | nginx/khub-docker.conf | 无 → `20r/s b=50` → `30r/m b=10` | ✅ |

### 建议修复（R2 列表，均未处理）

以下为 `review_docker_role_arch_r2.md` §四"建议修复"中的 6 项，f176e7a **未触及**：

| # | 问题 | 文件 | 严重度 | 状态 |
|---|------|------|--------|------|
| R2-F1 | 预装依赖（PyYAML/pypdf/...）未锁定版本 | Dockerfile L15 | 中 | ❌ 仍开放 |
| R2-F2 | 健康检查配置重复且不一致（30s vs 10s） | Dockerfile + compose | 低 | ❌ 仍开放 |
| R2-F3 | 无日志轮转配置 | docker-compose.yml | 低 | ❌ 仍开放 |
| R2-F4 | `KHUB_PII_ENCRYPT=1` 密钥初始化需确认 | entrypoint/应用代码 | 中 | ❌ 仍开放 |
| R2-F5 | `dumb-init → su` 信号不传递（原 A3 升级） | docker-entrypoint.sh | 中 | ❌ 仍开放 |
| R2-F6 | 未配置 `read_only: true` | docker-compose.yml | 低 | ❌ 仍开放 |

### 长期未修复项（R1 已列，跨三轮）

| # | 问题 | 文件 | 严重度 | 理由 |
|---|------|------|--------|------|
| D1 | CSP `'unsafe-inline'` | nginx/khub-docker.conf | 中 | 需前端配合，架构不越界 |
| D2 | `form-action 'none'` 验证 | nginx/khub-docker.conf | 中 | 需前端验证 |
| A2 | 缺少 USER 指令注释 | Dockerfile | 低 | 非阻塞 |
| B2 | 入口脚本卷挂载的生产标注 | docker-compose.yml | 低 | 非阻塞 |
| E1/E2 | deployment.md 章节拆分/CSP 精度 | docs/deployment.md | 低 | 文档问题 |

---

## 三、R3 新增发现

### 发现 1：限流 30r/m + burst=10 对批量操作的架构影响（严重度：中）

`30r/m burst=10 nodelay` 意味着：
- **平均**：每 2 秒 1 请求
- **突发**：10 个请求可瞬时通过，第 11 个请求立即被 503 拒绝（`nodelay` 不排队）

**架构影响**：
- RAG 知识库中批量文档上传（调 Embedding API）—— 假设一次上传 30 个文件，每个文件触发 1 API 调用 → 前 10 个通过，后 20 个被拒
- 健康检查（`/health`）虽未显式限流，但共享 `khub_limit` 区，每 30 秒的健康检查请求消耗 1 个配额
- 在当前单用户场景下影响可控，但若多用户并发或后续添加了后台批量处理任务会立刻触达瓶颈

**建议**：
- 保持 30r/m 速率上限，但将 burst 从 10 提高到 `20-30`，给批量操作留出突发窗口
- 或新增独立限流区 `khub_health`（`30r/m`）用于 `/health`，主限流区专心保护业务 API
- 在 `deployment.md` 中记录此限流策略及其对批量操作的约束

### 发现 2：`KHUB_PII_KEY_FILE` 注释路径与卷挂载路径不一致（严重度：低）

`docker-compose.yml:29`：
```yaml
# - KHUB_PII_KEY_FILE=/root/.khub/pii.key  # 方式2：从文件加载（推荐）
```

但容器运行时用户为 `app`（非 root），且卷挂载注释（L18）使用 `/home/app/.khub/pii.key`：
```yaml
# - ./pii.key:/home/app/.khub/pii.key:ro
```

若未来取消注释使用 `KHUB_PII_KEY_FILE`，应用将尝试读取 `/root/.khub/pii.key`，实际文件被挂载到了 `/home/app/.khub/pii.key`，导致密钥加载失败。

**建议**：将注释中的路径对齐为 `/home/app/.khub/pii.key`。

### 发现 3：`khub-net: internal: false` 的注释存在误导（严重度：低）

`docker-compose.yml:71`：
```yaml
internal: false  # nginx 暴露端口，khub 服务不对外
```

`internal: false` 控制的是容器能否**出站访问外网**（internet 连通性），与端口暴露/对外可见无关。`khub 服务不对外` 是由 **无 `ports:` 定义** 实现的，不是 `internal: false` 的效果。

实际需要 `internal: false` 的原因是：khub 容器需要出站连接 SshReplica（远程灾备）和真实模型 API（Embedding/LLM）。

**建议**：将注释修正为：
```yaml
internal: false  # khub 需出站连接（SSH 灾备、真实模型 API）
```

### 发现 4：Dockerfile 使用 `pip install -e .` 而非标准 `pip install .`（严重度：低）

Dockerfile L19：`RUN pip install --no-cache-dir -e .`

`-e`（editable mode）在容器镜像中无实际用途 —— 容器内的源码不会在运行期被编辑修改。`pip install -e .` 会创建额外的 `.egg-link` 或 `.pth` 文件，使文件系统略复杂。

**建议**：改为 `pip install --no-cache-dir .`，语义更清晰，镜像层级更简洁。

### 发现 5：SSL 私钥提交在 git 仓库中（严重度：低）

`ssl/khub.key` 存在于工作树中。虽然 `.dockerignore` 排除了 `ssl/`，但 git 未在 `.gitignore` 中排除 `ssl/*.key`，私钥依然被版本控制。

**检查确认**：
```
$ git ls-files ssl/
khub.crt  khub.key
```

**建议**：将 `ssl/*.key` 加入 `.gitignore`（若为自签名开发证书）或明确在文档中标注"生产环境必须替换为正式证书，当前密钥仅用于开发"。

---

## 四、安全边界复核

| 维度 | 当前状态 | R2→R3 变化 | 评价 |
|------|----------|-----------|------|
| 网络隔离（khub 端口暴露） | khub 无 `ports:` | 不变 | ✅ |
| 进程隔离（非 root） | 用户 `app` | 不变 | ✅ |
| 资源限制 | mem_limit/mem_reservation/cpus | 不变 | ✅ |
| 速率限制 | 30r/m burst=10 nodelay | 大幅收紧 | ⚠️ 见发现 1 |
| 镜像体积 | slim + apt 缓存清理 | 不变 | ✅ |
| 读根文件系统 | 未配 `read_only: true` | 不变 | ❌ R2-F6 未修复 |
| API 鉴权 | 未强制 | 不变 | ❌ 最重大缺口 |
| 信号传递 | `dumb-init→su` 不转发 | 不变 | ❌ R2-F5 未修复 |
| 密钥文件路径 | 注释不一致 | 新增 | ⚠️ 见发现 2 |
| SSL 密钥 git 追踪 | git 包含私钥 | 新增 | ⚠️ 见发现 5 |

---

## 五、结论

### f176e7a 修复评价

| 维度 | 评价 |
|------|------|
| entrypoint `$*` 回归 | ✅ 正确 —— 彻底解决了 R2-H1 回退问题 |
| 限流 30r/m | ✅ 语法正确、安全维度提升 —— 但架构层面需确认 `burst=10` 是否满足批量操作场景 |
| 与 R2 架构评审建议的一致性 | ⚠️ f176e7a 主要修复了**安全评审**的两项（R2-H1, R2-L2），但**架构评审**的 6 项建议修复（R2-F1~F6）均未处理 —— 合理，因安全评审有 P0 级回归 |

### 三轮累计剩余风险 TOP 3

| 优先级 | 问题 | 严重度 | 所属轮次 |
|--------|------|--------|----------|
| 1 | API 鉴权未强制（H1） | 高 | R1 |
| 2 | `dumb-init→su` 信号不传递影响 HA/DR 优雅关闭 | 中 | R2（A3 升级） |
| 3 | `KHUB_PII_ENCRYPT=1` 密钥初始化路径未确认 | 中 | R2 |

### 本次优先修复建议

| # | 问题 | 文件 | 变更量 | 严重度 |
|---|------|------|--------|--------|
| R3-1 | 限流 burst 增至 20-30 或新增健康检查独立限流区 | nginx/khub-docker.conf | 1-2 行 | 中 |
| R3-2 | `KHUB_PII_KEY_FILE` 注释路径 `/root/` → `/home/app/` | docker-compose.yml | 1 行 | 低 |
| R3-3 | `khub-net` 注释修正 | docker-compose.yml | 1 行 | 低 |
| R3-4 | Dockerfile `pip install -e .` → `pip install .` | Dockerfile | 1 字 | 低 |
| R3-5 | SSL 私钥 git 追踪处理（`.gitignore` 或文档标注） | `.gitignore` / `deployment.md` | 1 行 | 低 |

---

*第 3 轮评审结束。f176e7a 两项修复正确，7 项架构评审建议保持未修复状态（无新增阻塞问题）。限流收紧后的吞吐量影响是 R3 最值得关注的架构权衡点，建议在 burst 参数上做微调以平衡安全与功能。*
