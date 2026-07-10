from typing import Optional
from ..db import Store
from ..llm import LLMProvider, get_provider
from ..audit import record
from .records import list_records, init as init_records
from .consultations import list_consultations, init as init_consultations
from .patients import get_patient
from ..models import CanonicalDoc

def _build_context(store: Store, patient_id: str):
    """聚合患者及其病历/问诊的真实数据，返回 (patient, recs, cons)。"""
    row = get_patient(store, patient_id)
    patient = dict(row) if row else None
    recs = list_records(store, patient_id)
    cons = list_consultations(store, patient_id)
    return patient, recs, cons

def _patient_label(patient) -> str:
    if not patient:
        return "未知患者"
    name = patient.get("name") or "未知"
    gender = patient.get("gender") or "?"
    born = patient.get("born") or "?"
    return f"{name}({gender},{born})"

def _fallback_text(patient, recs, cons) -> str:
    parts = [f"[孪生体摘要] 患者{_patient_label(patient)}"]
    if recs:
        rec_lines = []
        for i, r in enumerate(recs, 1):
            diag = r.get("diagnosis") or "无"
            pres = r.get("prescription") or "无"
            note = r.get("note") or ""
            line = f"{i}诊断={diag} 处方={pres}"
            if note:
                line += f" 备注={note}"
            rec_lines.append(line)
        parts.append(f"病历{len(recs)}条：" + "；".join(rec_lines))
    else:
        parts.append("病历0条")
    if cons:
        con_lines = []
        for i, c in enumerate(cons, 1):
            cc = c.get("chief_complaint") or "无"
            diff = c.get("differentiation") or "无"
            plan = c.get("plan") or "无"
            line = f"{i}主诉={cc} 辨证={diff} 方案={plan}"
            con_lines.append(line)
        parts.append(f"问诊{len(cons)}条：" + "；".join(con_lines))
    else:
        parts.append("问诊0条")
    return "；".join(parts) + "。"

def build_summary(store: Store, patient_id: str, provider: Optional[LLMProvider] = None) -> str:
    from .records import init as init_records
    from .consultations import init as init_consultations
    init_records(store); init_consultations(store)
    provider = provider or get_provider()
    record(store, "read_twin", scope="twin", patient_id=patient_id)
    patient, recs, cons = _build_context(store, patient_id)

    ctx = (
        f"患者{_patient_label(patient)}；"
        f"病历 {len(recs)} 条："
        + "；".join(
            f"①诊断={r.get('diagnosis') or '无'} 处方={r.get('prescription') or '无'}"
            for r in recs
        )
        + f"；问诊 {len(cons)} 条："
        + "；".join(
            f"①主诉={c.get('chief_complaint') or '无'} 辨证={c.get('differentiation') or '无'} 方案={c.get('plan') or '无'}"
            for c in cons
        )
    )
    prompt = (
        "你是中医临床助手。请根据以下患者数字孪生数据，用简洁专业的中文写一段数字孪生体摘要，"
        f"涵盖诊断、处方、主诉、辨证与治疗方案：\n{ctx}"
    )

    try:
        out = provider.complete(prompt)
    except Exception:
        out = ""
    if out and out.strip():
        return out
    return _fallback_text(patient, recs, cons)

def persist_summary(store: Store, patient_id: str, provider: Optional[LLMProvider] = None) -> str:
    text = build_summary(store, patient_id, provider)
    store.store_document(CanonicalDoc(
        canonical_id=f"twin:{patient_id}", title=f"孪生体:{patient_id}",
        content=text, source="twin", source_id=patient_id, doc_type="twin", origin="hub"))
    return text
