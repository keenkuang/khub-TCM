#!/usr/bin/env bash
# kHUB 数据目录初始化
set -euo pipefail

KHUB_DB="${KHUB_DB:-$HOME/.khub/khub.db}"
KHUB_LIB="${KHUB_LIBRARY:-$HOME/.khub/library}"
KHUB_DIR="$(dirname "$KHUB_DB")"

echo "▶ 初始化 kHUB 数据目录: $KHUB_DIR"
mkdir -p "$KHUB_DIR" "$KHUB_LIB"

if [ ! -f "$KHUB_DB" ]; then
    echo "  → 数据库文件将在首次启动时自动创建"
fi

echo "▶ 检查 pip 包..."
cd "$(dirname "$0")/.."
pip install -e ".[pdf,ann]" -q 2>/dev/null && echo "  → khub 已安装" || echo "  → 跳过"

echo "✓ 就绪"
echo "  启动: cd $(pwd) && python -m khub.cli serve --port 8765"
echo "  查看: http://127.0.0.1:8765"
