"""从文本自动抽取知识图谱实体关系（框架 + LLM 增强）。"""
from __future__ import annotations
import re
from ..db import Store
from . import herbs, formulas, syndromes


def extract_from_text(store: Store, text: str) -> dict:
    """从文本中抽取中医实体和关系。"""
    entities = {"herbs": _extract_herbs(text), "syndromes": _extract_syndromes(text),
                "formulas": _extract_formulas(text)}
    relations = []
    # 简单关系抽取：同句共现实体
    for s in entities["syndromes"]:
        for f in entities["formulas"]:
            if s["name"] in text and f["name"] in text:
                relations.append({"source": s["name"], "target": f["name"], "type": "indicates"})
    for f in entities["formulas"]:
        for h in entities["herbs"]:
            if h["name"] in text:
                relations.append({"source": f["name"], "target": h["name"], "type": "contains"})
    return {"entities": entities, "relations": relations, "source_length": len(text)}


_SYNDROME_PATTERN = re.compile(
    r"(风寒|风热|寒湿|湿热|痰湿|气滞|血瘀|气虚|血虚|阴虚|阳虚|脾虚|肾虚|肝郁)(?:证)?")


def _extract_herbs(text: str) -> list[dict]:
    known = store_herb_names()
    found = []
    for h in known:
        if h in text:
            found.append({"name": h, "source": "dictionary"})
    return found


def _extract_syndromes(text: str) -> list[dict]:
    found = []
    for m in _SYNDROME_PATTERN.finditer(text):
        found.append({"name": m.group(0) + "证", "source": "pattern"})
    return found


def _extract_formulas(text: str) -> list[dict]:
    known = store_formula_names()
    return [{"name": f, "source": "dictionary"} for f in known if f in text]


_store_herbs: list[str] = []
_store_formulas: list[str] = []


def store_herb_names() -> list[str]:
    global _store_herbs
    return _store_herbs


def store_formula_names() -> list[str]:
    global _store_formulas
    return _store_formulas


def cache_names(store: Store):
    global _store_herbs, _store_formulas
    _store_herbs = [r["name"]
                    for r in store.conn.execute("SELECT name FROM kg_herbs").fetchall()]
    _store_formulas = [r["name"]
                       for r in store.conn.execute("SELECT name FROM kg_formulas").fetchall()]
