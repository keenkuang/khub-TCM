"""0.2.7 问诊助手——会话管理 + 多轮 prompt + 离线兜底。"""
from __future__ import annotations

from ..db import Store
from ..crypto import enc, dec
from ..audit import record as _record
from ..llm import get_provider
from ..llm.rag import RAGEngine
from .twin_v2 import build_summary_incremental

_MAX_HISTORY_CHARS = 6000


def start_session(store: Store, pid: int) -> int:
    store.conn.execute(
        "INSERT INTO consult_sessions (patient_id) VALUES (?)", (pid,)
    )
    return store.conn.execute("SELECT last_insert_rowid()").fetchone()[0]


def get_history(store: Store, session_id: int) -> str:
    rows = store.conn.execute(
        "SELECT role, content FROM consult_messages "
        "WHERE session_id=? ORDER BY id ASC", (session_id,)
    ).fetchall()
    parts = []
    chars = 0
    for r in rows:
        content = dec(r["content"]) if isinstance(r["content"], bytes) else r["content"]
        line = f"{r['role']}: {content}"
        chars += len(line)
        if chars > _MAX_HISTORY_CHARS:
            break
        parts.append(line)
    return "\n".join(parts)


def chat(store: Store, session_id: int, user_msg: str) -> str:
    # 写用户消息
    store.conn.execute(
        "INSERT INTO consult_messages (session_id, role, content) "
        "VALUES (?, 'user', ?)", (session_id, enc(user_msg))
    )
    # 获取患者 ID
    row = store.conn.execute(
        "SELECT patient_id FROM consult_sessions WHERE id=?", (session_id,)
    ).fetchone()
    if not row:
        raise ValueError(f"会话 {session_id} 不存在")
    pid = row["patient_id"]
    # 构建 prompt
    summary = build_summary_incremental(store, pid) or "(暂无摘要)"
    history = get_history(store, session_id)
    # RAG 知识片段
    try:
        engine = RAGEngine(store)
        rag_context = engine.search_context(user_msg, k=3, max_chars=1500)
    except Exception:
        rag_context = ""
    rag_part = f"\n参考知识：\n{rag_context}\n\n" if rag_context else ""
    prompt = (
        f"你是一名中医问诊助手。以下是该患者的健康摘要：\n{summary}\n\n"
        f"{rag_part}"
        f"对话历史：\n{history}\n\n"
        f"患者提问：{user_msg}\n\n请以中医思维辨证分析并回复。"
    )
    provider = get_provider()
    try:
        reply = provider.complete(prompt) or _fallback_chat(user_msg)
    except Exception:
        reply = _fallback_chat(user_msg)
    # 写助手回复
    store.conn.execute(
        "INSERT INTO consult_messages (session_id, role, content) "
        "VALUES (?, 'assistant', ?)", (session_id, enc(reply))
    )
    _record(store, "consult_chat", scope=f"session={session_id}")
    return reply


def _fallback_chat(user_msg: str) -> str:
    return (f"（离线助手）收到您的问询：{user_msg[:100]}。请连接 AI 模型获取实时辨证建议，"
            f"或预约医生进行面对面问诊。")
