"""RAG 知识问答引擎。

用法::

    from .llm.rag import RAGEngine
    engine = RAGEngine(store)
    answer, sources = engine.ask("小青龙汤的组成是什么？")

流式版本::

    for event in engine.ask_stream("小青龙汤的组成？"):
        if event["event"] == "token":
            print(event["data"]["token"], end="")
"""

from __future__ import annotations

from typing import Generator, Optional

from ..db import Store
from ..llm import get_provider
from ..retrieval import Retriever

PROMPT_TEMPLATE = """你是一个知识问答助手。请根据以下参考文档，用中文回答用户的问题。

如果参考文档不足以回答，请如实说"资料中未找到相关信息"，不要编造。

参考文档：
{context}

用户问题：{question}

请给出准确、简洁的回答："""


class RAGEngine:
    """RAG 问答引擎：向量检索 → 文档上下文组装 → LLM 生成回答。"""

    def __init__(self, store: Store, retriever: Optional[Retriever] = None,
                 llm=None):
        self.store = store
        self.retriever = retriever or Retriever(store)
        from ..llm import LLMProvider
        self.llm = llm if llm is not None else get_provider()

    def ask(self, question: str, k: int = 5) -> tuple[str, list[dict]]:
        """非流式 RAG 管道。返回 (answer_text, sources_list)。"""
        hits = self.retriever.search_similar(question, k=k)
        sources = self._fetch_sources(hits)
        context = self._assemble_context(sources)
        prompt = self._build_prompt(question, context)
        answer = self.llm.complete(prompt, temperature=0.3)
        return answer, sources

    def ask_stream(self, question: str, k: int = 5) -> Generator[dict, None, None]:
        """流式 RAG 管道，逐事件 yield。

        Events:
            {"event": "sources", "data": {"sources": [...]}}
            {"event": "token",    "data": {"token": "..."}}
            {"event": "done",     "data": {"finish_reason": "stop"}}
            {"event": "error",    "data": {"error": "..."}}
        """
        hits = self.retriever.search_similar(question, k=k)
        sources = self._fetch_sources(hits)
        yield {"event": "sources", "data": {"sources": sources}}

        context = self._assemble_context(sources)
        prompt = self._build_prompt(question, context)
        try:
            for token in self.llm.complete_stream(prompt, temperature=0.3):
                yield {"event": "token", "data": {"token": token}}
        except Exception as exc:
            yield {"event": "error", "data": {"error": str(exc)}}
            return
        yield {"event": "done", "data": {"finish_reason": "stop"}}

    # ── 辅助方法 ──────────────────────────────────────────────────────────

    def _fetch_sources(self, hits: list[tuple[str, float]]) -> list[dict]:
        """将 [(doc_id, score)] 转换为包含标题和摘要的富来源列表。"""
        sources = []
        for doc_id, score in hits:
            doc = self.store.get_document(doc_id)
            vers = self.store.get_versions(doc_id)
            content = vers[-1]["content"] if vers else ""

            # 截取前 200 字作为 snippet（中文）
            snippet = content[:200].strip()
            snippet = " ".join(snippet.split())  # 去空行、去换行

            sources.append({
                "id": doc_id,
                "title": doc["title"] if doc else doc_id,
                "score": round(score, 4),
                "snippet": snippet,
            })
        return sources

    def _assemble_context(self, sources: list[dict], max_chars: int = 6000) -> str:
        """将多篇文档拼成 LLM context 文本。按相似度降序排列，分层截断。"""
        per_doc = max(400, max_chars // max(len(sources), 1))
        parts = []
        for src in sources:
            vers = self.store.get_versions(src["id"])
            content = vers[-1]["content"] if vers else ""
            truncated = content[:per_doc].strip()
            parts.append(
                f"--- 文档：{src['title']} (相似度: {src['score']}) ---\n"
                f"{truncated}"
            )
        return "\n\n".join(parts)

    @staticmethod
    def _build_prompt(question: str, context: str) -> str:
        return PROMPT_TEMPLATE.format(question=question, context=context)
