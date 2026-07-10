# Docker 部署安全评审 —— 第 4 轮 (R4 / Final)

**评审范围**: commit `086638b` (R3 修复)，基于 R1/R2/R3 报告
**评审日期**: 2026-07-10
**R3 修复提交**: `086638b fix(docker): R3 评审修复——burst + PII路径 + pip install`

| 文件 | 行数 | 角色 |
|------|------|------|
| `Dockerfile` | 33 | 镜像构建定义 |
| `docker-entrypoint.sh` | 7 | 容器入口 & 权限降级 |
| `docker-compose.yml` | 87 | 编排配置 & 密钥管理 |
| `nginx/khub-docker.conf` | 57 | 反向代理 & 安全标头 |

---

## 1. R3 修复验证（commit 086638b）

### 1.1 burst 10 → 20（对应 R3-M1 部分修复）

| 属性 | 值 |
|------|------|
| 原值（f176e7a） | `burst=10 nodelay` |
| 修复后（086638b） | `burst=20 nodelay` |
| 当前代码 | `nginx/khub-docker.conf:34` |

**验证结果**: ✅ **已修复**。

**分析**:
- `rate=30r/m` 下，burst=20 提供 40 秒的令牌桶容量
- 单次页面加载（典型 5–15 个子请求）可通过 burst 完全消化
- 用户正常浏览间隔 >2 秒时，不触发额外限流
- 相比 burst=10（R3 报告指出单页加载即触发 429），burst=20 对单用户内部工具已足够

**遗留**: 主速率 30r/m 未调整（仍为 R3-M1 讨论范畴）。这是安全性与可用性的权衡——在当前单用户场景下，30r/m + burst=20 是合理的折中点。

---

### 1.2 PII_KEY_FILE 路径 `/root/` → `/home/app/`（对应 R3 架构发现 2）

| 属性 | 值 |
|------|------|
| 原值（f176e7a） | `KHUB_PII_KEY_FILE=/root/.khub/pii.key` |
| 修复后（086638b） | `KHUB_PII_KEY_FILE=/home/app/.khub/pii.key` |
| 当前代码 | `docker-compose.yml:29` |

**验证结果**: ✅ **已修复**。

注释中的路径与卷挂载路径（`./pii.key:/home/app/.khub/pii.key:ro`，line 18）已对齐，消除了密钥加载失败的隐患。

---

### 1.3 `pip install -e .` → `pip install .`（对应 R3 架构发现 4）

| 属性 | 值 |
|------|------|
| 原值（f176e7a） | `pip install --no-cache-dir -e .` |
| 修复后（086638b） | `pip install --no-cache-dir .` |
| 当前代码 | `Dockerfile:19` |

**验证结果**: ✅ **已修复**。

容器内无需 editable 模式，移除 `-e` 后镜像层更简洁。

---

## 2. R3 修复未引入回归

对 4 个评审文件进行了全量回归检查，确认 086638b 未引入任何新问题：

| 检查维度 | 结论 |
|----------|------|
| 语法正确性（Dockerfile / compose / nginx / entrypoint） | ✅ 无语法错误 |
| `$*` 保留（R2-H1 修复未退化） | ✅ 仍为 `$*` |
| entrypoint 参数传递完整性 | ✅ 4 个 CMD 参数全部进入 `su -c` |
| 30r/m 限流配置 | ✅ 未改变 |
| 健康检查 `location /health` | ✅ 未改变 |
| PII 加密默认启用 | ✅ `KHUB_PII_ENCRYPT=1` 保留 |
| 非 root 用户 | ✅ `app` 用户保留 |
| HSTS / CSP / 安全标头 | ✅ 未变化 |

---

## 3. 累积未修复发现状态（R1–R4）

以下发现跨越 4 轮评审仍然存在，本报告仅做追踪，不视为本轮阻塞项：

### 已知设计决策 / 非本轮目标

| 编号 | 标题 | 等级 | 首次报告 | 理由 |
|------|------|------|----------|------|
| H1 | 生产部署无强制 API 鉴权 | 高 | R1 | 需业务评估，非本轮范围 |
| M1 | CSP `'unsafe-inline'` | 中 | R1 | 需前端配合，非本轮范围 |
| M3 | `openssh-client` 带入生产运行时 | 中 | R1 | 架构决策——SshReplica 需要，可后续拆 sidecar |
| L3 | 环境变量传递密钥 | 低 | R1 | 已提供 `_FILE` 替代方案，文档已标注 |
| I1 | X-XSS-Protection 已弃用 | 信息 | R1 | 无安全危害，仅代码整洁问题 |

### 低优先级加固项（未在本轮分配）

| 编号 | 标题 | 等级 | 首次报告 |
|------|------|------|----------|
| L1 | 入口脚本静默忽略 `chown` 错误 | 低 | R1 |
| L2 | 自签名证书缺少生产替换说明 | 低 | R1 |
| L4 | Nginx 未设置 Referrer-Policy 标头 | 低 | R1 |
| R2-M1 | `/health` 端点绕过限流 | 中 | R2 |
| R2-M2 | 网络隔离 `internal: false` | 中 | R2 |
| R2-L1 | 无被拦截请求日志 | 低 | R2 |
| R3-L1 | 缺少 `no-new-privileges` | 低 | R3 |
| R3-L2 | 缺少 `read_only` 根文件系统 | 低 | R3 |
| R3-L3 | 缺少 `cap_drop: ALL` | 低 | R3 |

---

## 4. 安全基准对照（最终）

| 基准项目 | R1 | R2 | R3 | R4 | 最终状态 |
|----------|----|----|----|----|---------|
| 非 root 用户运行 | ✅ | ✅ | ✅ | ✅ | ✅ |
| HEALTHCHECK | ✅ | ✅ | ✅ | ✅ | ✅ |
| 资源限制 | ✅ | ✅ | ✅ | ✅ | ✅ |
| HSTS | ✅ | ✅ | ✅ | ✅ | ✅ |
| 网络隔离（端口关闭） | ❌ | ⚠️ | ⚠️ | ⚠️ | khub 无 ports:；但 internal: false |
| 限流 | ❌ | ⚠️ | ⚠️ | ⚠️ | 30r/m burst=20 已配置；/health 未覆盖 |
| Entrypoint 安全性 | ✅ | ❌ | ✅ | ✅ | $* 正确，R2-H1 已修复 |
| CSP | ⚠️ | ⚠️ | ⚠️ | ⚠️ | unsafe-inline 待前端配合 |
| API 鉴权 | ❌ | ❌ | ❌ | ❌ | 最大缺口，需业务决策 |
| 只读根文件系统 | ❌ | ❌ | ❌ | ❌ | 未处理 |
| `cap_drop=ALL` | ❌ | ❌ | ❌ | ❌ | 未处理 |
| `no-new-privileges` | ❌ | ❌ | ❌ | ❌ | 未处理 |
| Docker 密钥 | ❌ | ❌ | ❌ | ❌ | 已提供 _FILE 替代 |
| 日志审计（限流） | ✅ | ❌ | ❌ | ❌ | 未处理 |
| 镜像漏洞扫描 | ❌ | ❌ | ❌ | ❌ | 未集成 |

---

## 5. R4 评审结论

### R3 修复评价

| 修复项 | 评价 |
|--------|------|
| burst 10→20 | ✅ 正确——缓解了单页加载触发 429 的问题 |
| PII 路径 `/root/`→`/home/app/` | ✅ 正确——路径对齐，消除密钥加载隐患 |
| pip install `-e` 移除 | ✅ 正确——容器内无需 editable 模式 |

**086638b 未引入任何新漏洞或回归。**

### 最终签意见

✅ **本轮无阻塞安全问题。**

commit `086638b` 正确完成了其 3 项 R3 修复目标。所有 4 个评审文件（Dockerfile、docker-entrypoint.sh、docker-compose.yml、nginx/khub-docker.conf）在当前分支 m1 上的安全状态可以接受：

- 核心安全机制（非 root 用户、资源限制、HSTS、限流）已到位
- 入口脚本参数传递正确（R2-H1 回归已修复）
- 已知剩余发现均为**有意识的设计决策**（H1 API 鉴权需业务评估）或**低优先级加固项**（cap_drop、read_only 等）

### 优先级建议（供后续迭代参考）

1. **🔴 P0**: API 鉴权（H1）——从 R1 积累至今的最大攻击面
2. **🟡 P1**: `/health` 限流（R2-M1）+ 网络隔离 `internal: true`（R2-M2）
3. **🟤 P2**: Docker 安全加固 `cap_drop: ALL`、`read_only`、`no-new-privileges`、限流日志
4. **⚪ P3**: CSP 强化（M1）、文档改进（L2）、SSH sidecar（M3）

---

*评审人: security-bot / general-purpose-40*
*基线: R1 (04e1121) + R2 (bf3e90d) + R3 (f176e7a) + R3 修复 (086638b)*
*对照标准: OWASP Docker Security Cheat Sheet + CIS Docker Benchmark v1.6*
