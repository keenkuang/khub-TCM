import sqlite3
import pytest

def test_fts5_available():
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE VIRTUAL TABLE t USING fts5(x)")
