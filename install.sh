#!/usr/bin/env bash
set -euo pipefail
REPO="https://github.com/keenkuang/khub-TCM"
KHUB_USER="${KHUB_USER:-khub}"
KHUB_DIR="${KHUB_DIR:-/opt/khub}"
DATA_DIR="${DATA_DIR:-/var/lib/khub}"

echo "=== khub 一键安装脚本 ==="
# 检测 OS
if [ -f /etc/os-release ]; then . /etc/os-release; OS=$ID; else OS=$(uname -s); fi
echo "检测到系统: $OS"

# 安装 Python
if ! command -v python3 &>/dev/null || ! python3 -c "import sqlite3" &>/dev/null; then
  echo "安装 Python 3 + SQLite..."
  case $OS in
    ubuntu|debian) apt-get update && apt-get install -y python3 python3-pip sqlite3 ;;
    centos|rhel|fedora) yum install -y python3 python3-pip sqlite ;;
    *) echo "不支持的 OS: $OS"; exit 1 ;;
  esac
fi

# 创建用户
if ! id "$KHUB_USER" &>/dev/null; then
  useradd -r -s /bin/false -d "$DATA_DIR" "$KHUB_USER"
fi

# 创建目录
mkdir -p "$DATA_DIR" "$KHUB_DIR"
chown "$KHUB_USER:" "$DATA_DIR"

# 克隆/更新代码
if [ -d "$KHUB_DIR/.git" ]; then
  cd "$KHUB_DIR" && git pull
else
  git clone "$REPO" "$KHUB_DIR"
fi

# 安装
cd "$KHUB_DIR"
pip3 install -e ".[all]"

# 初始化数据库
export KHUB_DB="$DATA_DIR/khub.db"
export KHUB_LIBRARY="$DATA_DIR/library"
sudo -u "$KHUB_USER" python3 -c "from khub.db import Store; s=Store('$DATA_DIR/khub.db'); print('DB initialized')"

# 配置 systemd
cat > /etc/systemd/system/khub.service <<EOF
[Unit]
Description=khub 个人知识中枢
After=network.target

[Service]
Type=simple
User=$KHUB_USER
Group=$KHUB_USER
WorkingDirectory=$KHUB_DIR
Environment=KHUB_DB=$DATA_DIR/khub.db
Environment=KHUB_LIBRARY=$DATA_DIR/library
ExecStart=$(which python3) -m khub.cli serve --port 8765
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable khub
systemctl start khub

echo "=== 安装完成 ==="
echo "服务状态："
systemctl status khub --no-pager | head -5
echo ""
echo "访问地址：http://localhost:8765"
echo "管理员密码：请查看日志或设置 KHUB_ADMIN_PASSWORD 环境变量"
