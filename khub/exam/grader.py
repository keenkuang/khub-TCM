from typing import Optional, Tuple
from .models import Question
from ..llm import LLMProvider, get_provider


def grade(q: Question, user_answer: str, provider: Optional[LLMProvider] = None) -> Tuple[float, str]:
    provider = provider or get_provider("noop")
    if q.answer and user_answer.strip() == q.answer.strip():
        return 1.0, "正确"
    if q.answer:
        return 0.0, "需人工/LLM 复核"
    _ = provider.complete("grade")
    return 0.0, "未配置评分器"
