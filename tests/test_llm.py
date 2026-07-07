from khub.llm import NoOpProvider, get_provider, register_provider


def test_noop_provider_interface():
    p = get_provider("noop")
    assert isinstance(p, NoOpProvider)
    assert p.complete("anything") == ""
    assert p.embed("anything") == []


def test_register_and_get_provider():
    class Fake:
        def complete(self, prompt, **kw): return "ok"
        def embed(self, text): return [0.1]

    register_provider("fake", Fake())
    assert get_provider("fake").complete("x") == "ok"


def test_unknown_provider_raises():
    try:
        get_provider("nope")
        assert False
    except KeyError:
        pass
