"""多用户鉴权系统测试。"""
import pytest
from khub.db import Store
from khub.auth import hash_password, verify_password, authenticate, create_user
from khub.auth import issue_token, validate_token, revoke_token


def test_hash_and_verify():
    pwd = "test_password_123"
    h = hash_password(pwd)
    assert verify_password(pwd, h) is True
    assert verify_password("wrong", h) is False


def test_different_hashes_for_same_password():
    pwd = "same"
    h1 = hash_password(pwd)
    h2 = hash_password(pwd)
    assert h1 != h2  # 每次 salt 不同


def test_create_and_authenticate():
    store = Store(":memory:")
    uid = create_user(store, "testuser", "mypassword", role="doctor")
    assert uid > 0
    user = authenticate(store, "testuser", "mypassword")
    assert user is not None
    assert user["username"] == "testuser"
    assert user["role"] == "doctor"


def test_authenticate_wrong_password():
    store = Store(":memory:")
    create_user(store, "u1", "correct")
    assert authenticate(store, "u1", "wrong") is None


def test_authenticate_nonexistent():
    store = Store(":memory:")
    assert authenticate(store, "nobody", "pwd") is None


def test_issue_and_validate_token():
    store = Store(":memory:")
    uid = create_user(store, "u1", "pwd")
    token = issue_token(store, uid)
    assert token is not None
    user = validate_token(store, token)
    assert user is not None
    assert user["user_id"] == uid


def test_revoke_token():
    store = Store(":memory:")
    uid = create_user(store, "u1", "pwd")
    token = issue_token(store, uid)
    revoke_token(store, token)
    assert validate_token(store, token) is None


def test_validate_invalid_token():
    store = Store(":memory:")
    assert validate_token(store, "invalid_token_xxx") is None


def test_check_permission_admin():
    from khub.auth import check_permission
    user = {"role": "admin", "user_id": 1}
    assert check_permission(user, "patients", "read") is True
    assert check_permission(user, "any_resource", "delete") is True


def test_check_permission_doctor():
    from khub.auth import check_permission
    user = {"role": "doctor", "user_id": 1}
    assert check_permission(user, "patients", "read") is True
    assert check_permission(user, "patients", "create") is True
    assert check_permission(user, "stats", "read") is True
    assert check_permission(user, "users", "read") is False


def test_check_permission_nurse():
    from khub.auth import check_permission
    user = {"role": "nurse", "user_id": 1}
    assert check_permission(user, "patients", "read") is True
    assert check_permission(user, "patients", "create") is False  # nurse 只有 r
    assert check_permission(user, "appointments", "create") is True
    assert check_permission(user, "exam", "create") is False


def test_check_permission_patient():
    from khub.auth import check_permission
    user = {"role": "patient", "user_id": 1}
    assert check_permission(user, "patients", "read") is True
    assert check_permission(user, "appointments", "create") is True
    assert check_permission(user, "courses", "read") is False
    assert check_permission(user, "exam", "create") is False


def test_check_permission_receptionist():
    from khub.auth import check_permission
    user = {"role": "receptionist", "user_id": 1}
    assert check_permission(user, "appointments", "create") is True
    assert check_permission(user, "patients", "read") is True
    assert check_permission(user, "records", "create") is False


def test_check_permission_no_user():
    from khub.auth import check_permission
    assert check_permission(None, "patients", "read") is False


def test_list_users():
    from khub.auth import list_users, create_user
    store = Store(":memory:")
    create_user(store, "u1", "p1", role="doctor")
    create_user(store, "u2", "p2", role="nurse")
    users = list_users(store)
    assert len(users) == 3  # admin + u1 + u2


def test_update_user_role():
    from khub.auth import update_user_role, create_user
    store = Store(":memory:")
    uid = create_user(store, "u1", "p1", role="doctor")
    update_user_role(store, uid, "nurse")
    row = store.conn.execute("SELECT role FROM users WHERE id=?", (uid,)).fetchone()
    assert row["role"] == "nurse"
