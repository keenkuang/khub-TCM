"""方剂 CRUD + 组成解析 + 相似度计算。"""
from __future__ import annotations
import json
from ..db import Store

def add_formula(store, name: str, composition: dict | None = None, source: str = "", **kw) -> int:
    comp_str = json.dumps(composition or {}, ensure_ascii=False)
    store.conn.execute("INSERT INTO kg_formulas (name, source, composition, 功效, 主治, 用法, 禁忌, category) VALUES (?,?,?,?,?,?,?,?)",
                       (name, source, comp_str, kw.get("功效",""), kw.get("主治",""), kw.get("用法",""), kw.get("禁忌",""), kw.get("category","")))
    return store.conn.execute("SELECT last_insert_rowid()").fetchone()[0]

def get_formula(store, name: str) -> dict | None:
    return store.conn.execute("SELECT * FROM kg_formulas WHERE name=?", (name,)).fetchone()

def list_formulas(store, category: str = "") -> list[dict]:
    if category: return store.conn.execute("SELECT * FROM kg_formulas WHERE category=? ORDER BY name", (category,)).fetchall()
    return store.conn.execute("SELECT * FROM kg_formulas ORDER BY name").fetchall()

def formula_similarity(store, name1: str, name2: str) -> float:
    """计算两个方剂的 Jaccard 相似度（基于组成中药集合）。"""
    f1 = get_formula(store, name1); f2 = get_formula(store, name2)
    if not f1 or not f2: return 0.0
    s1 = set(json.loads(f1["composition"] or "{}").keys())
    s2 = set(json.loads(f2["composition"] or "{}").keys())
    if not s1 and not s2: return 1.0
    return len(s1 & s2) / len(s1 | s2)
