FROM python:3.11-slim

# === 1. 安装系统依赖 ===
# sqlite-vec 和 cryptography 都有预编译 wheel，无需 build-essential
# openssh-client 为 SshReplica 远程灾备提供 ssh/scp 支持
RUN apt-get update && apt-get install -y --no-install-recommends \
    openssh-client \
    && rm -rf /var/lib/apt/lists/*

# === 2. 先安装 Python 依赖（缓存层） ===
# 将 pyproject.toml 单独 COPY，利用 Docker 构建缓存：
# 只要 pyproject.toml 不变，此层就不会重跑
WORKDIR /app
COPY pyproject.toml ./
RUN pip install --no-cache-dir ".[pdf,ann]" && \
    pip install --no-cache-dir cryptography boto3

# === 3. 再复制源码 ===
# 改源码只重建此层（依赖层已缓存）
COPY . .

# === 4. 健康检查（纯 stdlib，无需 curl） ===
# 服务不可用时抛出 URLError → 退出码 1 → HEALTHCHECK 标记 unhealthy
HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8765/health')"

EXPOSE 8765
ENTRYPOINT ["python", "-m", "khub.cli"]
CMD ["serve", "--host", "0.0.0.0", "--port", "8765"]
