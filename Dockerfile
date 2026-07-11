# Stage 1: Builder
FROM python:3.12-slim AS builder
WORKDIR /build
COPY pyproject.toml README.md ./
COPY khub/ khub/
RUN pip install --no-cache-dir -e ".[all]" && \
    python3 -c "from khub.db import Store; print('OK')"

# Stage 2: Runtime
FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends \
    dumb-init openssh-client \
    && rm -rf /var/lib/apt/lists/*
RUN groupadd -r khub && useradd -r -g khub -d /data -s /sbin/nologin khub
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /build/khub /app/khub
COPY --from=builder /build/pyproject.toml /app/
COPY docker-entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh
ENV KHUB_DB=/data/khub.db KHUB_LIBRARY=/data/library
EXPOSE 8765
HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
    CMD python3 -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8765/health')" || exit 1
VOLUME ["/data"]
ENTRYPOINT ["/entrypoint.sh"]
CMD ["python3", "-m", "khub.cli", "serve", "--port", "8765"]
