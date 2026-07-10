"""国际化——翻译引擎 + 语言检测（4 语言支持）。"""
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
        "clinic.billing": "计费", "clinic.pharmacy": "药房",
        "kg.title": "知识图谱", "kg.search": "搜索知识",
        "notif.title": "通知", "lang.switch": "语言",
    },
    "en": {
        "app.name": "kHUB Knowledge Hub",
        "nav.search": "Search", "nav.stats": "Stats", "nav.ops": "Operations",
        "nav.course": "Courses", "nav.admin": "Admin", "nav.logout": "Logout",
        "login.title": "kHUB Sign In", "login.username": "Username",
        "login.password": "Password", "login.btn": "Sign In",
        "common.loading": "Loading…", "common.no_data": "No Data",
        "common.error": "Load Failed", "common.save": "Save", "common.cancel": "Cancel",
        "clinic.billing": "Billing", "clinic.pharmacy": "Pharmacy",
        "kg.title": "Knowledge Graph", "kg.search": "Search Knowledge",
        "notif.title": "Notifications", "lang.switch": "Language",
    },
    "ja": {
        "app.name": "kHUB ナレッジハブ",
        "nav.search": "検索", "nav.stats": "統計", "nav.ops": "運営",
        "nav.course": "コース", "nav.admin": "管理", "nav.logout": "ログアウト",
        "login.title": "kHUB ログイン", "login.username": "ユーザー名",
        "login.password": "パスワード", "login.btn": "ログイン",
        "common.loading": "読み込み中…", "common.no_data": "データなし",
        "common.error": "読み込み失敗", "common.save": "保存", "common.cancel": "キャンセル",
        "clinic.billing": "請求", "clinic.pharmacy": "薬局",
        "kg.title": "知識グラフ",
    },
    "ko": {
        "app.name": "kHUB 지식 허브",
        "nav.search": "검색", "nav.stats": "통계", "nav.ops": "운영",
        "nav.course": "과정", "nav.admin": "관리", "nav.logout": "로그아웃",
        "login.title": "kHUB 로그인", "login.username": "사용자명",
        "login.password": "비밀번호", "login.btn": "로그인",
        "common.loading": "로딩 중…", "common.no_data": "데이터 없음",
        "common.error": "로딩 실패", "common.save": "저장", "common.cancel": "취소",
        "clinic.billing": "청구", "clinic.pharmacy": "약국",
        "kg.title": "지식 그래프",
    },
}


def t(key: str, lang: str = "en") -> str:
    langs = [lang, "en", "zh"]
    for l in langs:
        if l in TRANSLATIONS and key in TRANSLATIONS[l]:
            return TRANSLATIONS[l][key]
    return key


def detect_lang(accept_language: str = "") -> str:
    if accept_language.startswith("ja"): return "ja"
    if accept_language.startswith("ko"): return "ko"
    if accept_language.startswith("zh"): return "zh"
    return "en"


def get_translations(lang: str) -> dict:
    return TRANSLATIONS.get(lang, TRANSLATIONS["en"])


def supported_langs() -> list[dict]:
    return [{"code": k, "name": v.get("app.name", k)} for k, v in TRANSLATIONS.items()]
