# khub 生产部署指南

**版本**: 0.2.0

---

## 运行环境

- **Python**: 3.11+
- **数据库**: SQLite3（需 FTS5 支持，Ubuntu 22.04+ 内置）
- **操作系统**: 推荐 Linux (Ubuntu 22.04+)

## 安装步骤

### 1. 安装 khub

```bash
cd /home/keen/khub-m1
pip install -e ".[pdf,ann]"
```

> 安装耗时约 30~60 秒，取决于网络与依赖缓存。

### 2. 初始化数据目录

```bash
mkdir -p ~/.khub
echo 'db: ~/.khub/khub.db' > ~/.khub/config.yaml
```

### 3. 验证安装

```bash
khub list && echo ok
```

输出 `ok` 表示安装成功。

---

## 作为系统服务（systemd）

### 安装服务

```bash
sudo cp systemd/khub.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now khub
```

### 验证服务状态

```bash
systemctl status khub
curl http://127.0.0.1:8765/health
```

返回 HTTP 200 表示服务正常运行。

---

## 环境变量参考

完整变量列表见 [`docs/config.md`](config.md)。核心变量：

| 变量 | 用途 | 默认值 |
|------|------|--------|
| `KHUB_DB` | SQLite 数据库路径 | `~/.khub/khub.db` |
| `KHUB_LIBRARY` | 受管库目录 | `~/.khub/library` |
| `KHUB_LOG_LEVEL` | 日志级别 | `INFO` |

---

## 安全建议

- **REST API 绑定**: 默认绑定 `127.0.0.1`，不应暴露到公网。
- **PII 加密**: 设置 `KHUB_PII_ENCRYPT=1` 并配置 `KHUB_PII_KEY`（Fernet 密钥）以加密个人身份信息。
- **日志文件**: 建议配置 `KHUB_LOG_FILE=/var/log/khub/khub.log` 以便集中管理日志。

---

## HTTPS / 反向代理

建议通过 nginx 或 Caddy 代理转发到 `127.0.0.1:8765` 并配置 TLS 证书。

### nginx 配置示例

```nginx
server {
    listen 443 ssl;
    server_name khub.example.com;

    ssl_certificate     /etc/ssl/certs/khub.crt;
    ssl_certificate_key /etc/ssl/private/khub.key;

    location / {
        proxy_pass http://127.0.0.1:8765;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

### Caddy 配置示例

```
khub.example.com {
    reverse_proxy 127.0.0.1:8765
}
```

---

## 升级

```bash
cd /home/keen/khub-m1
git pull
pip install -e .
sudo systemctl restart khub
```

---

## 备份

运维与备份说明见 [`docs/operations.md`](operations.md)。
