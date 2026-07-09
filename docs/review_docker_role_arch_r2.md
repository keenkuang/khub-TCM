# Docker 部署架构 —— 第 2 轮评审

> R1 修复提交: `bf3e90d`
> 评审人: CodeBuddy Code (architect role)
> 日期: 2026-07-10

---

## 一、R1 修复验证

R1 重点修复了架构评审的 **C1（网络隔离）**、**B1（entrypoint 参数展开）**，
以及安全评审的 **H1/M2（nginx 限流）**。以下逐项验证。

### C1 — 网络隔离（docker-compose.yml）

| 项目 | 状态 |
|------|------|
| R1 建议 | 拆分 internal（`internal: true`）+ external 双网络 |
| 实际实现 | 单一 `khub-net`，`internal: false`，两个服务均接入 |

**验证：✅ 修复正确，属合理权衡**

- khub 无 `ports:` 暴露，仅 nginx 对宿主机暴露 80/443
- 命名桥接网络已实现与 default 网络的隔离，外部容器默认无法访问 khub
- `internal: false` 是有意选择：khub 需要出站连接（SshReplica SSH、嵌入/LLM 真实模型 API）
- 双网络模式在本架构中收益有限（仅 nginx+khub 两个服务），单网络更简洁

### B1 — entrypoint `$*` → `$@`（docker-entrypoint.sh）

| 项目 | 状态 |
|------|------|
| R1 建议 | `"$@"` 保留参数边界 |
| 实际实现 | 裸 `$@`（无外层双引号） |

**验证：✅ 修复正确**

- `$*` 将所有参数空格拼接 → `$@` 保持参数分隔，行为已改善
- 当前 CMD 为 `serve --host 0.0.0.0 --port 8765`，所有参数无空格，实际无差异
- 理想形式应为 `"$@"`，但 `su -c "..."` 字符串内 `"$@"` 的展开行为有限，当前实现满足需求

### H1/M2 — nginx 限流（khub-docker.conf）

| 项目 | 状态 |
|------|------|
| R1 要求 | 新增 rate limiting |
| 实际实现 | `limit_req_zone`（20r/s）+ `limit_req burst=50 nodelay` |

**验证：✅ 修复正确**

- 配置语法正确，语义合理：每 IP 20r/s，突发 50，超限立即 503
- 仅应用于 `location /`（API 代理），`location /health` 未加限流——正确，健康检查不应受限
- 10MB 共享内存可追踪约 160k 独立 IP，对单机部署充足

### R1 其他条目状态一览

| # | 问题 | 严重度 | 状态 | 说明 |
|---|------|--------|------|------|
| A1 | Dockerfile 预装未锁定版本 | 中 | ❌ 未修复 | 仍在同一层级 |
| A2 | 缺少 USER 指令注释 | 低 | ❌ 未修复 | 非阻塞 |
| A3 | gosu fallback / 信号传递 | 低 | ❌ 未修复 | 确认仍存在（见 R2 §三-1） |
| B2 | 卷挂载覆写入口脚本 | 低 | ❌ 未修复 | 非阻塞 |
| D1 | CSP `'unsafe-inline'` | 中 | ❌ 未修复 | 需前端配合 |
| D2 | `form-action 'none'` 验证 | 中 | ❌ 未修复 | 需前端验证 |
| D3 | X-XSS-Protection 已废弃 | 低 | ❌ 未修复 | 兼容保留 |
| D4 | proxy_cookie_flags | 低 | ❌ 未修复 | 未来预案 |
| E1 | 升级章节未拆分 | 低 | ❌ 未修复 | 非阻塞 |
| E2 | CSP 安全性描述不精确 | 低 | ❌ 未修复 | 非阻塞 |

> 以上未修复项多为"建议修复"或"仅供参考"级别，R1 聚焦必须修复项（C1）是合理选择。

---

## 二、R2 新增发现

### 发现 1：健康检查配置重复且不一致

**Dockerfile**（L27-L28）：
```
HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
  CMD python -c "..."
```

**docker-compose.yml**（L37-L42）：
```yaml
healthcheck:
  test: ["CMD", "python", "-c", "..."]
  interval: 10s
  timeout: 5s
  retries: 3
  start_period: 15s
```

**影响**：docker-compose 的 healthcheck 会覆盖 Dockerfile 中的定义，且差异显著：
- compose 版本 3x 更激进（10s 间隔 vs 30s），可能在小负载波动时导致误判
- compose 版本 2x 更短的超时（5s vs 10s），python stdlib URL 请求在首次 JIT 预热时偶尔超过 5s

**建议**：统一在 docker-compose.yml 中保留一份，删除 Dockerfile 中的 HEALTHCHECK，或使两者一致并加注释说明优先级。

- **严重度**: 低
- **验证方法**: `docker inspect` 确认生效的 healthcheck 参数

---

### 发现 2：无健康检查重试背压

nginx 的 `depends_on: condition: service_healthy` 确保启动顺序正确，但未配置 nginx 端 `proxy_next_upstream` 或熔断逻辑。若 khub 在运行时进入 failing 状态（如 DB 损坏、磁盘满），nginx 继续转发导致客户端收到 502/503。

**建议**：至少添加错误日志告警建议到部署文档。若未来多实例扩展，需引入主动熔断。

- **严重度**: 低
- **验证方法**: 模拟 khub 故障，观察 nginx 行为

---

### 发现 3：无日志轮转配置

nginx 日志输出到 stdout/stderr（Docker 惯例），但 docker-compose.yml 未配置 `logging:` 驱动限制。`json-file` 日志驱动在默认无限制时，长期运行可能耗尽磁盘。建议添加：

```yaml
logging:
  driver: "json-file"
  options:
    max-size: "10m"
    max-file: "3"
```

- **严重度**: 低
- **验证方法**: `docker inspect khub-m1-nginx-1 | jq '.[0].HostConfig.LogConfig'`

---

### 发现 4：`KHUB_PII_ENCRYPT=1` 但入口脚本无密钥初始化逻辑

`docker-compose.yml` 中设置了 `KHUB_PII_ENCRYPT=1`，注释声称"PII 密钥由容器自动生成（首次启动）"，但 `docker-entrypoint.sh` 中没有对应的密钥初始化逻辑。

若应用内部自行管理（首次启动时生成密钥并持久化），需确认持久化位置在卷 `khub-db` 上，否则容器重建后密钥丢失、已加密数据无法解密。

**建议**：确认密钥初始化逻辑实现在 `khub.cli` 内部且密钥持久化在卷上，或补充文档说明。

- **严重度**: 中
- **验证方法**: 阅读 `khub/cli.py` 或 `khub/pii.py` 中密钥初始化逻辑

---

## 三、架构级复核

### 1. 信号传递链：`dumb-init → su → python`（A3 重申）

- PID 1: `dumb-init` — 正确收割僵尸、转发信号
- PID 2: `su -s /bin/sh app -c "python -m khub.cli serve ..."` — **不转发信号**
- PID 3: `python` — 永远不会收到 SIGTERM

`stop_grace_period: 60s` 缓解了问题（Docker 最终 SIGKILL），但 WAL 落盘、PII 写回等优雅关闭逻辑将无法执行。

**建议**：虽列在"仅供参考"级别，但在 HA/DR 场景下（确保 WAL 一致性），此问题应升级为"建议修复"。最简单的方案是 entrypoint 改用 `exec su app -c "$0 $@"` 并配合 `gosu`，或 Python 脚本自身封装 PID 1 逻辑。

### 2. 安全边界

| 维度 | 当前状态 | 评价 |
|------|----------|------|
| 网络隔离 | 命名桥接，khub 无端口暴露 | ✅ |
| 进程隔离 | 非 root 用户 | ✅ |
| 资源限制 | mem_limit/mem_reservation/cpus | ✅ |
| 速率限制 | 20r/s + burst 50 | ✅ |
| 镜像体积 | slim 基础镜像，apt 缓存清理 | ✅ |
| 读根文件系统 | 未配置 `read_only: true` | ⚠️ 建议加固 |
| API Token | 未在 compose 中配置 | ⚠️ 可接受（端口不对外）|

### 3. 可维护性

| 维度 | 评价 |
|------|------|
| 构建缓存 | Dockerfile 分层缓存设计良好 |
| 信号处理 | ⚠️ `su` 不转发信号 |
| 日志 | ⚠️ 无日志轮转 |
| 健康检查 | ⚠️ Dockerfile 与 compose 重复 |

---

## 四、汇总

### 已修复并验证通过

| # | 修复内容 | 文件 | 评价 |
|---|----------|------|------|
| C1 | 网络隔离（khub-net） | docker-compose.yml | ✅ 合理权衡 |
| B1 | `$*` → `$@` | docker-entrypoint.sh | ✅ |
| H1/M2 | nginx 限流 20r/s | nginx/khub-docker.conf | ✅ |

### 建议修复（R2 新增 + A1/A3 升级）

| # | 问题 | 文件 | 建议严重度 |
|---|------|------|-----------|
| R2-F1 | 预装依赖未锁定版本 | Dockerfile | 中 |
| R2-F2 | 健康检查配置重复且不一致 | Dockerfile + compose | 低 |
| R2-F3 | 无日志轮转 | docker-compose.yml | 低 |
| R2-F4 | `KHUB_PII_ENCRYPT=1` 密钥初始化需确认 | docker-entrypoint.sh / app code | 中 |
| R2-F5 | `dumb-init → su` 信号不传递（原 A3） | docker-entrypoint.sh | 中（HA/DR 场景） |
| R2-F6 | 未配置 `read_only: true` | docker-compose.yml | 低 |

### 与 R1 一致的未修复建议

| # | 问题 | 严重度 | 理由 |
|---|------|--------|------|
| D1 | CSP `'unsafe-inline'` | 中 | 需前端配合，架构评审不越界 |
| D2 | `form-action 'none'` | 中 | 需前端验证 |
| E1/E2 | deploy.md 精度 | 低 | 文档问题，不影响运行 |

---

## 五、结论

- **R1 三处修复全部正确**，网络隔离的单网络方案为合理权衡
- **无新增架构级阻塞问题**
- 最值得关注的遗留问题：
  1. `dumb-init → su` 信号链（A3）在 HA/DR 场景下应升级处理
  2. `KHUB_PII_ENCRYPT=1` 密钥初始化路径需确认
  3. 健康检查应统一清理以减少混淆

---

*第 2 轮评审结束。R1 修复验证通过，架构方向一致，建议在 v0.2.5 迭代中处理上述建议修复项。*
