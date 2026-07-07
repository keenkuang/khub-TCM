#!/usr/bin/env bash
# kHUB 桌面启动脚本
# 用法: bash desktop/run.sh
# 首次运行会自动安装 Electron（需网络，~100MB）
set -euo pipefail
cd "$(dirname "$0")/.."

if [ ! -d "node_modules" ]; then
  echo "▶ 安装 Electron……"
  cd desktop && npm install --no-audit --no-fund && cd ..
fi

echo "▶ 启动 kHUB 桌面版……"
cd desktop && npx electron .
