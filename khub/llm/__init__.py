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


_PROVIDERS = {"noop": NoOpProvider()}


def register_provider(name: str, provider: LLMProvider):
    _PROVIDERS[name] = provider


def get_provider(name: str = "noop") -> LLMProvider:
    if name not in _PROVIDERS:
        raise KeyError(f"unknown provider: {name}")
    return _PROVIDERS[name]
