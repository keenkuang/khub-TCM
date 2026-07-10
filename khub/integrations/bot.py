"""企业微信/钉钉机器人消息推送。"""
from __future__ import annotations
import json, logging, os, urllib.request

logger = logging.getLogger("khub.integrations.bot")


def send_wechat(title: str, content: str = "") -> bool:
    """推送到企业微信群机器人。"""
    url = os.environ.get("WECHAT_WEBHOOK", "")
    if not url:
        return False
    data = {"msgtype": "markdown", "markdown": {"content": f"## {title}\n{content}"}}
    return _post(url, data)


def send_dingtalk(title: str, content: str = "") -> bool:
    """推送到钉钉群机器人。"""
    url = os.environ.get("DINGTALK_WEBHOOK", "")
    if not url:
        return False
    data = {"msgtype": "markdown",
            "markdown": {"title": title, "text": f"# {title}\n{content}"}}
    return _post(url, data)


def send_all(title: str, content: str = "") -> dict:
    """推送到所有已配置的机器人。"""
    return {"wechat": send_wechat(title, content),
            "dingtalk": send_dingtalk(title, content)}


def _post(url: str, data: dict) -> bool:
    try:
        req = urllib.request.Request(
            url, data=json.dumps(data).encode(),
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status == 200
    except Exception as e:
        logger.warning("机器人推送失败: %s", e)
        return False
