import pytest
pytestmark = pytest.mark.smoke

import json, pytest
from khub.db import Store
from khub.knowledge.herbs import add_herb, search_herbs, get_herb
from khub.knowledge.formulas import add_formula, formula_similarity
from khub.knowledge.inference import infer

def _seed(store):
    from khub.knowledge.seed import seed
    # 确保知识图谱表已创建
    store.init_schema()
    # 手动建表以防 schema 未加载
    from khub.knowledge.schema import init as kg_init
    kg_init(store.conn)
    seed(store)

def test_herb_crud():
    store = Store(":memory:"); _seed(store)
    h = get_herb(store, "桂枝")
    assert h is not None; assert h["nature"] == "温"
    result = search_herbs(store, nature="温")
    assert len(result) >= 1

def test_herb_search_by_channel():
    store = Store(":memory:"); _seed(store)
    result = search_herbs(store, channel="肺")
    assert len(result) >= 1

def test_formula_crud():
    store = Store(":memory:"); _seed(store)
    from khub.knowledge.formulas import get_formula
    f = get_formula(store, "桂枝汤")
    assert f is not None; assert f["source"] == "伤寒论"

def test_formula_similarity():
    store = Store(":memory:"); _seed(store)
    sim = formula_similarity(store, "桂枝汤", "麻黄汤")
    assert sim > 0  # 都有桂枝、甘草
    sim2 = formula_similarity(store, "桂枝汤", "六味地黄丸")
    assert sim2 == 0.0  # 完全不同

def test_infer():
    store = Store(":memory:"); _seed(store)
    result = infer(store, "风寒表证")
    assert "error" not in result
    assert len(result["treatment_methods"]) >= 1
    assert len(result["recommended_formulas"]) >= 1
    assert len(result["channel_tropism"]) >= 1

def test_infer_unknown():
    store = Store(":memory:"); _seed(store)
    result = infer(store, "未知证型")
    assert "error" in result

def test_syndrome_categories():
    store = Store(":memory:"); _seed(store)
    from khub.knowledge.syndromes import list_syndromes
    all_syds = list_syndromes(store)
    assert len(all_syds) >= 14
    biao = list_syndromes(store, category="表证")
    assert len(biao) >= 2
