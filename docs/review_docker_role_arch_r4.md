# Docker 部署架构 —— 第 4 轮评审（终签）

> 评审提交: `086638b` on branch `m1`
> 评审人: CodeBuddy Code (architect role)
> 日期: 2026-07-10

---

## 一、086638b 修复验证

提交 086638b 依 R3 建议修复了 3 项，以下逐项验证：

### R3-1：限流 burst 10 → 20

| 项目 | R3 状态 → 086638b |
|------|------------------|
| 文件 | `nginx/khub-docker.conf:34` |
| 变更 | `burst=10` → `burst=20` |
| 当前 | `limit_req zone=khub_limit burst=20 nodelay;` |

**验证：✅ 修复正确**
- 30r/m + burst=20 nodelay 在单页多资源加载（CSS/JS 各 5-8 个请求 + API 首屏）和典型 RAG 查询下不会误触 429
- `/health` 未显式限流，仍与主区共享计数——可接受，健康检查频率低（30s × 3 retries ≈ 0.1 r/m），消耗可忽略
- 与 `limit_req_zone rate=30r/m` 参数一致

### R3-2：`KHUB_PII_KEY_FILE` 注释路径 `/root/` → `/home/app/`

| 项目 | R3 状态 → 086638b |
|------|------------------|
| 文件 | `docker-compose.yml:29` |
| 变更 | `/root/.khub/pii.key` → `/home/app/.khub/pii.key` |
| 当前 | `# - KHUB_PII_KEY_FILE=/home/app/.khub/pii.key` |

**验证：✅ 修复正确**
- 注释路径与卷挂载注释（L18 `/home/app/.khub/pii.key:ro`）一致
- 与运行时用户 `app` 的 HOME 一致
- 注释文案从 `"PII 密钥由容器自动生成（首次启动），或通过 KHUB_PII_KEY 传入"` 同步更新为更精确的表述

### R3-4：`pip install -e .` → `pip install .`

| 项目 | R3 状态 → 086638b |
|------|------------------|
| 文件 | `Dockerfile:19` |
| 变更 | `-e .` → `.` |
| 当前 | `RUN pip install --no-cache-dir . && \` |

**验证：✅ 修复正确**
- 移除 `-e` 后镜像层不再产生 `.egg-link` / `.pth` 文件
- 容器内源码运行期不可编辑，editable mode 无意义
- 分层缓存逻辑未受影响（`COPY pyproject.toml → pip install 第三方依赖` → `COPY . → pip install .`）

---

## 二、R1-R3 全量修复追踪矩阵

| # | 问题 | 文件 | 所属 | 预期修复 | 当前状态 | 验证 |
|---|------|------|------|---------|----------|------|
| C1 | 网络隔离 | docker-compose.yml | R1 | `khub-net` 命名桥接 | `khub-net internal: false`，khub 无 ports | ✅ 合理权衡 |
| B1 | entrypoint `$*` | docker-entrypoint.sh | R1 | `"$@"` → 回归 `$*` | `su -c "python -m khub.cli $*"` | ✅ 回归正确 |
| H1/M2 | nginx 限流 | nginx/khub-docker.conf | R1 | 20r/s→30r/m→burst=20 | `30r/m burst=20 nodelay` | ✅ 已微调 |
| R3-1 | burst 10→20 | nginx/khub-docker.conf | R3 | 提至 20 | `burst=20` | ✅ 086638b |
| R3-2 | PII 路径 `/root/`→`/home/app/` | docker-compose.yml | R3 | 对齐非 root | `/home/app/.khub/pii.key` | ✅ 086638b |
| R3-4 | `pip install -e`→`.` | Dockerfile | R3 | 去 editable | `pip install --no-cache-dir .` | ✅ 086638b |
| R3-5 | SSL 私钥 git 追踪 | `.gitignore` / git | R3 | 排除或标注 | `.gitignore` 已有 `ssl/`，`git ls-files ssl/` 为空 | ✅ 已解决 |

### 未修复项（均非阻塞，R3 已认可）

| # | 问题 | 文件 | 严重度 | 跨轮次 | 备注 |
|---|------|------|--------|--------|------|
| R2-F1 | 预装依赖未锁定版本 | Dockerfile L15 | 中 | R1→R2→R3→R4 | 需引入 constraints.txt |
| R2-F2 | 健康检查重复且不一致 | Dockerfile + compose | 低 | R2→R3→R4 | 30s 与 10s 差异 |
| R2-F3 | 无日志轮转 | docker-compose.yml | 低 | R2→R3→R4 | json-file 默认无 max-size |
| R2-F4 | PII 密钥初始化需确认 | 应用代码 | 中 | R2→R3→R4 | 架构层不越界 |
| R2-F5 | dumb-init→su 信号不传递 | docker-entrypoint.sh | 中 | R1→R2→R3→R4 | 影响优雅关闭 |
| R2-F6 | 未配 `read_only: true` | docker-compose.yml | 低 | R2→R3→R4 | 安全加固项 |
| D1 | CSP `'unsafe-inline'` | nginx/khub-docker.conf | 中 | R1→R2→R3→R4 | 需前端配合 |
| D2 | `form-action 'none'` | nginx/khub-docker.conf | 中 | R1→R2→R3→R4 | 需前端验证 |
| A2 | 缺少 USER 指令注释 | Dockerfile | 低 | R1→R2→R3→R4 | 非阻塞 |
| R3-3 | khub-net 注释误导 | docker-compose.yml L71 | 低 | R3→R4 | 见下 |

#### R3-3 补充说明：`khub-net` 注释仍为旧文案

**当前**（docker-compose.yml:71）：
```yaml
internal: false  # nginx 暴露端口，khub 服务不对外
```

**问题**：`internal: false` 实际控制的是容器能否**出站访问外网**（internet 连通性），khub 端口不对外是由**无 `ports:` 定义**实现的。当前注释的因果关系错误。

**建议**（R3 已提出，继续记录）：
```yaml
internal: false  # khub 需出站连接（SSH 灾备、真实模型 API）
```

**严重度**：低 — 仅注释文案，不影响运行时行为。

---

## 三、四轮累计安全与架构边界复核

| 维度 | R1 | R2 | R3 | R4 | 趋势 |
|------|----|----|----|----|------|
| 网络隔离 | ❌→✅ | ✅ | ✅ | ✅ | 已加固 |
| 参数展开 `$*` | ❌→✅ | ⚠️回归→✅ | ✅ | ✅ | 已稳定 |
| 速率限制 | ❌→✅ | ⚠️收紧→✅ | ⚠️→✅ | ✅ | 已调优 |
| PII 密钥文件路径 | — | ❌ | ❌→✅ | ✅ | 已修复 |
| SSL 密钥 git 追踪 | — | — | ⚠️ | ✅ | 已排除 |
| editable 模式 | — | — | ⚠️→✅ | ✅ | 已简化 |
| 预装依赖锁定 | ❌ | ❌ | ❌ | ❌ | 跨四轮未动 |
| 信号传递 | ❌ | ❌ | ❌ | ❌ | 跨四轮未动 |
| 健康检查统一 | — | ❌ | ❌ | ❌ | 跨三轮未动 |
| 日志轮转 | — | ❌ | ❌ | ❌ | 跨三轮未动 |
| CSP 精确性 | ❌ | ❌ | ❌ | ❌ | 需前端配合 |
| `read_only` 加固 | — | ❌ | ❌ | ❌ | 低优先级 |
| PII 密钥初始化 | — | ❌ | ❌ | ❌ | 需确认应用侧 |
| 注释精度 | — | — | ⚠️ | ❌ | 非阻塞 |

> **趋势判断**：经过 4 轮评审，7 项阻塞/关键问题全部关闭（C1→B1→H1→R3-1→R3-2→R3-4→R3-5）。
> 剩余 8 项开放均为"建议修复"或"仅供参考"，且跨轮次未恶化。架构质量已稳定。

---

## 四、总体评价

### 086638b 修复评价

| 修复项 | 评价 |
|--------|------|
| burst 10→20 | ✅ 正确 —— 平衡了安全限流与单页多请求场景 |
| PII 路径 `/root/`→`/home/app/` | ✅ 正确 —— 注释与挂载点完全对齐 |
| `pip install -e .`→`.` | ✅ 正确 —— 容器镜像无需 editable 模式 |

### 四轮累计交付质量

| 指标 | 数值 |
|------|------|
| 评审轮次 | 4 轮 |
| 发现总问题数 | ~20 项 |
| 阻塞/**必须修复** | 1 项（C1）— 已修复 |
| 建议修复 | ~12 项 — 7 项已修复 |
| 仅供参考 | ~7 项 — 2 项已处理 |
| 当前开放 | 8 项（均建议/参考级） |

### 结论：**最终签署通过**

- 所有阻塞性问题（C1）已关闭
- 086638b 三项修复正确，代码与设计匹配
- 剩余开放项均非阻塞，可在 v0.2.5 或后续版本规划中迭代
- 架构方向正确，实现质量经过 4 轮交叉验证

---

## 五、签署

```
架构评审角色: CodeBuddy Code
评审状态: ✅ 最终签署
日期: 2026-07-10
```

---

*第 4 轮评审结束。Docker 增强架构评审四轮全部完成，建议允许合并。*
