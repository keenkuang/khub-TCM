from typing import Optional
from .models import Question
from ..llm import LLMProvider, get_provider


def generate(topic: str, provider: Optional[LLMProvider] = None, source_doc: str = "") -> Question:
    provider = provider or get_provider("noop")
    prompt = f"出一道关于「{topic}」的中医考题。"
    text = provider.complete(prompt)
    return Question(kind="mcq", stem=(text or f"[待生成] {topic}"),
                    options=[], answer="", explanation="", source_doc=source_doc)
