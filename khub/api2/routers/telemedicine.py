"""远程医疗路由。"""

from fastapi import APIRouter, Depends, Query
from ..deps import get_store
from ...db import Store

router = APIRouter(tags=["telemedicine"])


@router.post("/api/telemedicine/room")
async def create_telemedicine_room(body: dict, store: Store = Depends(get_store)):
    from ...telemedicine import create_room
    result = create_room(store, body.get("appointment_id", 0))
    return result


@router.get("/api/telemedicine/room/{room_id}")
async def get_telemedicine_room(room_id: str, store: Store = Depends(get_store)):
    from ...telemedicine import get_room
    room = get_room(store, room_id)
    if not room:
        from fastapi import HTTPException
        raise HTTPException(404, "room not found")
    return room


@router.post("/api/telemedicine/room/{room_id}/start")
async def start_telemedicine_room(room_id: str, body: dict, store: Store = Depends(get_store)):
    from ...telemedicine import set_offer
    set_offer(store, room_id, body.get("offer", ""))
    return {"status": "ok"}


@router.post("/api/telemedicine/room/{room_id}/end")
async def end_telemedicine_room(room_id: str, store: Store = Depends(get_store)):
    from ...telemedicine import end_call
    end_call(store, room_id)
    return {"status": "ok"}


@router.post("/api/prescriptions")
async def create_prescription(body: dict, store: Store = Depends(get_store)):
    from ...telemedicine import create_prescription as _create_prescription
    pid = _create_prescription(store, body.get("consultation_id", 0),
                                body.get("doctor_id", 0),
                                body.get("patient_id", 0),
                                body.get("items", []))
    return {"prescription_id": pid}


@router.get("/api/prescriptions")
async def list_prescriptions(patient_id: int = Query(0), doctor_id: int = Query(0),
                              store: Store = Depends(get_store)):
    from ...telemedicine import list_prescriptions as _list_prescriptions
    return {"prescriptions": _list_prescriptions(store, patient_id, doctor_id)}


@router.get("/api/prescriptions/{prescription_id}")
async def get_prescription(prescription_id: int, store: Store = Depends(get_store)):
    if not prescription_id:
        from fastapi import HTTPException
        raise HTTPException(400, "invalid id")
    from ...telemedicine import get_prescription as _get_prescription
    presc = _get_prescription(store, prescription_id)
    if not presc:
        from fastapi import HTTPException
        raise HTTPException(404, "not found")
    return presc
