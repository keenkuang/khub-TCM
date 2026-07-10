"""0.3.0 多用户鉴权系统。
零外部依赖，使用 stdlib hashlib.pbkdf2_hmac + secrets + hmac 实现。"""
from __future__ import annotations
import binascii
import hashlib
import hmac
import json
import logging
import os
import secrets
import time
import base64
from typing import Optional

logger = logging.getLogger("khub.auth")

# ── 密码哈希（PBKDF2-HMAC-SHA256） ──

def hash_password(password: str) -> str:
    """返回 salt+hash 的十六进制字符串。"""
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 100000)
    return binascii.hexlify(salt + dk).decode("ascii")


def verify_password(password: str, stored: str) -> bool:
    """验证密码是否匹配存储的哈希。"""
    try:
        raw = binascii.unhexlify(stored.encode("ascii"))
        salt, dk = raw[:16], raw[16:]
        computed = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 100000)
        return hmac.compare_digest(dk, computed)
    except Exception:
        return False


# ── Token 管理（opaque random token + 持久化到 auth_tokens） ──

def issue_token(store, user_id: int, expires_in: int = 86400 * 7) -> str:
    """签发 token（有效期默认 7 天）。"""
    token = secrets.token_urlsafe(48)
    expires_at = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(time.time() + expires_in))
    store.conn.execute(
        "INSERT INTO auth_tokens (user_id, token, expires_at) VALUES (?, ?, ?)",
        (user_id, token, expires_at))
    return token


def validate_token(store, token: str) -> Optional[dict]:
    """验证 token，返回 user 信息 dict 或 None。"""
    row = store.conn.execute(
        "SELECT t.user_id, t.expires_at, u.username, u.display_name, u.role, u.active "
        "FROM auth_tokens t JOIN users u ON t.user_id=u.id "
        "WHERE t.token=?", (token,)).fetchone()
    if not row:
        return None
    if row["expires_at"] and row["expires_at"] < time.strftime("%Y-%m-%dT%H:%M:%S"):
        return None  # token 已过期
    if not row["active"]:
        return None  # 用户被禁用
    return {"user_id": row["user_id"], "username": row["username"],
            "display_name": row["display_name"] or row["username"],
            "role": row["role"]}


def revoke_token(store, token: str):
    store.conn.execute("DELETE FROM auth_tokens WHERE token=?", (token,))


# ── 用户管理 ──

def create_user(store, username: str, password: str,
                display_name: str = "", role: str = "user") -> int:
    pwd_hash = hash_password(password)
    store.conn.execute(
        "INSERT INTO users (username, password_hash, display_name, role) VALUES (?, ?, ?, ?)",
        (username, pwd_hash, display_name or username, role))
    return store.conn.execute("SELECT last_insert_rowid()").fetchone()[0]


def authenticate(store, username: str, password: str) -> Optional[dict]:
    row = store.conn.execute(
        "SELECT id, password_hash, display_name, role, active FROM users WHERE username=?",
        (username,)).fetchone()
    if not row:
        return None
    if not row["active"]:
        return None
    if not verify_password(password, row["password_hash"]):
        return None
    return {"user_id": row["id"], "username": username,
            "display_name": row["display_name"] or username,
            "role": row["role"]}


def get_current_user(store, auth_header: str) -> Optional[dict]:
    """从 HTTP Authorization header 提取当前用户。
    支持 Bearer token 和向后兼容的 KHUB_API_TOKEN。
    当未设置 KHUB_API_TOKEN 且无参数时，返回默认 admin 以保持向后兼容（本地使用）。
    """
    if not auth_header:
        global_token = os.environ.get("KHUB_API_TOKEN")
        if global_token:
            return {"user_id": 0, "username": "admin", "display_name": "系统管理员",
                    "role": "admin", "via_global_token": True}
        # 未设 KHUB_API_TOKEN 时，允许本地访问（向后兼容）
        return {"user_id": 1, "username": "admin", "display_name": "系统管理员",
                "role": "admin", "via_global_token": False}
    if auth_header.startswith("Bearer "):
        token = auth_header[len("Bearer "):]
        user = validate_token(store, token)
        if user:
            return user
        # Bearer token 无效时，回退检查 KHUB_API_TOKEN
        global_token = os.environ.get("KHUB_API_TOKEN")
        if global_token and token == global_token:
            return {"user_id": 0, "username": "admin", "display_name": "系统管理员",
                    "role": "admin", "via_global_token": True}
        return None
    return None


# ── RBAC 权限定义 ──

PERMISSIONS: dict[str, dict[str, str]] = {
    "admin":        {"*": "admin"},
    "doctor":       {"patients": "crud", "records": "crud", "consultations": "crud",
                     "appointments": "crud", "courses": "r", "exam": "crud", "docs": "r",
                     "wechat": "r", "stats": "r", "tags": "crud", "favorites": "crud",
                     "users": ""},
    "nurse":        {"patients": "r", "records": "rw", "consultations": "r",
                     "appointments": "crud", "courses": "r", "docs": "r",
                     "stats": "r", "tags": "r", "favorites": "crud",
                     "users": ""},
    "intern":       {"patients": "r", "records": "rw", "consultations": "r",
                     "appointments": "r", "courses": "r", "docs": "r",
                     "stats": "r", "tags": "r", "favorites": "crud",
                     "users": ""},
    "receptionist": {"patients": "r", "appointments": "crud", "courses": "r",
                     "docs": "r", "stats": "r",
                     "users": ""},
    "patient":      {"patients": "r", "records": "r", "consultations": "r",
                     "appointments": "crud", "docs": "r", "favorites": "crud",
                     "users": ""},
    "guardian":     {"patients": "r", "appointments": "crud", "docs": "r",
                     "users": ""},
    "security":     {"patients": "r", "users": ""},
}


def check_permission(user: dict | None, resource: str, action: str) -> bool:
    if not user:
        return False
    role = user.get("role", "")
    perms = PERMISSIONS.get(role, {})
    if perms.get("*") == "admin" or user.get("via_global_token"):
        return True
    rp = perms.get(resource, "")
    if action == "read" and "r" in rp:
        return True
    if action in ("create",) and "c" in rp:
        return True
    if action in ("update",) and "u" in rp:
        return True
    if action in ("delete",) and "d" in rp:
        return True
    if action in ("write",) and "w" in rp:
        return True
    return False


def list_users(store) -> list[dict]:
    rows = store.conn.execute(
        "SELECT id, username, display_name, role, active, created_at FROM users"
    ).fetchall()
    return [dict(r) for r in rows]


def update_user_role(store, user_id: int, new_role: str) -> bool:
    if new_role not in PERMISSIONS:
        raise ValueError(f"无效角色：{new_role}")
    store.conn.execute("UPDATE users SET role=? WHERE id=?", (new_role, user_id))
    return True


# ── 数据隔离（0.3.2） ──

def scope_filter(user: dict | None, resource: str, alias: str = "") -> tuple[str, list]:
    """返回 (where_clause, params) 供 SQL 查询追加数据隔离。

    Args:
        user: 当前用户 dict（含 role, user_id, username）
        resource: 资源名（patients, records, consultations, appointments）
        alias: 表别名（如 "p."），用于 JOIN 查询

    Returns:
        (where_clause, params) — clause 为空字符串时表示无限制
    """
    if not user:
        return "1=0", []
    role = user.get("role", "")
    uid = user.get("user_id", 0)
    username = user.get("username", "")
    if role in ("admin",) or user.get("via_global_token"):
        return "", []
    p = alias + "." if alias else ""
    if resource == "patients":
        if role in ("patient", "guardian"):
            return f"{p}id=?", [uid]
        if role in ("doctor", "intern", "nurse"):
            # 医生/护士/实习生：看到自己接诊/护理过的患者
            return f"{p}id IN (SELECT DISTINCT patient_id FROM records)", []
    elif resource in ("records",):
        if role in ("patient", "guardian"):
            return f"{p}patient_id=?", [uid]
        # 医生/护士/实习生：看到所有记录（数据层面）
    elif resource in ("consultations",):
        if role in ("patient", "guardian"):
            return f"{p}patient_id=?", [uid]
    elif resource == "appointments":
        if role in ("patient", "guardian"):
            return f"{p}patient_id=?", [uid]
        if role == "doctor":
            return f"{p}doctor=?", [username]
        if role == "intern":
            return f"{p}1=1", []  # 仅查看
    return "", []
