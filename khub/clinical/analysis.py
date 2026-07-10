"""0.4.0 临床知识图谱——证型→方剂关联矩阵、体质演变分析。"""
from __future__ import annotations
from ..db import Store
from .twin_v2 import get_syndrome_evolution


def build_syndrome_formula_matrix(store: Store) -> dict:
    """从 record_struct 统计 (differentiation_norm, formula) 关联频次。"""
    rows = store.conn.execute(
        "SELECT differentiation_norm, formula, count(*) as cnt FROM record_struct "
        "WHERE differentiation_norm!='' AND formula!='' "
        "GROUP BY differentiation_norm, formula ORDER BY cnt DESC"
    ).fetchall()
    matrix: dict[str, dict[str, int]] = {}
    for r in rows:
        key = r["differentiation_norm"]
        matrix.setdefault(key, {})[r["formula"]] = r["cnt"]
    return matrix


def build_syndrome_formula_matrix_for_patient(store: Store, pid: int) -> dict:
    """特定患者的证型→方剂关联。"""
    rows = store.conn.execute("""
        SELECT rs.differentiation_norm, rs.formula, count(*) as cnt
        FROM record_struct rs
        JOIN records r ON rs.source='record' AND rs.source_id=r.id
        WHERE r.patient_id=? AND rs.differentiation_norm!='' AND rs.formula!=''
        GROUP BY rs.differentiation_norm, rs.formula
    """, (pid,)).fetchall()
    matrix: dict[str, dict[str, int]] = {}
    for r in rows:
        matrix.setdefault(r["differentiation_norm"], {})[r["formula"]] = r["cnt"]
    return matrix


def analyze_constitution_evolution(store: Store, pid: int) -> dict:
    """分析患者体质演变趋势。"""
    evolution = get_syndrome_evolution(store, pid)
    if not evolution:
        return {"trend": "insufficient_data"}
    syndromes = [e["differentiation"] for e in evolution if e.get("differentiation")]
    result: dict = {"sequence": syndromes}
    unique = list(dict.fromkeys(syndromes))  # 保持顺序去重
    result["unique"] = unique
    result["count"] = len(unique)
    if len(syndromes) >= 2:
        result["shift"] = f"{syndromes[0]} → {syndromes[-1]}"
        result["direction"] = "changed"
    else:
        result["shift"] = "stable"
        result["direction"] = "stable"
    return result
