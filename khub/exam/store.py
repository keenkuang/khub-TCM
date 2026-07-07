import json
import time
from typing import List, Optional
from .models import Question
from ..db import Store


def init(store: Store):
    store.conn.execute("""CREATE TABLE IF NOT EXISTS questions(
        id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT, stem TEXT,
        options TEXT, answer TEXT, explanation TEXT, source_doc TEXT, created_at TEXT)""")
    store.conn.commit()


def add_question(store: Store, q: Question) -> int:
    init(store)
    cur = store.conn.execute(
        "INSERT INTO questions(kind, stem, options, answer, explanation, source_doc, created_at) "
        "VALUES(?,?,?,?,?,?,?)",
        (q.kind, q.stem, json.dumps(q.options, ensure_ascii=False), q.answer,
         q.explanation, q.source_doc, time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())))
    store.conn.commit()
    return cur.lastrowid


def get_question(store: Store, qid: int) -> Optional[Question]:
    r = store.conn.execute("SELECT * FROM questions WHERE id=?", (qid,)).fetchone()
    return _row_to_q(r) if r else None


def list_questions(store: Store, kind: Optional[str] = None) -> List[Question]:
    if kind:
        rows = store.conn.execute("SELECT * FROM questions WHERE kind=? ORDER BY id", (kind,)).fetchall()
    else:
        rows = store.conn.execute("SELECT * FROM questions ORDER BY id").fetchall()
    return [_row_to_q(r) for r in rows]


def _row_to_q(r):
    return Question(id=r["id"], kind=r["kind"], stem=r["stem"],
                    options=json.loads(r["options"] or "[]"), answer=r["answer"],
                    explanation=r["explanation"], source_doc=r["source_doc"])
