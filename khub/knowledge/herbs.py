"""中药 CRUD + 归经/性味查询。"""
from __future__ import annotations
from ..db import Store

def add_herb(store: Store, name: str, nature: str = "", flavor: str = "", channel: str = "", category: str = "", **kw) -> int:
    store.conn.execute("INSERT INTO kg_herbs (name, nature, flavor, channel, category, 功效, dosage, 禁忌, 毒性, pinyin) VALUES (?,?,?,?,?,?,?,?,?,?)",
                       (name, nature, flavor, channel, category, kw.get("功效",""), kw.get("dosage",""), kw.get("禁忌",""), kw.get("毒性",""), kw.get("pinyin","")))
    return store.conn.execute("SELECT last_insert_rowid()").fetchone()[0]

def search_herbs(store: Store, channel: str = "", nature: str = "", flavor: str = "", category: str = "") -> list[dict]:
    sql = "SELECT * FROM kg_herbs WHERE 1=1"; params = []
    if channel: sql += " AND channel LIKE ?"; params.append(f"%{channel}%")
    if nature: sql += " AND nature=?"; params.append(nature)
    if flavor: sql += " AND flavor LIKE ?"; params.append(f"%{flavor}%")
    if category: sql += " AND category=?"; params.append(category)
    return store.conn.execute(sql + " ORDER BY name", params).fetchall()

def get_herb(store, name: str) -> dict | None:
    return store.conn.execute("SELECT * FROM kg_herbs WHERE name=?", (name,)).fetchone()
