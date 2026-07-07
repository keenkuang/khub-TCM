#!/usr/bin/env bash
# 启动 IMA 限速探测（保持后台运行）
set -euo pipefail
cd /home/keen/khub-m1
source /home/keen/.khub/ima.env
exec python -c "
from khub.ima_probe import run_longterm
run_longterm(interval=120)
" >> /home/keen/.khub/ima_probe.log 2>&1
