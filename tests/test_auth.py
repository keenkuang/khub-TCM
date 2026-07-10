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
