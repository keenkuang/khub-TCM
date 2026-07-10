"""推理引擎：证型→治法→方剂→中药→归经→禁忌。"""
from __future__ import annotations
import json
from ..db import Store
from . import syndromes, formulas, herbs

def infer(store: Store, syndrome_name: str) -> dict:
    syd = syndromes.get_syndrome(store, syndrome_name)
    if not syd: return {"error": f"证型 '{syndrome_name}' 未收录"}
    relations = store.conn.execute(
        "SELECT * FROM kg_relations WHERE source_type='syndrome' AND source_id=?", (syd["id"],)).fetchall()
    result = {"syndrome": syndrome_name, "category": syd["category"], "treatment_principle": syd["treatment_principle"]}
    methods = []; formula_list = []; herb_set = set(); contraindicated = []
    for r in relations:
        if r["target_type"] == "method":
            row = store.conn.execute("SELECT name FROM kg_methods WHERE id=?", (r["target_id"],)).fetchone()
            if row: methods.append(row["name"])
        elif r["target_type"] == "formula":
            row = store.conn.execute("SELECT name, composition FROM kg_formulas WHERE id=?", (r["target_id"],)).fetchone()
            if row:
                formula_list.append({"name": row["name"], "composition": row["composition"]})
                comp = json.loads(row["composition"] or "{}")
                herb_set.update(comp.keys())
        elif r["relation_type"] == "contraindicates" and r["target_type"] == "herb":
            row = store.conn.execute("SELECT name FROM kg_herbs WHERE id=?", (r["target_id"],)).fetchone()
            if row: contraindicated.append(row["name"])
    channels = set()
    for h in herb_set:
        hr = herbs.get_herb(store, h)
        if hr and hr["channel"]:
            for ch in hr["channel"].split("/"):
                if ch.strip(): channels.add(ch.strip())
    result["treatment_methods"] = methods
    result["recommended_formulas"] = [f["name"] for f in formula_list]
    result["key_herbs"] = list(herb_set)[:15]
    result["channel_tropism"] = list(channels)
    result["contraindicated_herbs"] = contraindicated
    return result
