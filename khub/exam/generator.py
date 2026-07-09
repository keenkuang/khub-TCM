import json
from typing import Optional
from .models import Question
from ..llm import LLMProvider, get_provider


def _parse_generated(text: str) -> dict:
    """尽力把 LLM 输出解析为结构化字段。

    依次尝试：JSON → 带标签的多行文本（题干/选项/答案/解析）→ 原样作为题干。
    返回 dict，键可能缺失，调用方负责兜底。
    """
    text = (text or "").strip()
    if not text:
        return {}
    # 1) JSON（模型按提示返回 {"stem":..., "options":[...], "answer":..., "explanation":...}）
    try:
        obj = json.loads(text)
        if isinstance(obj, dict):
            return obj
    except (json.JSONDecodeError, ValueError):
        pass
    # 2) 标签式多行：题干：/选项：/答案：/解析：
    out: dict = {}
    stem_lines, opt_lines, ans_lines, exp_lines = [], [], [], []
    section = "stem"
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("题干") or s.startswith("题目"):
            section = "stem"; continue
        if s.startswith("选项") or s.startswith("选项："):
            section = "options"; continue
        if s.startswith("答案") or s.startswith("正确"):
            section = "answer"; continue
        if s.startswith("解析"):
            section = "explanation"; continue
        if section == "stem":
            stem_lines.append(s)
        elif section == "options":
            opt_lines.append(s)
        elif section == "answer":
            ans_lines.append(s)
        elif section == "explanation":
            exp_lines.append(s)
    if stem_lines:
        out["stem"] = "\n".join(stem_lines).strip()
    if opt_lines:
        opts = [o.split("、", 1)[-1].split(".", 1)[-1].strip()
                for o in opt_lines if o]
        out["options"] = opts
    if ans_lines:
        out["answer"] = ans_lines[0].strip()
    if exp_lines:
        out["explanation"] = "\n".join(exp_lines).strip()
    if out:
        return out
    # 3) 兜底：整段作为题干
    return {"stem": text}


def generate(topic: str, provider: Optional[LLMProvider] = None, source_doc: str = "") -> Question:
    provider = provider or get_provider()

    doc_hint = f"可参考资料「{source_doc}」。" if source_doc else ""
    prompt = (
        f"你是一位中医考试出题专家，请围绕「{topic}」出一道单选题，{doc_hint}"
        f"请以 JSON 返回，字段为：stem（题干）、options（选项字符串数组）、"
        f"answer（正确答案，须是 options 中的一项）、explanation（解析）。"
    )

    text = None
    try:
        text = provider.complete(prompt)
    except Exception:
        text = None

    if not text:
        return Question(kind="mcq", stem=f"[待生成] {topic}",
                        options=[], answer="", explanation="", source_doc=source_doc)

    parsed = _parse_generated(text)
    return Question(
        kind="mcq",
        stem=parsed.get("stem", text),
        options=parsed.get("options", []),
        answer=parsed.get("answer", ""),
        explanation=parsed.get("explanation", ""),
        source_doc=source_doc,
    )
