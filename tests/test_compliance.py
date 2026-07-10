from khub.db import Store
from khub.compliance import run_checklist, generate_report, CHECKS


def test_checklist_structure():
    store = Store(":memory:")
    result = run_checklist(store)
    assert "checklist" in result
    assert "summary" in result
    assert result["summary"]["total"] >= 8


def test_checklist_passed_count():
    store = Store(":memory:")
    result = run_checklist(store)
    passed = result["summary"]["passed"]
    total = result["summary"]["total"]
    assert 0 <= passed <= total


def test_report_format():
    store = Store(":memory:")
    report = generate_report(store)
    assert "合规认证报告" in report
    assert "合规得分" in report


def test_checks_defined():
    assert len(CHECKS) >= 8
    for c in CHECKS:
        assert "id" in c and "title" in c and "check" in c
