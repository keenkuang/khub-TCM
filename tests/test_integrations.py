import os
from khub.integrations.status import check_all


def test_check_all():
    results = check_all()
    assert len(results) >= 8


def test_check_with_env(monkeypatch):
    monkeypatch.setenv("WECHAT_WEBHOOK",
                       "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=test")
    monkeypatch.setenv("KHUB_LLM_URL", "http://localhost:11434")
    results = check_all()
    wechat = [r for r in results if r["name"] == "企业微信机器人"]
    assert len(wechat) >= 1
    assert wechat[0]["configured"] is True
    llm = [r for r in results if r["name"] == "OpenAI/LLM"]
    assert len(llm) >= 1
    assert llm[0]["configured"] is True
