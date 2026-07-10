"""KG 服务测试——搜索、统计与自动抽取。"""
import pytest
from khub.db import Store
from khub.knowledge.search import search_kg, kg_stats
from khub.knowledge.extractor import extract_from_text, cache_names


def _seed(store: Store):
    from khub.knowledge.seed import seed
    from khub.knowledge.schema import init as kg_init
    kg_init(store.conn)
    seed(store)


class TestSearch:
    def test_search_herbs(self):
        store = Store(":memory:")
        _seed(store)
        results = search_kg(store, "桂枝")
        assert len(results) >= 1
        assert results[0]["entity_type"] == "herb"

    def test_search_formulas(self):
        store = Store(":memory:")
        _seed(store)
        results = search_kg(store, "桂枝汤")
        assert len(results) >= 1
        assert results[0]["entity_type"] == "formula"

    def test_search_syndromes(self):
        store = Store(":memory:")
        _seed(store)
        results = search_kg(store, "风寒")
        assert len(results) >= 1

    def test_search_empty_query(self):
        store = Store(":memory:")
        _seed(store)
        results = search_kg(store, "")
        # 空 LIKE 匹配全部，应该返回大量结果
        assert len(results) > 0

    def test_search_no_match(self):
        store = Store(":memory:")
        _seed(store)
        results = search_kg(store, "XXXXXX不存在的搜索词")
        assert len(results) == 0


class TestStats:
    def test_kg_stats(self):
        store = Store(":memory:")
        _seed(store)
        stats = kg_stats(store)
        assert stats["herbs"] >= 50
        assert stats["formulas"] >= 10
        assert stats["syndromes"] >= 10
        assert stats["methods"] >= 8
        assert stats["relations"] >= 10
        assert stats["total_entities"] >= 70

    def test_kg_stats_empty(self):
        store = Store(":memory:")
        stats = kg_stats(store)
        assert stats["herbs"] == 0
        assert stats["total_entities"] == 0


class TestExtract:
    def test_extract_syndrome(self):
        store = Store(":memory:")
        _seed(store)
        cache_names(store)
        result = extract_from_text(store, "患者风寒表证，使用桂枝汤治疗")
        assert len(result["entities"]["syndromes"]) >= 1
        assert len(result["relations"]) >= 1

    def test_extract_herbs(self):
        store = Store(":memory:")
        _seed(store)
        cache_names(store)
        result = extract_from_text(store, "桂枝、白芍、甘草各9克")
        assert len(result["entities"]["herbs"]) >= 1

    def test_extract_formulas(self):
        store = Store(":memory:")
        _seed(store)
        cache_names(store)
        result = extract_from_text(store, "服用四君子汤加减治疗")
        assert len(result["entities"]["formulas"]) >= 1

    def test_extract_no_match(self):
        store = Store(":memory:")
        _seed(store)
        cache_names(store)
        result = extract_from_text(store, "今天天气很好")
        assert len(result["entities"]["herbs"]) == 0
        assert len(result["entities"]["formulas"]) == 0
        assert len(result["entities"]["syndromes"]) == 0
        assert len(result["relations"]) == 0
