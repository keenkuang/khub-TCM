import json
import time
from typing import Optional


def init_audit(store) -> None:
    """Create the audit_log table if it does not exist."""
    store.conn.execute(
        "CREATE TABLE IF NOT EXISTS audit_log("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, event TEXT, scope TEXT, "
        "patient_id TEXT, doc_id TEXT, actor TEXT, at TEXT, details TEXT)"
    )
    store.conn.commit()


def record(
    store,
    event: str,
    scope: str = "",
    patient_id: Optional[str] = None,
    doc_id: Optional[str] = None,
    actor: str = "system",
    details: Optional[dict] = None,
) -> None:
    """Insert an audit log entry. Ensures the audit_log table exists."""
    init_audit(store)
    # 确保 details 列为兼容旧行
    cols = {r["name"] for r in store.conn.execute("PRAGMA table_info(audit_log)")}
    if "details" not in cols:
        store.conn.execute("ALTER TABLE audit_log ADD COLUMN details TEXT")
        store.conn.commit()
    details_json = json.dumps(details, ensure_ascii=False) if details else ""
    store.conn.execute(
        "INSERT INTO audit_log(event, scope, patient_id, doc_id, actor, at, details) "
        "VALUES(?,?,?,?,?,?,?)",
        (
            event,
            scope,
            patient_id,
            doc_id,
            actor,
            time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()),
            details_json,
        ),
    )
    store.conn.commit()


def search_audit(store, event=None, actor=None, since=None, limit=100):
    """Search audit log entries with optional filters."""
    init_audit(store)
    sql = "SELECT * FROM audit_log WHERE 1=1"
    params = []
    if event:
        sql += " AND event=?"
        params.append(event)
    if actor:
        sql += " AND actor=?"
        params.append(actor)
    if since:
        sql += " AND at>=?"
        params.append(since)
    sql += " ORDER BY id DESC LIMIT ?"
    params.append(limit)
    rows = store.conn.execute(sql, params).fetchall()
    return [dict(r) for r in rows]


def recent(store, limit: int = 50):
    """Return the most recent audit log entries as a list of dicts."""
    rows = store.conn.execute(
        "SELECT * FROM audit_log ORDER BY id DESC LIMIT ?", (limit,)
    ).fetchall()
    return [dict(r) for r in rows]
