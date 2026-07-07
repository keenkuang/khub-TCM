import json
import os
import urllib.error
import urllib.request
from typing import Optional, Protocol, runtime_checkable


@runtime_checkable
class LLMProvider(Protocol):
    """未来考试/问诊/病历模块依赖的 LLM 抽象。现在只定义接口，不绑定任何厂商。"""

    def complete(self, prompt: str, **kwargs) -> str:
        ...

    def embed(self, text: str) -> list[float]:
        ...


class NoOpProvider:
    """占位实现：未接入真实模型时返回空结果，保证接口可调用、可测试。"""

    def complete(self, prompt: str, **kwargs) -> str:
        return ""

    def embed(self, text: str) -> list[float]:
        return []


class RemoteLLMProvider:
    """真实 LLM 提供器：通过 OpenAI 风格的 /v1/chat/completions 接口调用远程模型。

    仅负责文本补全（complete）。向量嵌入由独立的 RemoteEmbedder 负责，
    本类 embed 仅满足 LLMProvider 协议、返回空列表。
    """

    def __init__(self, url: str, api_key: str = "", model: str = "", timeout: int = 30):
        self.url = url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout

    def complete(self, prompt: str, **kwargs) -> str:
        endpoint = self.url + "/v1/chat/completions"
        body = {
            "model": self.model or "default",
            "messages": [{"role": "user", "content": prompt}],
            "temperature": kwargs.get("temperature", 0.3),
        }
        data = json.dumps(body).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        req = urllib.request.Request(endpoint, data=data, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
        except urllib.error.URLError as exc:
            raise
        except Exception as exc:
            raise
        return str(payload["choices"][0]["message"]["content"])

    def embed(self, text: str) -> list[float]:
        # 向量由独立的 RemoteEmbedder 负责；provider 仅满足协议。
        return []


_PROVIDERS = {"noop": NoOpProvider()}


def register_provider(name: str, provider: LLMProvider):
    _PROVIDERS[name] = provider


def get_provider(name: Optional[str] = None) -> LLMProvider:
    if name is not None and name in _PROVIDERS:
        return _PROVIDERS[name]

    if name is None or name == "default":
        env_url = os.environ.get("KHUB_LLM_URL", "")
        if env_url:
            remote = RemoteLLMProvider(
                url=env_url,
                api_key=os.environ.get("KHUB_LLM_API_KEY", ""),
                model=os.environ.get("KHUB_LLM_MODEL", ""),
            )
            register_provider("remote", remote)
            return remote
        return NoOpProvider()

    raise KeyError(f"unknown provider: {name}")
