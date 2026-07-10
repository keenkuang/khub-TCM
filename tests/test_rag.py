"""RAGEngine 单元测试。mock Retriever + LLMProvider，验证 context 组装与管道。"""

from unittest.mock import Mock, MagicMock, patch
from khub.db import Store
from khub.llm import get_provider, LLMProvider
from khub.llm.rag import RAGEngine, PROMPT_TEMPLATE
from khub.retrieval import Retriever
import pytest
pytestmark = pytest.mark.smoke



def _make_store_with_docs():
    """创建内存 Store 并写入两篇测试文档。"""
    from khub.models import CanonicalDoc
    s = Store()
    s.store_document(CanonicalDoc(
        canonical_id="doc-001", title="方剂学·小青龙汤",
        content="小青龙汤：麻黄、芍药、细辛、干姜、甘草、桂枝、五味子、半夏各三两。",
        source="test", source_id="t/1"))
    s.store_document(CanonicalDoc(
        canonical_id="doc-002", title="伤寒论·太阳病篇",
        content="伤寒表不解，心下有水气，干呕发热而咳。小青龙汤主之。",
        source="test", source_id="t/2"))
    return s


def _make_fake_llm():
    """返回一个 Mock LLMProvider，complete 返回固定回答。"""
    m = MagicMock(spec=LLMProvider)
    m.complete.return_value = "小青龙汤由麻黄、芍药、细辛、干姜、甘草、桂枝、五味子、半夏组成。"
    m.complete_stream.return_value = iter(["小", "青", "龙", "汤"])
    return m


class TestRAGEngineInit:
    def test_init_defaults(self):
        """默认参数：空 store 不抛异常。"""
        s = Store()
        engine = RAGEngine(s)
        assert engine.store is s
        assert engine.retriever is not None
        assert engine.llm is not None

    def test_init_with_explicit_retriever(self):
        s = Store()
        r = Retriever(s)
        engine = RAGEngine(s, retriever=r)
        assert engine.retriever is r


class TestFetchSources:
    def test_empty_hits(self):
        s = _make_store_with_docs()
        engine = RAGEngine(s)
        result = engine._fetch_sources([])
        assert result == []

    def test_single_hit(self):
        s = _make_store_with_docs()
        engine = RAGEngine(s)
        hits = [("doc-001", 0.95)]
        result = engine._fetch_sources(hits)
        assert len(result) == 1
        assert result[0]["id"] == "doc-001"
        assert result[0]["title"] == "方剂学·小青龙汤"
        assert result[0]["score"] == 0.95
        assert "麻黄" in result[0]["snippet"]

    def test_multiple_hits(self):
        s = _make_store_with_docs()
        engine = RAGEngine(s)
        hits = [("doc-001", 0.92), ("doc-002", 0.85)]
        result = engine._fetch_sources(hits)
        assert len(result) == 2
        assert result[0]["id"] == "doc-001"
        assert result[1]["id"] == "doc-002"

    def test_snippet_truncation(self):
        """snippet 截取前 200 字。"""
        s = _make_store_with_docs()
        engine = RAGEngine(s)
        hits = [("doc-001", 0.9)]
        result = engine._fetch_sources(hits)
        assert len(result[0]["snippet"]) <= 200

    def test_missing_doc(self):
        """不存在的文档 id 不崩。"""
        s = _make_store_with_docs()
        engine = RAGEngine(s)
        hits = [("nonexistent", 0.5)]
        result = engine._fetch_sources(hits)
        assert len(result) == 1
        assert result[0]["id"] == "nonexistent"


class TestAssembleContext:
    def test_empty_sources(self):
        s = _make_store_with_docs()
        engine = RAGEngine(s)
        ctx = engine._assemble_context([])
        assert ctx == ""

    def test_single_source(self):
        s = _make_store_with_docs()
        engine = RAGEngine(s)
        hits = [("doc-001", 0.9)]
        sources = engine._fetch_sources(hits)
        ctx = engine._assemble_context(sources)
        assert "方剂学·小青龙汤" in ctx
        assert "麻黄" in ctx
        assert "相似度:" in ctx

    def test_multiple_sources(self):
        s = _make_store_with_docs()
        engine = RAGEngine(s)
        hits = [("doc-001", 0.92), ("doc-002", 0.85)]
        sources = engine._fetch_sources(hits)
        ctx = engine._assemble_context(sources)
        assert "方剂学·小青龙汤" in ctx
        assert "伤寒论" in ctx

    def test_max_chars_honored(self):
        """超长内容应被截断到 max_chars 附近。"""
        s = Store()
        from khub.models import CanonicalDoc
        long = "字" * 10000
        s.store_document(CanonicalDoc(
            canonical_id="long", title="长文档", content=long,
            source="test", source_id="t/l"))
        engine = RAGEngine(s)
        hits = [("long", 0.9)]
        sources = engine._fetch_sources(hits)
        ctx = engine._assemble_context(sources, max_chars=2000)
        assert len(ctx) <= 2500  # 有余量（换行符等）


class TestBuildPrompt:
    def test_prompt_format(self):
        engine = RAGEngine(Store())
        prompt = engine._build_prompt("问题", "上下文")
        assert "问题" in prompt
        assert "上下文" in prompt
        assert "资料中未找到相关信息" in prompt

    def test_prompt_template_roundtrip(self):
        """使用 .replace() 替换后问题/文档含 {} 不崩溃。"""
        question = "小青龙汤的{组成}？"
        context = "--- 文档：方剂学 (0.92) ---\n小青龙汤：{麻黄}..."
        prompt = PROMPT_TEMPLATE.replace("{context}", context).replace("{question}", question)
        assert question in prompt
        assert context in prompt
        # 确保 {} 不被当成 format 占位符解析
        assert "{question}" not in prompt
        assert "{context}" not in prompt


class TestAsk:
    def test_ask_returns_answer_and_sources(self):
        s = _make_store_with_docs()
        llm = _make_fake_llm()
        ret = MagicMock(spec=Retriever)
        ret.search_similar.return_value = [("doc-001", 0.95), ("doc-002", 0.85)]
        engine = RAGEngine(s, retriever=ret, llm=llm)
        answer, sources = engine.ask("小青龙汤的组成？", k=5)
        assert isinstance(answer, str)
        assert "小青龙汤由" in answer
        assert len(sources) == 2
        assert sources[0]["id"] == "doc-001"

    def test_ask_invokes_llm_complete(self):
        s = _make_store_with_docs()
        llm = _make_fake_llm()
        ret = MagicMock(spec=Retriever)
        ret.search_similar.return_value = [("doc-001", 0.9)]
        engine = RAGEngine(s, retriever=ret, llm=llm)
        engine.ask("什么汤？", k=5)
        assert llm.complete.call_count == 1
        prompt_arg = llm.complete.call_args[0][0]
        assert "什么汤？" in prompt_arg

    def test_ask_empty_question(self):
        """空问题应返回空结果。"""
        s = _make_store_with_docs()
        llm = _make_fake_llm()
        engine = RAGEngine(s, llm=llm)
        answer, sources = engine.ask("")
        assert answer == ""
        assert sources == []

    def test_ask_llm_failure(self):
        """LLM 抛异常时返回友好错误消息，不抛到调用方。"""
        s = _make_store_with_docs()
        ret = MagicMock(spec=Retriever)
        ret.search_similar.return_value = [("doc-001", 0.9)]
        bad_llm = MagicMock(spec=LLMProvider)
        bad_llm.complete.side_effect = RuntimeError("API挂了")
        engine = RAGEngine(s, retriever=ret, llm=bad_llm)
        answer, sources = engine.ask("什么汤？", k=5)
        assert "生成失败" in answer
        assert len(sources) == 1
        assert bad_llm.complete.call_count == 1


class TestAskStream:
    def test_stream_events_sequence(self):
        s = _make_store_with_docs()
        llm = _make_fake_llm()
        ret = MagicMock(spec=Retriever)
        ret.search_similar.return_value = [("doc-001", 0.95)]
        engine = RAGEngine(s, retriever=ret, llm=llm)
        events = list(engine.ask_stream("什么汤？", k=5))
        # 事件顺序：sources → token... → done
        assert events[0]["event"] == "sources"
        assert events[-1]["event"] == "done"
        token_events = [e for e in events if e["event"] == "token"]
        assert len(token_events) == 4
        assert token_events[0]["data"]["token"] == "小"

    def test_stream_empty_llm(self):
        """NoOpProvider 的 complete_stream 不 yield token。"""
        s = _make_store_with_docs()
        ret = MagicMock(spec=Retriever)
        ret.search_similar.return_value = [("doc-001", 0.9)]
        from khub.llm import NoOpProvider
        engine = RAGEngine(s, retriever=ret, llm=NoOpProvider())
        events = list(engine.ask_stream("什么汤？", k=5))
        assert events[0]["event"] == "sources"
        assert events[-1]["event"] == "done"
        token_events = [e for e in events if e["event"] == "token"]
        assert len(token_events) == 0

    def test_stream_error_handling(self):
        """LLM complete_stream 抛异常时 yield error 事件。"""
        s = _make_store_with_docs()
        ret = MagicMock(spec=Retriever)
        ret.search_similar.return_value = [("doc-001", 0.9)]
        bad_llm = MagicMock(spec=LLMProvider)
        bad_llm.complete_stream.side_effect = RuntimeError("LLM挂了")
        engine = RAGEngine(s, retriever=ret, llm=bad_llm)
        events = list(engine.ask_stream("什么汤？", k=5))
        assert events[0]["event"] == "sources"
        assert events[-1]["event"] == "error"
        assert "LLM挂了" in events[-1]["data"]["error"]

    def test_stream_retrieval_failure(self):
        """retriever 抛异常时 yield error 事件，不传播。"""
        s = _make_store_with_docs()
        ret = MagicMock(spec=Retriever)
        ret.search_similar.side_effect = RuntimeError("DB挂了")
        engine = RAGEngine(s, retriever=ret)
        events = list(engine.ask_stream("什么汤？", k=5))
        assert events[0]["event"] == "error"
        assert "检索" in events[0]["data"]["error"]

    def test_stream_special_chars(self):
        """问题和文档含 {} 不崩溃。"""
        s = _make_store_with_docs()
        ret = MagicMock(spec=Retriever)
        ret.search_similar.return_value = [("doc-001", 0.9)]
        llm = _make_fake_llm()
        engine = RAGEngine(s, retriever=ret, llm=llm)
        events = list(engine.ask_stream("{hello} {world} {x: y}", k=5))
        assert events[0]["event"] == "sources"
        assert events[-1]["event"] == "done"
