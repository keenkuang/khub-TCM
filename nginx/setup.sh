#!/usr/bin/env bash
# kHUB 一键部署脚本：nginx 反代 + 自签名 TLS + systemd 服务
# 用法: sudo bash nginx/setup.sh
# 说明: 请在运行前确认已安装 nginx (sudo apt install nginx)
set -euo pipefail

KHDIR="$(cd "$(dirname "$0")/.." && pwd)"

echo "==> 1. 验证 nginx 已安装"
if ! command -v nginx &>/dev/null; then
  echo "请先安装 nginx: sudo apt install nginx -y" >&2
  exit 1
fi

echo "==> 2. 复制 TLS 证书"
sudo mkdir -p /etc/nginx/ssl
sudo cp "$KHDIR/ssl/khub.crt" /etc/nginx/ssl/
sudo cp "$KHDIR/ssl/khub.key" /etc/nginx/ssl/
sudo chmod 644 /etc/nginx/ssl/khub.crt
sudo chmod 600 /etc/nginx/ssl/khub.key

echo "==> 3. 配置 nginx 站点"
sudo mkdir -p /etc/nginx/sites-available /etc/nginx/sites-enabled
sudo cp "$KHDIR/nginx/khub.conf" /etc/nginx/sites-available/khub
if [ ! -L /etc/nginx/sites-enabled/khub ]; then
  sudo ln -sf /etc/nginx/sites-available/khub /etc/nginx/sites-enabled/
fi
# 移除默认站点（可选）
sudo rm -f /etc/nginx/sites-enabled/default

echo "==> 4. 测试配置"
sudo nginx -t || { echo "nginx 配置错误，请检查"; exit 1; }

echo "==> 5. 重载 nginx"
sudo systemctl reload nginx || sudo systemctl restart nginx

echo "==> 6. 验证 kHUB 是否运行"
if ! curl -sf http://127.0.0.1:8765/health >/dev/null 2>&1; then
  echo "kHUB 服务未运行，启动中……"
  if systemctl is-enabled --quiet khub 2>/dev/null; then
    sudo systemctl start khub
  else
    echo "请先配置 systemd: sudo cp systemd/khub.service /etc/systemd/system/ && sudo systemctl daemon-reload && sudo systemctl start khub" >&2
    exit 1
  fi
fi

echo "==> 7. 验证 HTTPS"
sleep 1
curl -sk https://127.0.0.1/health | python3 -m json.tool
echo ""
echo "部署完成。"
echo "浏览器访问: https://127.0.0.1"
echo "局域网访问: https://172.22.22.127"
echo "TLS 为自签名证书，浏览器首次会提示安全警告，点"高级→继续"即可。"
