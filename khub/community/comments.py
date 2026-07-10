"""文章评论 CRUD。"""
from ..db import Store


def add_comment(store: Store, article_id: int, content: str, author_id: int = 0) -> int:
    store.conn.execute("INSERT INTO community_comments (article_id, author_id, content) VALUES (?, ?, ?)",
                       (article_id, author_id, content))
    return store.conn.execute("SELECT last_insert_rowid()").fetchone()[0]


def list_comments(store: Store, article_id: int) -> list[dict]:
    return store.conn.execute(
        "SELECT c.*, u.display_name FROM community_comments c "
        "LEFT JOIN users u ON c.author_id=u.id "
        "WHERE c.article_id=? ORDER BY c.id ASC", (article_id,)).fetchall()
