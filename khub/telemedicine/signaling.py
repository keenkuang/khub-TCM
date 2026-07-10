"""WebRTC 信令服务——房间创建/加入/状态管理。"""
from __future__ import annotations
import secrets
from ..db import Store


def create_room(store: Store, appointment_id: int = 0) -> dict:
    room_id = secrets.token_urlsafe(16)
    store.conn.execute(
        "INSERT INTO telemedicine_sessions (appointment_id, room_id) VALUES (?, ?)",
        (appointment_id or None, room_id))
    return {
        "room_id": room_id,
        "session_id": store.conn.execute(
            "SELECT last_insert_rowid()").fetchone()[0]
    }


def get_room(store: Store, room_id: str) -> dict | None:
    row = store.conn.execute(
        "SELECT * FROM telemedicine_sessions WHERE room_id=?", (room_id,)).fetchone()
    return dict(row) if row else None


def set_offer(store: Store, room_id: str, offer: str):
    store.conn.execute(
        "UPDATE telemedicine_sessions SET offer=?, status='waiting' WHERE room_id=?",
        (offer, room_id))


def set_answer(store: Store, room_id: str, answer: str):
    store.conn.execute(
        "UPDATE telemedicine_sessions SET answer=?, status='in_call', "
        "started_at=datetime('now') WHERE room_id=?",
        (answer, room_id))


def end_call(store: Store, room_id: str):
    store.conn.execute(
        "UPDATE telemedicine_sessions SET status='completed', "
        "ended_at=datetime('now') WHERE room_id=?",
        (room_id,))
