from khub.i18n import t, detect_lang, get_translations, supported_langs


def test_zh():
    assert t("app.name", "zh") == "kHUB 个人知识中枢"


def test_en_default():
    assert t("app.name") == "kHUB Knowledge Hub"


def test_ja():
    assert t("app.name", "ja") == "kHUB ナレッジハブ"


def test_ko():
    assert t("app.name", "ko") == "kHUB 지식 허브"


def test_fallback_to_en():
    # ja 没有 kg.search，应回退到 en
    expected = "Search Knowledge"  # en 的 kg.search
    got = t("kg.search", "ja")
    assert got == expected


def test_fallback_to_key():
    # vi 不存在，所有 key 不存在时返回 key 本身
    result = t("nonexistent_key", "vi")
    assert result == "nonexistent_key"


def test_detect_langs():
    assert detect_lang("zh-CN,zh;q=0.9") == "zh"
    assert detect_lang("en-US,en;q=0.9") == "en"
    assert detect_lang("ja-JP,ja;q=0.9") == "ja"
    assert detect_lang("ko-KR,ko;q=0.9") == "ko"
    assert detect_lang("") == "en"


def test_get_translations():
    tr = get_translations("ja")
    assert tr["nav.search"] == "検索"


def test_supported_langs():
    langs = supported_langs()
    codes = [l["code"] for l in langs]
    assert "en" in codes and "zh" in codes and "ja" in codes and "ko" in codes
