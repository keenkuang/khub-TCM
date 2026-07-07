from khub.llm import LLMProvider, register_provider, get_provider
from khub.exam.generator import generate
from khub.exam.models import Question


class FakeProvider(LLMProvider):
    def complete(self, prompt: str) -> str:
        return "FAKE_Q"

    def embed(self, text: str):
        return []


register_provider("fake_exam", FakeProvider())


def test_generate_uses_real_provider():
    q = generate("少阳证", provider=get_provider("fake_exam"))
    assert isinstance(q, Question)
    assert q.stem == "FAKE_Q"
    assert q.kind == "mcq"
    assert q.source_doc == ""


def test_generate_fallback_default_noop():
    q = generate("少阳证")
    assert isinstance(q, Question)
    assert "少阳证" in q.stem
    assert q.kind == "mcq"


def test_generate_passes_source_doc():
    q = generate("少阳证", provider=get_provider("fake_exam"), source_doc="伤寒论")
    assert q.source_doc == "伤寒论"
    assert q.stem == "FAKE_Q"
