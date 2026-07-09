from typing import Optional, Tuple
from .models import Question
from ..llm import LLMProvider, get_provider


def grade(q: Question, user_answer: str, provider: Optional[LLMProvider] = None) -> Tuple[float, str]:
    provider = provider or get_provider("noop")
    ans = (user_answer or "").strip()

    if q.answer and ans == q.answer.strip():
        return 1.0, "正确"

    # 尝试让 LLM 复核/评分（NoOp provider 返回空串 → 视为未配置，跳过）。
    verdict = ""
    try:
        if q.answer:
            verdict = provider.complete(
                f"题目标准答案：{q.answer}\n用户作答：{ans}\n"
                f"请判断该作答是否可视为正确，并简要说明。")
        else:
            verdict = provider.complete(
                f"请为以下作答评分（0~1）并说明理由：{ans}")
    except Exception:
        verdict = ""

    if verdict and verdict.strip():
        if q.answer:
            return 0.5, f"需人工/LLM 复核：{verdict.strip()}"
        return 0.5, f"LLM 评分：{verdict.strip()}"
    if q.answer:
        return 0.0, "需人工/LLM 复核"
    return 0.0, "未配置评分器"
