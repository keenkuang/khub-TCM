"""药房管理——库存 + 发药。"""
from __future__ import annotations
import json
from ..db import Store


def add_stock(store: Store, herb_name: str, qty: int, unit: str = "g",
              price: float = 0, alert_level: int = 100) -> int:
    existing = store.conn.execute("SELECT id FROM pharmacy_inventory WHERE herb_name=?", (herb_name,)).fetchone()
    if existing:
        store.conn.execute("UPDATE pharmacy_inventory SET stock=stock+?, price_per_unit=? WHERE id=?",
                           (qty, price, existing["id"]))
        return existing["id"]
    store.conn.execute("INSERT INTO pharmacy_inventory (herb_name, stock, unit, price_per_unit, alert_level) VALUES (?,?,?,?,?)",
                       (herb_name, qty, unit, price, alert_level))
    return store.conn.execute("SELECT last_insert_rowid()").fetchone()[0]


def list_inventory(store: Store, low_stock: bool = False) -> list[dict]:
    if low_stock:
        return store.conn.execute("SELECT * FROM pharmacy_inventory WHERE stock <= alert_level ORDER BY stock ASC").fetchall()
    return store.conn.execute("SELECT * FROM pharmacy_inventory ORDER BY herb_name").fetchall()


def dispense(store: Store, prescription_id: int, items: list[dict]) -> int:
    """发药：扣除库存 + 记录发药。"""
    for item in items:
        store.conn.execute("UPDATE pharmacy_inventory SET stock=stock-? WHERE herb_name=? AND stock>=?",
                           (item.get("qty", 0), item.get("herb", ""), item.get("qty", 0)))
    store.conn.execute("INSERT INTO pharmacy_dispenses (prescription_id, items, status) VALUES (?, ?, 'dispensed')",
                       (prescription_id, json.dumps(items)))
    return store.conn.execute("SELECT last_insert_rowid()").fetchone()[0]
