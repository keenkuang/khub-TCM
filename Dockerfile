FROM python:3.11-slim

# === 1. 安装系统依赖 ===
# sqlite-vec 和 cryptography 都有预编译 wheel，无需 build-essential
# openssh-client 为 SshReplica 远程灾备提供 ssh/scp 支持
# dumb-init 作为 PID 1 收割僵尸子进程（SshReplica/scheduler 会 spawn 子进程）
RUN apt-get update && apt-get install -y --no-install-recommends \
    openssh-client \
    dumb-init \
    && rm -rf /var/lib/apt/lists/*

# === 2. 先预装第三方依赖（缓存层） ===
# 利用 Docker 分层缓存：只装 wheel 包，不装 khub 自身。
# 注意：预装仅用于缓存提速，版本约束以 pyproject.toml 为准。
# 下一层 pip install -e . 会自动补齐/对齐版本。
WORKDIR /app
COPY pyproject.toml ./
RUN pip install --no-cache-dir PyYAML pypdf sqlite-vec cryptography boto3

# === 3. 再复制源码并安装 khub ===
# 改源码只重建此层（依赖层已缓存）
COPY . .
RUN pip install --no-cache-dir -e .

# === 4. 健康检查（纯 stdlib，无需 curl） ===
# 服务不可用时抛出 URLError → 退出码 1 → HEALTHCHECK 标记 unhealthy
HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8765/health')"

EXPOSE 8765
ENTRYPOINT ["dumb-init", "--", "python", "-m", "khub.cli"]
CMD ["serve", "--host", "0.0.0.0", "--port", "8765"]
