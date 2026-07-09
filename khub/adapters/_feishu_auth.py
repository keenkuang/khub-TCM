"""飞书 tenant_access_token 管理。

策略：
- token 缓存到内存，过期前 5 分钟自动刷新
- 首次获取若有 env，使用 app_id/app_secret 请求
"""

from __future__ import annotations

import json
import os
import time
import urllib.request

_TOKEN_URL = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"


class FeishuTokenManager:
    """管理飞书 tenant_access_token 的获取与缓存。"""

    def __init__(self):
        self._token = ""
        self._expires_at = 0.0

    @property
    def token(self) -> str:
        if time.time() >= self._expires_at - 300:
            self._refresh()
        return self._token

    def _refresh(self):
        app_id = os.environ.get("FEISHU_APP_ID", "")
        app_secret = os.environ.get("FEISHU_APP_SECRET", "")
        if not app_id or not app_secret:
            raise RuntimeError("需要设置 FEISHU_APP_ID 和 FEISHU_APP_SECRET 环境变量")

        body = json.dumps({
            "app_id": app_id,
            "app_secret": app_secret,
        }).encode()
        req = urllib.request.Request(
            _TOKEN_URL, data=body,
            headers={"Content-Type": "application/json; charset=utf-8"},
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())

        self._token = data.get("tenant_access_token", "")
        expire_sec = data.get("expire", 7200)
        self._expires_at = time.time() + expire_sec
