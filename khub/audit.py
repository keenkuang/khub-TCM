import time
from typing import Optional


def init_audit(store) -> None:
    """Create the audit_log table if it does not exist."""
    store.conn.execute(
        "CREATE TABLE IF NOT EXISTS audit_log("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, event TEXT, scope TEXT, "
        "patient_id TEXT, doc_id TEXT, actor TEXT, at TEXT)"
    )
    store.conn.commit()


def record(
    store,
    event: str,
    scope: str = "",
    patient_id: Optional[str] = None,
    doc_id: Optional[str] = None,
    actor: str = "system",
) -> None:
    """Insert an audit log entry. Ensures the audit_log table exists."""
    init_audit(store)
    store.conn.execute(
        "INSERT INTO audit_log(event, scope, patient_id, doc_id, actor, at) "
        "VALUES(?,?,?,?,?,?)",
        (
            event,
            scope,
            patient_id,
            doc_id,
            actor,
            time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()),
        ),
    )
    store.conn.commit()


def recent(store, limit: int = 50):
    """Return the most recent audit log entries as a list of dicts."""
    rows = store.conn.execute(
        "SELECT * FROM audit_log ORDER BY id DESC LIMIT ?", (limit,)
    ).fetchall()
    return [dict(r) for r in rows]
