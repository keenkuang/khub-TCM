"""测试 SQLite 持久化令牌桶限流器。"""

import os
import tempfile
import threading
import time

import pytest

from khub.db import Store
from khub.ratelimit import PersistentTokenBucket
pytestmark = pytest.mark.smoke



def _make_bucket(db_path: str = ":memory:") -> PersistentTokenBucket:
    store = Store(path=db_path)
    return PersistentTokenBucket(store)


class TestPersistentTokenBucket:
    def test_allow_under_rate(self):
        """基本放行：速率内请求应全部通过。"""
        bucket = _make_bucket()
        key = "test-client"
        # rate=100, burst=50 — 连续 50 个请求应全部放行
        for _ in range(50):
            assert bucket.allow(key, rate=100, burst=50) is True

    def test_deny_over_rate(self):
        """超过 burst 上限后被限流。"""
        bucket = _make_bucket()
        key = "test-over"
        # burst=10, rate=1 — 放行 10 个后应被限流
        allowed = 0
        for _ in range(20):
            if bucket.allow(key, rate=1, burst=10):
                allowed += 1
        assert allowed == 10

    def test_persistence(self):
        """重启（新实例）不丢令牌状态。"""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        try:
            # 第一轮：消耗部分令牌
            bucket1 = _make_bucket(db_path)
            key = "persist-client"
            for _ in range(5):
                bucket1.allow(key, rate=10, burst=10)
            # 关闭 store，模拟重启
            bucket1.store.close()

            # 第二轮：新实例应恢复剩余令牌
            bucket2 = _make_bucket(db_path)
            # burst=10, 已经用了 5，剩余 token ~5（加上 refill 可能略多）
            # 但 elapsed=0（刚创建的新 store 时间差极小），所以应该还有约 5 个
            # 放行 5 个没问题，第 6 个应该被限流
            allowed = 0
            for _ in range(10):
                if bucket2.allow(key, rate=10, burst=10):
                    allowed += 1
            # 按令牌桶算法，burst=10 已消耗 5，剩下 5 个，应当正好放行 5 个
            assert allowed == 5, f"期望恢复后放行 5 个，实际放行 {allowed}"
        finally:
            try:
                os.unlink(db_path)
            except OSError:
                pass

    def test_disabled(self):
        """rate=0 时放行所有请求。"""
        bucket = _make_bucket()
        key = "disable-client"
        for _ in range(100):
            assert bucket.allow(key, rate=0, burst=0) is True

    def test_thread_safety(self):
        """多线程并发访问不损坏内部状态。"""
        bucket = _make_bucket()
        key = "thread-safe-client"
        errors = []
        lock = threading.Lock()

        def worker(n):
            try:
                for _ in range(50):
                    bucket.allow(key, rate=50, burst=50)
            except Exception as e:
                with lock:
                    errors.append(e)

        threads = [threading.Thread(target=worker, args=(i,))
                   for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"并发访问异常: {errors}"
        # 验证表仍然可读
        row = bucket.store.conn.execute(
            "SELECT tokens FROM _TOKENS WHERE key=?", (key,)).fetchone()
        assert row is not None, "令牌行应存在"
