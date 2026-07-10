"""运营路由（appointments/schedules/visits/followup）。"""

from fastapi import APIRouter, Depends, Query
from ..deps import get_store, get_current_user_dep
from ...db import Store


def _safe_int(vals, default=0):
    try:
        return int(vals[0]) if vals else default
    except Exception:
        return default


router = APIRouter(tags=["ops"])


@router.get("/ops/appointments")
async def list_appointments(
    date: str = Query(None),
    patient_id: int = Query(None),
    store: Store = Depends(get_store),
    user: dict = Depends(get_current_user_dep),
):
    from ...ops.store import list_appointments as _list_appointments
    return _list_appointments(store, date, user=user, patient_id=patient_id)


@router.post("/ops/appointments")
async def book_appointment(body: dict, store: Store = Depends(get_store)):
    from ...ops.store import book_appointment as _book_appointment
    aid = _book_appointment(store, body["patient_id"], body["date"], body["doctor"])
    return {"id": aid}


@router.get("/ops/schedules")
async def list_schedules(date: str = Query(None), store: Store = Depends(get_store)):
    from ...ops.store import list_schedules as _list_schedules
    return {"schedules": _list_schedules(store, date)}


@router.post("/ops/schedules")
async def add_schedule(body: dict, store: Store = Depends(get_store)):
    from ...ops.store import add_schedule as _add_schedule
    sid = _add_schedule(store, body["date"], body["doctor"], body["slot"])
    return {"id": sid}


@router.post("/ops/visits")
async def checkin_visit(body: dict, store: Store = Depends(get_store)):
    from ...ops.store import checkin_visit as _checkin_visit
    vid = _checkin_visit(store, body["appointment_id"], body["patient_id"],
                         note=body.get("note", ""))
    return {"id": vid}


@router.get("/clinical/followup")
async def followup_list(patient_id: int = Query(0), store: Store = Depends(get_store)):
    from ...clinical.followup import list_plans
    return {"plans": list_plans(store, patient_id=patient_id)}


@router.get("/clinical/followup/scan")
async def followup_scan(as_of: str = Query(None), store: Store = Depends(get_store)):
    from ...clinical.followup import scan_due
    due = scan_due(store, as_of=as_of)
    return {"due_plans": due}
