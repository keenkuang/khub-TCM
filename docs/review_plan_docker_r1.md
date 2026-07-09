# Docker 部署增强方案 — 第 1 轮评审

**评审人**: code-reviewer-22
**日期**: 2026-07-10
**方案**: `docs/plan_docker_enhance.md`
**基线分支**: `m1`

---

## 评审结论

方案方向正确，但存在 **1 个阻塞级别问题**（非 root 用户与卷挂载的权限冲突）和 **4 个建议优化项**。建议修正后进入实施。

---

## 🔴 阻塞问题

### B1. 非 root 用户无法写入运行时挂载卷

**位置**: §2.1 — `adduser --system app` + `USER app` + `chown -R app:app /app`

**问题**: Dockerfile 的 `chown` 仅对构建期 `/app` 目录生效。运行时通过 `docker-compose.yml` 挂载的两个命名卷：

```yaml
volumes:
  - khub-db:/data/db
  - khub-library:/data/library
```

在首次启动时由 Docker 创建并以 **root:root** 所有。应用用户 `app` 无权写入，导致 `Store` 无法创建/打开数据库，`khub serve` 启动即崩溃。

**修复建议**：在 `ENTRYPOINT` 之前（或作为 entrypoint 脚本）添加一个启动前步骤，确保数据目录归 `app` 所有。推荐两种方案：

**方案 A — 改 ENTRYPOINT 为脚本**（推荐，与现有 `dumb-init` 兼容）：

```dockerfile
COPY docker-entrypoint.sh /usr/local/bin/
RUN chmod +x /usr/local/bin/docker-entrypoint.sh
ENTRYPOINT ["dumb-init", "--", "docker-entrypoint.sh"]
CMD ["serve", "--host", "0.0.0.0", "--port", "8765"]
```

`docker-entrypoint.sh` 内容：

```bash
#!/bin/sh
set -e
# 确保数据目录可由 app 用户写入
chown -R app:app /data/db /data/library
# 以 app 用户身份执行主进程
exec gosu app python -m khub.cli "$@"
```

需要额外安装 `gosu`（轻量，~1MB）：

```dockerfile
RUN apt-get install -y --no-install-recommends gosu && rm -rf /var/lib/apt/lists/*
```

**方案 B — 用 su-exec 代替 gosu**（更小，alpine 常用）或直接使用 Python 的 `os.setuid`。但 gosu 在 debian-slim 上最稳妥。

---

## 🟡 建议修改

### M1. docker-compose 中 SSH 密钥 / PII 路径与 app 用户不兼容

**位置**: §2.3 / `docker-compose.yml` 第 12–15 行

**问题**: 注释中的 SSH agent 转发和 PII 密钥挂载示例使用了 root 路径：

```yaml
# - ~/.ssh/id_ed25519:/root/.ssh/id_ed25519:ro          # ← app 用户读不了
# - ./pii.key:/root/.khub/pii.key:ro                     # ← app 用户读不了
```

`adduser --system app` 默认 home 为 `/home/app`，而 `KHUB_PII_KEY_FILE` 默认值为 `~/.khub/pii.key`（即 `/home/app/.khub/pii.key`）。路径对不上。

**建议**：更新注释示例中的容器端路径：

```yaml
# - $SSH_AUTH_SOCK:/ssh-agent:ro
# - ~/.ssh/id_ed25519:/home/app/.ssh/id_ed25519:ro
# - ~/.ssh/known_hosts:/home/app/.ssh/known_hosts:ro
# - ./pii.key:/home/app/.khub/pii.key:ro
```

如果使用方案 A 的 entrypoint 脚本，还可以在脚本中设置 `HOME=/home/app` 以确保 `os.path.expanduser("~")` 解析正确。

---

### M2. nginx docker 配置缺少 Content-Security-Policy

**位置**: §2.4 — `deployment.md` 计划撰写安全头文档说明

**问题**: 方案提到在 `deployment.md` 中补充 CSP/HSTS 说明，但 docker 环境下的 `nginx/khub-docker.conf` **当前没有 CSP 头**。已有 HSTS，但 CSP 完全缺失。仅在文档里写而不更新实际配置，对 docker 用户无保护。

**现有安全头**（`khub-docker.conf`）：
| 头 | 已有 | 值 |
|---|---|---|
| `X-Content-Type-Options` | ✅ | `nosniff` |
| `X-Frame-Options` | ✅ | `DENY` |
| `X-XSS-Protection` | ✅ | `1; mode=block` |
| `Strict-Transport-Security` | ✅ | `max-age=31536000; includeSubDomains` |
| `Content-Security-Policy` | ❌ | — |

**建议**：在 `nginx/khub-docker.conf` 中补充 CSP 头。最小可行 CSP（允许 kHUB 正常加载 WebUI）：

```nginx
add_header Content-Security-Policy "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self'; connect-src 'self'; frame-ancestors 'none'; form-action 'self'" always;
```

同时应更新 `nginx/khub.conf`（宿主机配置）保持对齐。

---

### M3. `.dockerignore` 中 `docs/` 已存在，计划描述需修正

**位置**: §2.2 / 现状分析表第 3 行

**现状表说**：
```
| `.dockerignore` | 已有基础忽略规则 | 缺少 `*.md`、`docs/` 等 |
```

但实际 `.dockerignore` **已有 `docs/`**（第 6 行）。实际缺少的是 `*.md`、`*.pdf`、`*.docx` 以及可能有用的 `*.svg`、`*.png` 等文档资产。

**建议**：修正现状表描述，将 "缺少 `docs/`" 改为文档资产通配符。另可考虑追加：

```
*.svg
*.png
*.jpg
*.jpeg
*.gif
*.ico
```

以及 Docker 无关的 CI/工具文件：

```
.editorconfig
.pre-commit-config.yaml
Makefile
```

---

### M4. Python 3.12 升级与 `pyproject.toml` 版本约束对齐

**位置**: §2.1 — `python:3.11-slim` → `python:3.12-slim`

**问题**: `pyproject.toml` 第 4 行仍为 `requires-python = ">=3.11"`。Docker 升级到 3.12 后运行无问题（3.12 向后兼容），但语义上建议同步更新以明确团队 CI/Tox 测试矩阵：

```
requires-python = ">=3.12"
```

这不是阻塞问题，但如果长期维护，可能有人在本地用 3.11 开发而 Docker 用 3.12，导致版本差异引入 bug。

---

## 🟢 确认无问题

### OK1. dumb-init + non-root 兼容性
`dumb-init` 作为 PID 1 只负责信号转发和僵尸进程收割，与被管理进程的 uid 无关。即使 `USER app` 后以非 root 身份运行，dumb-init 工作正常。

### OK2. WAL_KEEP 在 Docker 环境下的行为
`KHUB_WAL_KEEP=1000` / `KHUB_WAL_KEEP_DAYS=7` 只是 `db.py:prune_wal()` 的环境变量输入，不涉及网络/内核/特权操作，Docker 内外行为一致。两个约束同时设置时取更保守（保留更多）的交集——对容器环境完全安全。

### OK3. HEALTHCHECK 兼容性
当前 HEALTHCHECK 使用纯 stdlib Python，不依赖 curl/wget，与 non-root 用户兼容（仅访问 `127.0.0.1:8765/health`，无特权需求）。

### OK4. EXPOSE 端口
`EXPOSE 8765` 仅作文档用途，不受 USER 指令影响。

---

## 修改清单（修正后建议）

| 文件 | 修改 | 行数预估 | 优先级 |
|------|------|---------|--------|
| `Dockerfile` | Python 3.12 + non-root user + gosu + entrypoint 脚本 | ~15 行 | B1 |
| `docker-entrypoint.sh` | 新建：chown 数据目录 + gosu 降权 | ~8 行 | B1 |
| `docker-compose.yml` | 追加 `KHUB_WAL_KEEP`/`KHUB_WAL_KEEP_DAYS` + SSH/PII 路径修正 | ~5 行 | M1 |
| `nginx/khub-docker.conf` | 追加 CSP 头 | ~1 行 | M2 |
| `nginx/khub.conf` | 追加 CSP 头 + HSTS（宿主机配置对齐） | ~2 行 | M2 |
| `.dockerignore` | 追加 `*.md`、`*.pdf`、`*.docx`（移除重复 `docs/`） | ~3 行 | M3 |
| `pyproject.toml` | `requires-python` → `>=3.12` | ~1 行 | M4 |
| `docs/deployment.md` | 重写 | ~80 行 | 按原计划 |
| `docs/config.md` | 无需改动（已含 WAL_KEEP 文档） | 0 | — |

---

## 附：实施顺序建议

1. **先解决 B1**（Dockerfile + entrypoint 脚本）——这是阻塞项，影响部署可用性
2. **再改 M1**（docker-compose SSH/PII 路径）——路径依赖 B1 的用户选择
3. **M2**（CSP 头）——可与 1、2 并行
4. **M3 + M4**（小修补）——可与 1、2 并行
5. **最后 deployment.md 重写**——全部实现后再写文档，避免文档与实际行为偏差

