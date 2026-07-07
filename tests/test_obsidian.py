"""Tests for khub.obsidian — Obsidian vault adapter."""

import os
import tempfile

from khub.db import Store
from khub.obsidian import import_vault


def test_import_vault():
    with tempfile.TemporaryDirectory() as tmpdir:
        # --- 准备两篇 .md ---
        # 顶层文件
        top_md = os.path.join(tmpdir, "伤寒论.md")
        with open(top_md, "w", encoding="utf-8") as f:
            f.write("# 伤寒论\n太阳病篇")

        # 子目录文件
        sub_dir = os.path.join(tmpdir, "金匮要略")
        os.makedirs(sub_dir, exist_ok=True)
        sub_md = os.path.join(sub_dir, "百合病.md")
        with open(sub_md, "w", encoding="utf-8") as f:
            f.write("# 金匮要略")

        store = Store(":memory:")

        # --- 首次导入：2 篇新增 ---
        ingested, skipped = import_vault(store, tmpdir)
        assert ingested == 2, f"expected 2 ingested, got {ingested}"
        assert skipped == 0, f"expected 0 skipped, got {skipped}"

        # --- 验证全文搜索 ---
        results = store.search_old("太阳病")
        assert len(results) >= 1, "search should find '太阳病'"
        found = any("伤寒论" in r[1] for r in results)
        assert found, "search result should include 伤寒论"

        # --- 二次导入：幂等，全部跳过 ---
        ingested2, skipped2 = import_vault(store, tmpdir)
        assert ingested2 == 0, f"expected 0 ingested, got {ingested2}"
        assert skipped2 == 2, f"expected 2 skipped, got {skipped2}"

        # --- 修改一篇内容后再次导入：1 ingests, 1 skips ---
        with open(top_md, "w", encoding="utf-8") as f:
            f.write("# 伤寒论\n太阳病篇\n新增一条条文")

        ingested3, skipped3 = import_vault(store, tmpdir)
        assert ingested3 == 1, f"expected 1 ingested, got {ingested3}"
        assert skipped3 == 1, f"expected 1 skipped, got {skipped3}"
