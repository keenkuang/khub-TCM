"""多租户管理——租户 CRUD + 成员管理 + 当前租户检测。"""
from __future__ import annotations


def create_tenant(store, name: str, slug: str, plan: str = "free") -> int:
    store.conn.execute("INSERT INTO tenants (name, slug, plan) VALUES (?, ?, ?)",
                       (name, slug, plan))
    return store.conn.execute("SELECT last_insert_rowid()").fetchone()[0]


def list_tenants(store) -> list[dict]:
    return store.conn.execute(
        "SELECT * FROM tenants ORDER BY id DESC").fetchall()


def get_tenant(store, tid: int) -> dict | None:
    return store.conn.execute(
        "SELECT * FROM tenants WHERE id=?", (tid,)).fetchone()


def get_tenant_by_slug(store, slug: str) -> dict | None:
    return store.conn.execute(
        "SELECT * FROM tenants WHERE slug=?", (slug,)).fetchone()


def add_member(store, tenant_id: int, user_id: int, role: str = "member"):
    store.conn.execute(
        "INSERT OR IGNORE INTO tenant_members "
        "(tenant_id, user_id, role) VALUES (?, ?, ?)",
        (tenant_id, user_id, role))


def list_members(store, tenant_id: int) -> list[dict]:
    return store.conn.execute(
        "SELECT tm.*, u.username, u.display_name "
        "FROM tenant_members tm "
        "JOIN users u ON tm.user_id = u.id "
        "WHERE tm.tenant_id=?",
        (tenant_id,)).fetchall()


def detect_tenant(store, tenant_header: str = "") -> dict | None:
    """从 X-Tenant-ID 头检测当前租户。"""
    if not tenant_header:
        return None
    if tenant_header.isdigit():
        return get_tenant(store, int(tenant_header))
    return get_tenant_by_slug(store, tenant_header)
