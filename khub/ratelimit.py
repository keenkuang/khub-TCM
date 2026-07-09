"""SQLite 持久化令牌桶限流器。

当请求速率超过阈值时返回 429，重启后状态不丢失。
配置：
  KHUB_RATE_LIMIT_RATE   — 每秒允许的请求数（默认 10）
  KHUB_RATE_LIMIT_BURST  — 突发上限（默认 20）
"""

import os
import time

from .db import Store


class PersistentTokenBucket:
    """基于 Store 的 SQLite 连接的持久化令牌桶。

    使用 store._lock 保证线程安全，令牌状态写入 _TOKENS 表，
    进程重启后从 SQLite 恢复，重启不丢状态。
    """

    def __init__(self, store: Store):
        self.store = store
        self._init_table()

    def _init_table(self):
        self.store.conn.executescript("""
        CREATE TABLE IF NOT EXISTS _TOKENS(
            key TEXT PRIMARY KEY,
            tokens REAL NOT NULL DEFAULT 0,
            last_refill REAL NOT NULL DEFAULT 0
        );
        """)
        self.store.conn.commit()

    def allow(self, key: str, rate: float = 10, burst: float = 20) -> bool:
        """检查 key 对应的请求是否被允许。

        返回 True 表示放行，False 表示限流（应返回 429）。
        当 rate <= 0 时不做限流（始终返回 True）。
        """
        if rate <= 0:
            return True

        with self.store._lock:
            now = time.time()
            cur = self.store.conn

            row = cur.execute(
                "SELECT tokens, last_refill FROM _TOKENS WHERE key=?",
                (key,)).fetchone()

            if row is None:
                tokens = burst
                last_refill = now
                cur.execute(
                    "INSERT INTO _TOKENS(key, tokens, last_refill) VALUES(?,?,?)",
                    (key, tokens, last_refill))
            else:
                tokens = row["tokens"]
                last_refill = row["last_refill"]
                elapsed = now - last_refill
                tokens = min(burst, tokens + elapsed * rate)
                last_refill = now

            if tokens >= 1.0:
                tokens -= 1.0
                allowed = True
            else:
                allowed = False

            cur.execute(
                "UPDATE _TOKENS SET tokens=?, last_refill=? WHERE key=?",
                (tokens, last_refill, key))
            cur.commit()
            return allowed


def make_ratelimit(store: Store) -> PersistentTokenBucket | None:
    """根据环境变量创建限流器（如果启用）。

    KHUB_RATE_LIMIT_RATE 和 KHUB_RATE_LIMIT_BURST 均为可选，
    只有 KHUB_RATE_LIMIT_RATE 被设置时才会启用限流。
    """
    rate = os.environ.get("KHUB_RATE_LIMIT_RATE")
    if rate is None:
        return None
    return PersistentTokenBucket(store)
