"""0.7.2 统一搜索——跨实体检索 + 混合排序。"""
from __future__ import annotations
from .db import Store


def unified_search(store: Store, q: str, type: str = "all", limit: int = 20) -> list[dict]:
    all_results: list[dict] = []
    if type in ("all", "docs"):
        all_results.extend(_search_docs(store, q, limit))
    if type in ("all", "patients"):
        all_results.extend(_search_patients(store, q, limit))
    if type in ("all", "courses"):
        all_results.extend(_search_courses(store, q, limit))
    if type in ("all", "herbs"):
        all_results.extend(_search_herbs(store, q, limit))
    if type in ("all", "formulas"):
        all_results.extend(_search_formulas(store, q, limit))
    if type in ("all", "syndromes"):
        all_results.extend(_search_syndromes(store, q, limit))
    # 混合排序：按 score 降序
    all_results.sort(key=lambda r: r.get("score", 0), reverse=True)
    return all_results[:limit]


def _search_docs(store, q, limit) -> list[dict]:
    try:
        rows = store.conn.execute(
            "SELECT d.canonical_id as id, d.title, d.source_ids, "
            "rank as score FROM docs_fts f JOIN documents d ON f.rowid=d.rowid "
            "WHERE docs_fts MATCH ? ORDER BY rank LIMIT ?",
            (q, limit)).fetchall()
        return [{"entity_type": "document", "id": r["id"], "title": r.get("title", ""),
                 "subtitle": r.get("source_ids", ""), "score": r.get("score", 0) or 0} for r in rows]
    except Exception:
        return []


def _search_patients(store, q, limit) -> list[dict]:
    try:
        from .clinical.patients import list_patients, init as _pinit
        _pinit(store)  # 确保表存在
        rows = store.conn.execute(
            "SELECT id, name FROM patients WHERE name LIKE ? LIMIT ?",
            (f"%{q}%", limit)).fetchall()
        return [{"entity_type": "patient", "id": r["id"], "title": r["name"],
                 "subtitle": f"患者 #{r['id']}", "score": 0.5} for r in rows]
    except Exception:
        return []


def _search_courses(store, q, limit) -> list[dict]:
    try:
        rows = store.conn.execute(
            "SELECT id, name, teacher FROM courses WHERE name LIKE ? OR teacher LIKE ? LIMIT ?",
            (f"%{q}%", f"%{q}%", limit)).fetchall()
        return [{"entity_type": "course", "id": r["id"], "title": r["name"],
                 "subtitle": r["teacher"] or "", "score": 0.4} for r in rows]
    except Exception:
        return []


def _search_herbs(store, q, limit) -> list[dict]:
    try:
        rows = store.conn.execute(
            "SELECT name, pinyin, nature, flavor, channel, category FROM kg_herbs "
            "WHERE name LIKE ? OR pinyin LIKE ? OR 功效 LIKE ? OR category LIKE ? LIMIT ?",
            (f"%{q}%", f"%{q}%", f"%{q}%", f"%{q}%", limit)).fetchall()
        return [{"entity_type": "herb", "id": r["name"], "title": r["name"],
                 "subtitle": f"{r['nature']} {r['flavor']} 归{r['channel']}",
                 "score": 0.3} for r in rows]
    except Exception:
        return []


def _search_formulas(store, q, limit) -> list[dict]:
    try:
        rows = store.conn.execute(
            "SELECT name, source, 功效 FROM kg_formulas "
            "WHERE name LIKE ? OR 功效 LIKE ? OR 主治 LIKE ? LIMIT ?",
            (f"%{q}%", f"%{q}%", f"%{q}%", limit)).fetchall()
        return [{"entity_type": "formula", "id": r["name"], "title": r["name"],
                 "subtitle": f"{r['source']} {r['功效']}",
                 "score": 0.3} for r in rows]
    except Exception:
        return []


def _search_syndromes(store, q, limit) -> list[dict]:
    try:
        rows = store.conn.execute(
            "SELECT name, category, treatment_principle FROM kg_syndromes "
            "WHERE name LIKE ? OR symptoms LIKE ? LIMIT ?",
            (f"%{q}%", f"%{q}%", limit)).fetchall()
        return [{"entity_type": "syndrome", "id": r["name"], "title": r["name"],
                 "subtitle": f"{r['category'] or ''} — {r['treatment_principle'] or ''}",
                 "score": 0.3} for r in rows]
    except Exception:
        return []
