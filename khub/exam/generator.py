from typing import Optional
from .models import Question
from ..llm import LLMProvider, get_provider


def generate(topic: str, provider: Optional[LLMProvider] = None, source_doc: str = "") -> Question:
    provider = provider or get_provider()

    doc_hint = f"可参考资料「{source_doc}」。" if source_doc else ""
    prompt = (
        f"你是一位中医考试出题专家，请围绕「{topic}」出一道单选题，"
        f"{doc_hint}给出题干、选项、正确答案与解析。"
    )

    try:
        text = provider.complete(prompt)
    except Exception:
        text = None

    if text:
        stem = text
    else:
        stem = f"[待生成] {topic}"

    return Question(kind="mcq", stem=stem,
                    options=[], answer="", explanation="", source_doc=source_doc)
