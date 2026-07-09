#!/bin/sh
# kHUB Docker entrypoint
# 修正运行时挂载卷所有权，再以降权用户执行命令
set -e
chown -R app:app /data/db /data/library 2>/dev/null || true
exec dumb-init su -s /bin/sh app -c "python -m khub.cli $@"
