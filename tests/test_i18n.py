from khub.i18n import t, detect_lang, get_translations


def test_zh():
    assert t("app.name", "zh") == "kHUB 个人知识中枢"


def test_en():
    assert t("app.name", "en") == "kHUB Knowledge Hub"


def test_fallback():
    assert t("unknown.key", "en") == "unknown.key"


def test_detect_zh():
    assert detect_lang("zh-CN,zh;q=0.9") == "zh"


def test_detect_en():
    assert detect_lang("en-US,en;q=0.9") == "en"


def test_detect_default():
    assert detect_lang("") == "zh"


def test_get_translations():
    tr = get_translations("en")
    assert tr["nav.search"] == "Search"
