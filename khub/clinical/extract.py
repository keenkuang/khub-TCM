"""0.2.7 病历/问诊结构化抽取（LLM + 离线词典兜底）。"""
from __future__ import annotations
import re
import json

from ..db import Store
from ..llm import get_provider


# 证型关键词 → 规范证型名映射
_SYNDROME_KEYWORDS = {
    "风寒": "风寒表证", "风热": "风热表证", "寒湿": "寒湿证",
    "湿热": "湿热证", "痰湿": "痰湿证", "气滞": "气滞证",
    "血瘀": "血瘀证", "气虚": "气虚证", "血虚": "血虚证",
    "阴虚": "阴虚证", "阳虚": "阳虚证", "脾虚": "脾虚证",
    "肾虚": "肾虚证", "肝郁": "肝郁证",
}


def extract_structured(store: Store, text: str) -> dict:
    """抽取结构化字段，LLM 路径失败时退词典/正则。"""
    provider = get_provider()
    try:
        result = _llm_extract(provider, text)
        if result and _validate_struct(result):
            return result
    except Exception:
        pass
    return _regex_extract(text)


def _llm_extract(provider, text: str) -> dict:
    prompt = (
        f"从以下中医病历/问诊文本中抽取结构化字段，以 JSON 返回（键："
        f"differentiation_norm, syndrome, formula, method）：\n\n{text[:2000]}"
    )
    raw = provider.complete(prompt) or ""
    if not raw:
        return {}
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    if m:
        try:
            return json.loads(m.group())
        except json.JSONDecodeError:
            return {}
    return {}


def _regex_extract(text: str) -> dict:
    """基于词典/正则的离线兜底抽取。"""
    result: dict[str, str] = {}
    # 证型/辨证：查关键词
    found = _detect_syndrome(text)
    if found:
        result["differentiation_norm"] = found
    # 方剂：查 "方：" "剂：" "处方" 等模式
    fm = re.search(r"(?:方|剂|处方)[：:]\s*(.{2,20})", text)
    if fm:
        result["formula"] = fm.group(1).strip()
    # 治法
    mm = re.search(r"(?:治法|疗法|方案)[：:]\s*(.{2,30})", text)
    if mm:
        result["method"] = mm.group(1).strip()
    return result


def _detect_syndrome(text: str) -> str:
    """从文本检测主要证型。"""
    for kw, name in _SYNDROME_KEYWORDS.items():
        if kw in text:
            return name
    return ""


def _validate_struct(d: dict) -> bool:
    return bool(d.get("differentiation_norm") or d.get("formula") or d.get("method"))


def apply_struct(store: Store, source: str, source_id: int, structured: dict):
    store.conn.execute(
        "INSERT INTO record_struct (source, source_id, differentiation_norm, syndrome, formula, method) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (source, source_id,
         structured.get("differentiation_norm", ""),
         structured.get("syndrome", ""),
         structured.get("formula", ""),
         structured.get("method", ""))
    )
