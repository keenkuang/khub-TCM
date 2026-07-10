"""国际化——翻译引擎 + 语言检测。"""
from __future__ import annotations

TRANSLATIONS: dict[str, dict[str, str]] = {
    "zh": {
        "app.name": "kHUB 个人知识中枢",
        "nav.search": "搜索", "nav.stats": "统计", "nav.ops": "运营",
        "nav.course": "课程", "nav.admin": "管理", "nav.logout": "注销",
        "login.title": "kHUB 登录", "login.username": "用户名",
        "login.password": "密码", "login.btn": "登录",
        "common.loading": "加载中…", "common.no_data": "暂无数据",
        "common.error": "加载失败", "common.save": "保存", "common.cancel": "取消",
    },
    "en": {
        "app.name": "kHUB Knowledge Hub",
        "nav.search": "Search", "nav.stats": "Stats", "nav.ops": "Operations",
        "nav.course": "Courses", "nav.admin": "Admin", "nav.logout": "Logout",
        "login.title": "kHUB Sign In", "login.username": "Username",
        "login.password": "Password", "login.btn": "Sign In",
        "common.loading": "Loading…", "common.no_data": "No Data",
        "common.error": "Load Failed", "common.save": "Save", "common.cancel": "Cancel",
    },
}


def t(key: str, lang: str = "zh") -> str:
    return TRANSLATIONS.get(lang, {}).get(key, TRANSLATIONS.get("zh", {}).get(key, key))


def detect_lang(accept_language: str = "") -> str:
    if accept_language.startswith("en"):
        return "en"
    return "zh"


def get_translations(lang: str) -> dict:
    return TRANSLATIONS.get(lang, TRANSLATIONS["zh"])
