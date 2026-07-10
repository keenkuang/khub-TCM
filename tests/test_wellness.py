import pytest
from khub.vertical.wellness.constitution import assess, get_questions, CONSTITUTIONS


def test_get_questions():
    q = get_questions()
    assert len(q) == 9


def test_assess_pinghe():
    result = assess({"reverse": 5})  # 精力充沛
    assert result["primary_constitution"] == "平和质"


def test_assess_qi():
    result = assess({"qi": 5, "yang": 1})
    assert result["primary_constitution"] == "气虚质"
    assert "四君子汤" in result["advice"]


def test_assess_yang():
    result = assess({"yang": 5})
    assert result["primary_constitution"] == "阳虚质"


def test_assess_all_types():
    for t in ["qi", "yang", "yin", "tan", "shi_re", "xue_yu", "qi_zhi", "te_bing"]:
        result = assess({t: 5})
        assert result["primary_constitution"] in CONSTITUTIONS
