"""微信公众号 access_token 管理器（仿 feishu._feishu_auth）。"""
from __future__ import annotations
import json
import logging
import os
import time
import urllib.request
import urllib.error

logger = logging.getLogger("khub.wechat.auth")

_token_cache: dict = {"token": "", "expires_at": 0}


def _get_app_credentials():
    appid = os.environ.get("WECHAT_APPID", "")
    secret = os.environ.get("WECHAT_SECRET", "")
    if not appid or not secret:
        raise ValueError("请在环境变量中设置 WECHAT_APPID 和 WECHAT_SECRET")
    return appid, secret


def get_access_token() -> str:
    """返回有效的 access_token（缓存 + 自动刷新）。"""
    now = time.time()
    if _token_cache["token"] and _token_cache["expires_at"] > now + 120:
        return _token_cache["token"]
    appid, secret = _get_app_credentials()
    url = f"https://api.weixin.qq.com/cgi-bin/token?grant_type=client_credential&appid={appid}&secret={secret}"
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
        if "access_token" in data:
            _token_cache["token"] = data["access_token"]
            _token_cache["expires_at"] = now + data.get("expires_in", 7200)
            return _token_cache["token"]
        else:
            raise ValueError(f"获取 token 失败：{data}")
    except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError) as e:
        logger.warning("获取 access_token 失败：%s", e)
        if _token_cache["token"]:
            return _token_cache["token"]
        raise
