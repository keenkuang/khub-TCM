"""微信公众号平台 API 封装（素材管理/群发/粉丝同步）。"""
from __future__ import annotations
import json
import logging
import urllib.request
import urllib.error

from .auth import get_access_token

logger = logging.getLogger("khub.wechat.api")

_BASE = "https://api.weixin.qq.com/cgi-bin"


def _request(method: str, path: str, data: dict | None = None) -> dict:
    token = get_access_token()
    url = f"{_BASE}{path}?access_token={token}"
    body = json.dumps(data, ensure_ascii=False).encode() if data else None
    req = urllib.request.Request(url, data=body, method=method)
    req.add_header("Content-Type", "application/json; charset=utf-8")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode())
    except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError) as e:
        logger.warning("微信 API 请求失败 %s %s: %s", method, path, e)
        return {"errcode": -1, "errmsg": str(e)}


def upload_news(articles: list[dict]) -> dict:
    """上传永久图文素材。"""
    return _request("POST", "/material/add_news", {"articles": articles})


def send_mass(articles: dict, is_to_all: bool = True, tag_id: int = 0) -> dict:
    """按条件群发。"""
    body = {
        "filter": {"is_to_all": is_to_all, "tag_id": tag_id},
        "mpnews": {"media_id": articles.get("media_id")},
        "msgtype": "mpnews",
        "send_ignore_reprint": 0,
    }
    return _request("POST", "/message/mass/sendall", body)


def get_followers(next_openid: str = "") -> dict:
    """获取关注者列表（最多 10000 个）。"""
    params = f"/user/get?next_openid={next_openid}" if next_openid else "/user/get"
    return _request("GET", params)


def get_user_info(openid: str) -> dict:
    """获取单个用户信息。"""
    return _request("GET", f"/user/info?openid={openid}")


def batchget_user_info(openid_list: list[str]) -> list[dict]:
    """批量获取用户信息（最多 100 个）。"""
    result = _request("POST", "/user/info/batchget",
                      {"user_list": [{"openid": o, "lang": "zh_CN"} for o in openid_list]})
    return result.get("user_info_list", [])
