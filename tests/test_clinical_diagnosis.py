from khub.clinical.diagnosis import suggest_formula, check_incompatibility


def test_suggest_offline():
    results = suggest_formula("风寒表证")
    assert len(results) >= 1
    assert results[0]["source"] == "knowledge_base"
    assert all(item["formula"] in ["桂枝汤", "麻黄汤", "荆防败毒散"] for item in results)


def test_suggest_unknown():
    results = suggest_formula("未知证型")
    assert isinstance(results, list)


def test_check_incompatibility():
    warnings = check_incompatibility(["麻黄汤含乌头", "半夏泻心汤"])
    assert len(warnings) >= 1
    assert any("乌头" in w and "半夏" in w for w in warnings)


def test_check_incompatibility_clean():
    warnings = check_incompatibility(["桂枝汤", "麻黄汤"])
    assert len(warnings) == 0
