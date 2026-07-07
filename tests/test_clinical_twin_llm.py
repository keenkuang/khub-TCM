import pytest
from khub.db import Store
from khub.llm import LLMProvider, register_provider, get_provider
from khub.clinical import patients, records, consultations
from khub.clinical.twin import build_summary


class FakeProvider:
    """complete 直接返回固定字符串，用于覆盖真实 provider 路径。"""

    def complete(self, prompt: str, **kwargs) -> str:
        return "FAKE_SUMMARY"

    def embed(self, text: str) -> list:
        return []


@pytest.fixture
def store():
    s = Store(":memory:")
    return s


def _seed(store):
    pid = "p1"
    patients.add_patient(store, pid, name="张三", gender="男", born="1980")
    records.add_record(
        store, pid,
        diagnosis="太阳病", prescription="桂枝汤", note="发热恶寒")
    consultations.add_consultation(
        store, pid,
        chief_complaint="发热", tongue_pulse="脉浮",
        differentiation="表虚", plan="调和营卫")
    return pid


def test_build_summary_uses_real_provider(store):
    register_provider("fake_twin", FakeProvider())
    pid = _seed(store)
    out = build_summary(store, pid, provider=get_provider("fake_twin"))
    assert "FAKE_SUMMARY" in out


def test_build_summary_fallback_aggregates_real_data(store):
    pid = _seed(store)
    # 默认 get_provider() 无 KHUB_LLM_URL 时为 NoOpProvider，complete 返回 "" -> 走兜底模板
    out = build_summary(store, pid)
    assert isinstance(out, str)
    assert out  # 非空
    assert "张三" in out
    assert "太阳病" in out        # 诊断文本确实被聚合
    assert "桂枝汤" in out        # 处方文本确实被聚合
    assert "发热" in out          # 主诉
    assert "表虚" in out          # 辨证
    assert "FAKE_SUMMARY" not in out


def test_build_summary_fallback_without_data(store):
    pid = patients.add_patient(store, "p2", name="李四", gender="女", born="1990")
    out = build_summary(store, pid)
    assert "李四" in out
    assert "病历0条" in out
