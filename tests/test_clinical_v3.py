import pytest
from khub.clinical.safety import check_incompatibility, check_pregnancy, check_dosage, check_all
from khub.clinical.interview import get_questions, generate_interview
from khub.clinical.cdss import evaluate, RULES


def test_incompatibility():
    w = check_incompatibility(["麻黄汤含乌头", "半夏泻心汤"])
    assert len(w) >= 1
    assert any("乌头" in s and "半夏" in s for s in w)


def test_incompatibility_clean():
    assert check_incompatibility(["桂枝汤", "麻黄汤"]) == []


def test_pregnancy_contraindicated():
    w = check_pregnancy(["桃仁承气汤", "红花油"])
    assert len(w) >= 1


def test_dosage():
    w = check_dosage("附子", 20)
    assert len(w) >= 1


def test_dosage_safe():
    assert check_dosage("附子", 9) == []


def test_interview_headache():
    q = get_questions("头痛三天")
    assert len(q) >= 3


def test_interview_generic():
    q = get_questions("腿痛")
    assert len(q) >= 1


def test_cdss_alerts():
    alerts = evaluate({"age": 70, "pregnancy": False, "adherence": 1.0, "visit_count": 3},
                      diagnosis="麻黄汤证", dosage=0)
    assert len(alerts) >= 1
    assert alerts[0]["severity"] == "high"


def test_cdss_no_alerts():
    alerts = evaluate({"age": 30, "pregnancy": False, "adherence": 1.0, "visit_count": 1},
                      diagnosis="桂枝汤证", dosage=0)
    assert len(alerts) == 0
