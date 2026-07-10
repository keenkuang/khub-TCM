import pytest
from khub.db import Store
from khub.tenants import create_tenant, list_tenants, get_tenant, add_member, list_members, detect_tenant

pytestmark = pytest.mark.smoke


def test_create_tenant():
    store = Store(":memory:")
    tid = create_tenant(store, "测试诊所", "testclinic")
    assert tid > 0


def test_list_tenants():
    store = Store(":memory:")
    create_tenant(store, "诊所A", "clinic-a")
    create_tenant(store, "诊所B", "clinic-b")
    assert len(list_tenants(store)) == 2


def test_get_tenant():
    store = Store(":memory:")
    tid = create_tenant(store, "我的诊所", "myclinic", plan="pro")
    t = get_tenant(store, tid)
    assert t["name"] == "我的诊所"
    assert t["plan"] == "pro"


def test_add_and_list_members():
    store = Store(":memory:")
    tid = create_tenant(store, "诊所", "clinic")
    store.conn.execute(
        "INSERT INTO users (username, password_hash, role) "
        "VALUES ('u1', 'hash', 'doctor'), ('u2', 'hash', 'nurse')").fetchall()
    user1 = store.conn.execute("SELECT id FROM users WHERE username='u1'").fetchone()[0]
    user2 = store.conn.execute("SELECT id FROM users WHERE username='u2'").fetchone()[0]
    add_member(store, tid, user1, role="admin")
    add_member(store, tid, user2)
    members = list_members(store, tid)
    assert len(members) == 2


def test_detect_by_id():
    store = Store(":memory:")
    tid = create_tenant(store, "测试", "test")
    t = detect_tenant(store, str(tid))
    assert t is not None
    assert t["name"] == "测试"
