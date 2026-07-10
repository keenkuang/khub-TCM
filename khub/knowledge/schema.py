"""5 张知识图谱表建表函数。"""
def init(conn):
    from ..replication import install_triggers as trg
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS kg_herbs (id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE, pinyin TEXT, nature TEXT, flavor TEXT, channel TEXT, 功效 TEXT, dosage TEXT, 禁忌 TEXT, 毒性 TEXT DEFAULT '', category TEXT, created_at TEXT DEFAULT (datetime('now')));

        CREATE TABLE IF NOT EXISTS kg_formulas (id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE, source TEXT, composition TEXT, 功效 TEXT, 主治 TEXT, 用法 TEXT, 禁忌 TEXT, category TEXT, created_at TEXT DEFAULT (datetime('now')));

        CREATE TABLE IF NOT EXISTS kg_syndromes (id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE, parent_id INTEGER, category TEXT, symptoms TEXT, tongue TEXT, tongue_pulse TEXT, treatment_principle TEXT, created_at TEXT DEFAULT (datetime('now')));

        CREATE TABLE IF NOT EXISTS kg_methods (id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE, description TEXT, category TEXT, created_at TEXT DEFAULT (datetime('now')));

        CREATE TABLE IF NOT EXISTS kg_relations (id INTEGER PRIMARY KEY, source_type TEXT NOT NULL, source_id INTEGER NOT NULL, target_type TEXT NOT NULL, target_id INTEGER NOT NULL, relation_type TEXT NOT NULL, weight REAL DEFAULT 1.0, meta TEXT, UNIQUE(source_type, source_id, target_type, target_id, relation_type));
    """)
    for t in ("kg_herbs","kg_formulas","kg_syndromes","kg_methods","kg_relations"):
        trg(conn, t)
