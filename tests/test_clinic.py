import json, pytest
from khub.db import Store
from khub.clinic.billing import create_billing, list_billings, pay
from khub.clinic.pharmacy import add_stock, list_inventory, dispense


def test_create_billing():
    store = Store(":memory:")
    items = [{"name": "诊查费", "price": 50, "qty": 1}]
    bid = create_billing(store, 1, 1, items, method="wechat")
    assert bid > 0


def test_list_billings():
    store = Store(":memory:")
    create_billing(store, 1, 100, [{"name": "挂号", "price": 20, "qty": 1}])
    billings = list_billings(store, patient_id=100)
    assert len(billings) == 1


def test_pay():
    store = Store(":memory:")
    bid = create_billing(store, 1, 1, [{"name": "药费", "price": 100, "qty": 1}])
    pay(store, bid, 100)
    b = store.conn.execute("SELECT status FROM billings WHERE id=?", (bid,)).fetchone()
    assert b["status"] == "paid"


def test_add_stock():
    store = Store(":memory:")
    iid = add_stock(store, "桂枝", 500, unit="g", price=0.1)
    assert iid > 0


def test_low_stock():
    store = Store(":memory:")
    add_stock(store, "人参", 50, alert_level=100)
    low = list_inventory(store, low_stock=True)
    assert len(low) >= 1


def test_dispense():
    store = Store(":memory:")
    add_stock(store, "桂枝", 100)
    did = dispense(store, 1, [{"herb": "桂枝", "qty": 30}])
    assert did > 0
