"""集成状态检测。"""
from __future__ import annotations
import os


def check_all() -> list[dict]:
    return [
        check("企业微信机器人", "WECHAT_WEBHOOK", "bool"),
        check("钉钉机器人", "DINGTALK_WEBHOOK", "bool"),
        check("OpenAI/LLM", "KHUB_LLM_URL", "url"),
        check("嵌入模型", "KHUB_EMBEDDING_URL", "url"),
        check("微信公众平台", "WECHAT_APPID", "pair", "WECHAT_SECRET"),
        check("微信公众号 Secret", "WECHAT_SECRET", "pair", "WECHAT_APPID"),
        check("PII 加密", "KHUB_PII_ENCRYPT", "eq", "1"),
        check("API Token", "KHUB_API_TOKEN", "bool"),
    ]


def check(name: str, var: str, check_type: str = "bool",
          pair_var: str = "") -> dict:
    val = os.environ.get(var, "")
    if check_type == "bool":
        ok = bool(val)
    elif check_type == "url":
        ok = val.startswith("http") if val else False
    elif check_type == "pair":
        ok = bool(val) and bool(os.environ.get(pair_var, ""))
    elif check_type == "eq":
        ok = val == "1"
    else:
        ok = False
    return {
        "name": name,
        "env_var": var,
        "configured": ok,
        "value": "***" if ok and check_type != "eq" else "",
    }
