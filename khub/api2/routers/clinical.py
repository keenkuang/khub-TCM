"""临床路由（twin/consult/analysis/tracking/diagnosis/safety/interview/cdss）。"""

from fastapi import APIRouter, Depends, Query
from ..deps import get_store, get_current_user_dep
from ...db import Store


def _safe_int(vals, default=0):
    try:
        return int(vals[0]) if vals else default
    except Exception:
        return default


router = APIRouter(tags=["clinical"])


@router.get("/twin/{pid}")
async def twin_detail(pid: int, store: Store = Depends(get_store)):
    from ...clinical.twin_v2 import get_timeline, get_syndrome_evolution, build_summary_incremental
    summary = build_summary_incremental(store, pid)
    timeline = get_timeline(store, pid)
    evolution = get_syndrome_evolution(store, pid)
    return {"patient_id": pid, "summary": summary,
            "timeline": timeline, "syndrome_evolution": evolution}


@router.get("/clinical/patients")
async def list_patients(store: Store = Depends(get_store), user: dict = Depends(get_current_user_dep)):
    from ...clinical.patients import list_patients as _list_patients
    return _list_patients(store, user=user)


@router.post("/clinical/patients")
async def add_patient(body: dict, store: Store = Depends(get_store)):
    from ...clinical.patients import add_patient as _add_patient
    pid = _add_patient(store, body["id"], body["name"],
                       gender=body.get("gender", ""), born=body.get("born", ""))
    return {"id": pid}


@router.post("/clinical/records")
async def add_record(body: dict, store: Store = Depends(get_store)):
    from ...clinical.records import add_record as _add_record
    rid = _add_record(store, body["patient_id"],
                      diagnosis=body.get("diagnosis", ""),
                      prescription=body.get("prescription", ""),
                      note=body.get("note", ""))
    return {"id": rid}


@router.post("/clinical/consultations")
async def add_consultation(body: dict, store: Store = Depends(get_store)):
    from ...clinical.consultations import add_consultation as _add_consultation
    cid = _add_consultation(store, body["patient_id"],
                            chief_complaint=body.get("chief_complaint", ""),
                            tongue_pulse=body.get("tongue_pulse", ""),
                            differentiation=body.get("differentiation", ""),
                            plan=body.get("plan", ""))
    return {"id": cid}


@router.get("/clinical/consultations")
async def list_consultations(patient_id: int = Query(0), store: Store = Depends(get_store)):
    if patient_id:
        rows = store.conn.execute(
            "SELECT id, patient_id, date, chief_complaint, differentiation, plan "
            "FROM consultations WHERE patient_id=? ORDER BY date DESC",
            (patient_id,)
        ).fetchall()
    else:
        rows = store.conn.execute(
            "SELECT id, patient_id, date, chief_complaint, differentiation "
            "FROM consultations ORDER BY date DESC LIMIT 50"
        ).fetchall()
    return {"consultations": rows}


@router.post("/clinical/twin/{pid}/summarize")
async def twin_summarize(pid: str, store: Store = Depends(get_store)):
    from ...clinical.records import init as init_records
    from ...clinical.consultations import init as init_consultations
    from ...clinical.twin import build_summary
    init_records(store)
    init_consultations(store)
    text = build_summary(store, pid)
    return {"patient_id": pid, "summary": text}


@router.post("/clinical/consult/chat")
async def consult_chat(body: dict, store: Store = Depends(get_store)):
    from ...clinical.consult_chat import start_session, chat
    pid = body.get("patient_id", 0)
    if not pid:
        from fastapi import HTTPException
        raise HTTPException(400, "patient_id required")
    sid = body.get("session_id")
    if not sid:
        sid = start_session(store, pid)
    msg = body.get("message", "")
    if not msg:
        from fastapi import HTTPException
        raise HTTPException(400, "message required")
    reply = chat(store, sid, msg)
    return {"session_id": sid, "reply": reply}


@router.post("/clinical/extract")
async def clinical_extract(body: dict, store: Store = Depends(get_store)):
    from ...clinical.extract import extract_structured, apply_struct
    source = body.get("source", "")
    source_id = body.get("source_id", 0)
    text = body.get("text", "")
    if not source or not source_id:
        from fastapi import HTTPException
        raise HTTPException(400, "source and source_id required")
    if not text:
        if source == "record":
            row = store.conn.execute(
                "SELECT diagnosis, prescription FROM records WHERE id=?", (source_id,)
            ).fetchone()
            if row:
                text = f"{row['diagnosis'] or ''} {row['prescription'] or ''}"
        elif source == "consult":
            row = store.conn.execute(
                "SELECT chief_complaint, differentiation FROM consultations WHERE id=?", (source_id,)
            ).fetchone()
            if row:
                text = f"{row['chief_complaint'] or ''} {row['differentiation'] or ''}"
    if not text:
        from fastapi import HTTPException
        raise HTTPException(404, "source not found or text empty")
    struct = extract_structured(store, text)
    apply_struct(store, source, source_id, struct)
    return {"structured": struct}


@router.get("/clinical/analysis/{pid}/matrix")
async def analysis_matrix(pid: int, store: Store = Depends(get_store)):
    from ...clinical.analysis import build_syndrome_formula_matrix_for_patient
    return {"matrix": build_syndrome_formula_matrix_for_patient(store, pid)}


@router.get("/clinical/analysis/{pid}/evolution")
async def analysis_evolution(pid: int, store: Store = Depends(get_store)):
    from ...clinical.analysis import analyze_constitution_evolution
    return {"evolution": analyze_constitution_evolution(store, pid)}


@router.get("/clinical/tracking/{pid}")
async def tracking_efficacy(pid: int, store: Store = Depends(get_store)):
    from ...clinical.tracking import evaluate_efficacy
    return {"efficacy": evaluate_efficacy(store, pid)}


@router.get("/clinical/trends/{pid}")
async def health_trends(pid: int, store: Store = Depends(get_store)):
    from ...clinical.visualize import get_health_trends
    return {"trends": get_health_trends(store, pid)}


@router.post("/clinical/diagnosis/suggest")
async def diagnosis_suggest(body: dict, store: Store = Depends(get_store)):
    from ...clinical.diagnosis import suggest_formula, check_incompatibility
    from ...llm import get_provider
    syndrome = body.get("syndrome", "")
    formulas = body.get("formulas", [])
    suggestions = suggest_formula(syndrome, provider=get_provider())
    warnings = check_incompatibility(formulas) if formulas else []
    return {"suggestions": suggestions, "incompatibility_warnings": warnings}


@router.post("/api/clinical/safety")
async def clinical_safety(body: dict, store: Store = Depends(get_store)):
    from ...clinical.safety import check_all
    result = check_all(body.get("formulas", []), is_pregnant=body.get("is_pregnant", False))
    return result


@router.post("/api/clinical/interview")
async def clinical_interview(body: dict, store: Store = Depends(get_store)):
    from ...clinical.interview import generate_interview
    return generate_interview(store, body.get("text", ""))


@router.post("/api/clinical/cdss")
async def clinical_cdss(body: dict, store: Store = Depends(get_store)):
    from ...clinical.cdss import evaluate
    from datetime import datetime
    age = datetime.now().year - int(body.get("birth_year", 1990))
    patient_data = {"age": age, "pregnancy": body.get("pregnancy", False),
                    "adherence": body.get("adherence", 1.0), "visit_count": body.get("visit_count", 0)}
    alerts = evaluate(patient_data, diagnosis=body.get("diagnosis", ""), dosage=body.get("dosage", 0))
    return {"alerts": alerts, "count": len(alerts), "patient_data": patient_data}
