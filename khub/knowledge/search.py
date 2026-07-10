"""知识图谱搜索——跨实体全文检索 + 混合排序。"""
from __future__ import annotations
from ..db import Store


def search_kg(store: Store, q: str, limit: int = 20) -> list[dict]:
    """跨 herbs/formulas/syndromes 搜索。"""
    results: list[dict] = []
    # 中药
    rows = store.conn.execute(
        "SELECT name as title, category, nature, flavor, channel FROM kg_herbs "
        "WHERE name LIKE ? OR 功效 LIKE ? LIMIT ?",
        (f"%{q}%", f"%{q}%", limit)).fetchall()
    results.extend({"entity_type": "herb", **dict(r)} for r in rows)
    # 方剂
    rows = store.conn.execute(
        "SELECT name as title, source, 功效 as description FROM kg_formulas "
        "WHERE name LIKE ? OR 功效 LIKE ? LIMIT ?",
        (f"%{q}%", f"%{q}%", limit)).fetchall()
    results.extend({"entity_type": "formula", **dict(r)} for r in rows)
    # 证型
    rows = store.conn.execute(
        "SELECT name as title, category, treatment_principle as description FROM kg_syndromes "
        "WHERE name LIKE ? OR symptoms LIKE ? LIMIT ?",
        (f"%{q}%", f"%{q}%", limit)).fetchall()
    results.extend({"entity_type": "syndrome", **dict(r)} for r in rows)
    return results[:limit]


def kg_stats(store: Store) -> dict:
    """KG 统计信息。"""
    herbs = store.conn.execute("SELECT count(*) as c FROM kg_herbs").fetchone()["c"] or 0
    formulas = store.conn.execute("SELECT count(*) as c FROM kg_formulas").fetchone()["c"] or 0
    syndromes = store.conn.execute("SELECT count(*) as c FROM kg_syndromes").fetchone()["c"] or 0
    methods = store.conn.execute("SELECT count(*) as c FROM kg_methods").fetchone()["c"] or 0
    relations = store.conn.execute("SELECT count(*) as c FROM kg_relations").fetchone()["c"] or 0
    return {"herbs": herbs, "formulas": formulas, "syndromes": syndromes,
            "methods": methods, "relations": relations,
            "total_entities": herbs + formulas + syndromes + methods}
