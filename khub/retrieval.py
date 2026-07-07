import math
import struct
import sqlite3
from typing import List, Optional, Tuple

from .db import Store
from .llm import LLMProvider


class LocalEmbedder:
    """Offline character n-gram embedder (no deps). Deterministic, L2-normalized."""
    def __init__(self, dim: int = 256, n: int = 2):
        self.dim = dim
        self.n = n

    def _grams(self, text: str) -> List[str]:
        text = text or ""
        if not text:
            return [""]
        return [text[i:i + self.n] for i in range(max(0, len(text) - self.n + 1))] or [text]

    def embed(self, text: str) -> List[float]:
        vec = [0.0] * self.dim
        for g in self._grams(text):
            vec[hash(g) % self.dim] += 1.0
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]


def _pack(vec: List[float]) -> bytes:
    return struct.pack("f" * len(vec), *vec)


def _unpack(blob: bytes) -> List[float]:
    return list(struct.unpack("f" * (len(blob) // 4), blob))


def cosine(a: List[float], b: List[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


class Retriever:
    def __init__(self, store: Store, provider: Optional[LLMProvider] = None, model: str = "local"):
        self.store = store
        self.provider = provider or LocalEmbedder()
        self.model = model

    def index_document(self, doc_id: str, version_id: int, text: str):
        vec = self.provider.embed(text)
        cur = self.store.conn
        cur.execute(
            "DELETE FROM embeddings WHERE doc_id=? AND version_id=? AND model=?",
            (doc_id, version_id, self.model))
        cur.execute(
            "INSERT INTO embeddings(doc_id, version_id, model, vector) VALUES(?,?,?,?)",
            (doc_id, version_id, self.model, sqlite3.Binary(_pack(vec))))
        cur.commit()

    def index_ebook(self, canonical_id: str):
        vers = self.store.get_versions(canonical_id)
        if not vers:
            return
        v = vers[-1]
        self.index_document(canonical_id, v["version_id"], v["content"] or "")

    def search_similar(self, text: str, k: int = 5) -> List[Tuple[str, float]]:
        q = self.provider.embed(text)
        rows = self.store.conn.execute(
            "SELECT doc_id, version_id, vector FROM embeddings WHERE model=?",
            (self.model,)).fetchall()
        scored = []
        for r in rows:
            vec = _unpack(r["vector"])
            scored.append((r["doc_id"], cosine(q, vec)))
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:k]
