FROM python:3.12-slim

# === 1. 安装系统依赖 ===
RUN apt-get update && apt-get install -y --no-install-recommends \
    openssh-client \
    dumb-init \
    && rm -rf /var/lib/apt/lists/*

# === 2. 创建非 root 用户 ===
RUN addgroup --system app && adduser --system --ingroup app app

# === 3. 预装第三方依赖（缓存层） ===
WORKDIR /app
COPY pyproject.toml ./
RUN pip install --no-cache-dir ".[all]"

# === 4. 复制源码并安装 ===
COPY . .
RUN pip install --no-cache-dir . && \
    chown -R app:app /app

# === 5. 入口脚本 ===
COPY docker-entrypoint.sh /usr/local/bin/
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

# === 6. 健康检查 ===
HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8765/health')"

EXPOSE 8765
ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["serve", "--host", "0.0.0.0", "--port", "8765"]
