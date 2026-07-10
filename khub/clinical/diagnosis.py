"""0.4.0 AI 辅助辨证——知识库 + LLM 推荐 + 配伍禁忌检查。"""
from __future__ import annotations
from typing import Optional

_SYNDROME_FORMULA_MAP: dict[str, list[str]] = {
    "风寒表证": ["桂枝汤", "麻黄汤", "荆防败毒散"],
    "风热表证": ["银翘散", "桑菊饮"],
    "寒湿证": ["藿香正气散"],
    "湿热证": ["茵陈蒿汤", "甘露消毒丹"],
    "痰湿证": ["二陈汤", "温胆汤"],
    "气滞证": ["柴胡疏肝散"],
    "血瘀证": ["血府逐瘀汤"],
    "气虚证": ["四君子汤", "补中益气汤"],
    "血虚证": ["四物汤", "当归补血汤"],
    "阴虚证": ["六味地黄丸", "一贯煎"],
    "阳虚证": ["金匮肾气丸", "右归丸"],
    "脾虚证": ["参苓白术散"],
    "肾虚证": ["六味地黄丸", "金匮肾气丸"],
    "肝郁证": ["逍遥散", "柴胡疏肝散"],
}


def suggest_formula(syndrome: str, provider=None) -> list[dict]:
    """LLM 或离线知识库推荐方剂。"""
    offline = [{"formula": f, "source": "knowledge_base", "confidence": "medium"}
               for f in _SYNDROME_FORMULA_MAP.get(syndrome, [])]
    if provider is None or not callable(getattr(provider, 'complete', None)):
        return offline
    prompt = f"中医辨证：{syndrome}。推荐 3 个经典方剂并简述理由。"
    try:
        result = provider.complete(prompt) or ""
    except Exception:
        result = ""
    if result:
        return [{"formula": result, "source": "llm", "confidence": "high"}]
    return offline


def check_incompatibility(formulas: list[str]) -> list[str]:
    """方剂配伍禁忌检查（十八反十九畏基础版）。"""
    warnings: list[str] = []
    text = " ".join(formulas)
    pairs = [
        ("乌头", "半夏"), ("乌头", "贝母"), ("乌头", "瓜蒌"),
        ("甘草", "甘遂"), ("甘草", "大戟"), ("甘草", "海藻"),
        ("藜芦", "人参"), ("藜芦", "沙参"), ("藜芦", "玄参"),
        ("川乌", "半夏"), ("草乌", "贝母"),
    ]
    for a, b in pairs:
        if a in text and b in text:
            warnings.append(f"{a} 与 {b} 相反，不宜同用")
    return warnings
