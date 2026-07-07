import json

import urllib.request

from khub.llm import (
    NoOpProvider,
    RemoteLLMProvider,
    get_provider,
    register_provider,
)


class _FakeResponse:
    """支持 with 语句、read 返回伪造 chat/completions JSON 的假响应。"""

    def __init__(self, payload: dict):
        self._bytes = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        return self._bytes


class _RecordingFakeOpener:
    """替换 urllib.request.urlopen，记录请求 URL 并返回假响应。"""

    def __init__(self, payload):
        self.payload = payload
        self.last_url = None

    def __call__(self, request, timeout=None):
        self.last_url = request.full_url
        return _FakeResponse(self.payload)


def test_remote_complete_returns_content(monkeypatch):
    fake = _RecordingFakeOpener({"choices": [{"message": {"content": "摘要内容"}}]})
    monkeypatch.setattr(urllib.request, "urlopen", fake)

    provider = RemoteLLMProvider("http://x")
    result = provider.complete("hi")

    assert result == "摘要内容"
    assert fake.last_url.endswith("/v1/chat/completions")


def test_get_provider_env_set_returns_remote(monkeypatch):
    monkeypatch.setenv("KHUB_LLM_URL", "http://127.0.0.1:9999")
    provider = get_provider()
    assert isinstance(provider, RemoteLLMProvider)


def test_get_provider_no_env_returns_noop(monkeypatch):
    monkeypatch.delenv("KHUB_LLM_URL", raising=False)
    provider = get_provider()
    assert isinstance(provider, NoOpProvider)


def test_noop_and_fake_still_work():
    assert isinstance(get_provider("noop"), NoOpProvider)

    class Fake:
        def complete(self, prompt, **kw):
            return "ok"

        def embed(self, text):
            return [0.1]

    register_provider("fake", Fake())
    assert get_provider("fake").complete("x") == "ok"
