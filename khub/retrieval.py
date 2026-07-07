import json
import math
import os
import struct
import sqlite3
import urllib.request
from typing import List, Optional, Tuple

from .db import Store


# ---------------------------------------------------------------------------
# Embedder 抽象：离线默认 + 可接真实模型（本地 llama.cpp / 远端 API）
# ---------------------------------------------------------------------------
class LocalEmbedder:
    """离线字符 n-gram 嵌入（零依赖、确定性、L2 归一化）。作为默认/兜底。"""
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


class RemoteEmbedder:
    """真实嵌入：调用 OpenAI/llama.cpp 风格 /v1/embeddings 端点。

    通过环境变量启用：
      KHUB_EMBEDDING_URL  （必填，如 http://127.0.0.1:8080）
      KHUB_EMBED_DIM      （可选，向量维度；不填则按首次返回推断）
      KHUB_EMBED_API_KEY  （可选）
      KHUB_EMBED_MODEL    （可选，请求体 model 字段）
    """
    def __init__(self, url: str, dim: Optional[int] = None, api_key: str = "",
                 model: str = "", timeout: int = 30):
        self.url = url.rstrip("/")
        self.dim = dim
        self.api_key = api_key
        self.model = model
        self.timeout = timeout

    def embed(self, text: str) -> List[float]:
        payload = {"input": text}
        if self.model:
            payload["model"] = self.model
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(self.url + "/v1/embeddings", data=data, method="POST")
        req.add_header("Content-Type", "application/json")
        if self.api_key:
            req.add_header("Authorization", f"Bearer {self.api_key}")
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            obj = json.loads(resp.read().decode("utf-8"))
        vec = obj["data"][0]["embedding"]
        if self.dim is None:
            self.dim = len(vec)
        return vec


def get_embedder():
    """按环境变量选择嵌入器：有 KHUB_EMBEDDING_URL 则用真实远端，否则离线。"""
    url = os.environ.get("KHUB_EMBEDDING_URL")
    if url:
        dim = int(os.environ["KHUB_EMBED_DIM"]) if os.environ.get("KHUB_EMBED_DIM") else None
        return RemoteEmbedder(url, dim=dim, api_key=os.environ.get("KHUB_EMBED_API_KEY", ""),
                              model=os.environ.get("KHUB_EMBED_MODEL", ""))
    return LocalEmbedder()


# ---------------------------------------------------------------------------
# 向量序列化 / 相似度
# ---------------------------------------------------------------------------
def _pack(vec: List[float]) -> bytes:
    return struct.pack("f" * len(vec), *vec)


def _unpack(blob: bytes) -> List[float]:
    return list(struct.unpack("f" * (len(blob) // 4), blob))


def cosine(a: List[float], b: List[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


# ---------------------------------------------------------------------------
# ANN：sqlite-vec 虚拟表（近似最近邻），不可用时退回暴力余弦
# ---------------------------------------------------------------------------
try:
    import sqlite_vec  # type: ignore
    HAVE_VEC = True
except Exception:  # pragma: no cover - 依赖可选
    sqlite_vec = None  # type: ignore
    HAVE_VEC = False


class Retriever:
    def __init__(self, store: Store, provider=None, model: str = "local", ann: Optional[bool] = None):
        self.store = store
        self.provider = provider or get_embedder()
        self.model = model
        self.ann = (ann if ann is not None
                    else (HAVE_VEC and os.environ.get("KHUB_DISABLE_ANN") != "1"))
        self._vec_table: Optional[str] = None

    # ---- ANN 索引维护 ----
    def _ensure_vec(self, dim: int):
        if self._vec_table:
            return
        name = f"vec_{self.model}"
        conn = self.store.conn
        if HAVE_VEC:
            conn.enable_load_extension(True)
            sqlite_vec.load(conn)
        meta = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone()
        if meta:
            d = conn.execute("SELECT dim FROM vec_meta WHERE name=?", (name,)).fetchone()
            if d and d["dim"] != dim:
                conn.execute(f"DROP TABLE IF EXISTS {name}")
                conn.execute("DELETE FROM vec_meta WHERE name=?", (name,))
                conn.execute(f"CREATE VIRTUAL TABLE {name} USING vec0(embedding float[{dim}] distance=cosine)")
                conn.execute("INSERT INTO vec_meta(name, dim) VALUES(?,?)", (name, dim))
                conn.commit()
        else:
            if HAVE_VEC:
                conn.execute(
                    f"CREATE VIRTUAL TABLE {name} USING vec0(embedding float[{dim}] distance=cosine)")
                conn.execute("CREATE TABLE IF NOT EXISTS vec_meta(name TEXT PRIMARY KEY, dim INTEGER)")
                conn.execute("INSERT INTO vec_meta(name, dim) VALUES(?,?)", (name, dim))
                conn.commit()
        self._vec_table = name

    def index_document(self, doc_id: str, version_id: int, text: str):
        vec = self.provider.embed(text)
        cur = self.store.conn
        cur.execute(
            "DELETE FROM embeddings WHERE doc_id=? AND version_id=? AND model=?",
            (doc_id, version_id, self.model))
        cur.execute(
            "INSERT INTO embeddings(doc_id, version_id, model, vector) VALUES(?,?,?,?)",
            (doc_id, version_id, self.model, sqlite3.Binary(_pack(vec))))
        ann_ok = True
        if self.ann and HAVE_VEC:
            try:
                self._ensure_vec(len(vec))
                name = self._vec_table
                cur.execute(f"DELETE FROM {name} WHERE doc_id=? AND version_id=?", (doc_id, version_id))
                cur.execute(f"INSERT INTO {name}(doc_id, version_id, embedding) VALUES(?,?,?)",
                            (doc_id, version_id, sqlite_vec.serialize_float32(vec)))  # type: ignore
            except Exception:  # ANN 失败不影响主流程
                ann_ok = False
        if ann_ok:
            cur.commit()

    def index_ebook(self, canonical_id: str):
        vers = self.store.get_versions(canonical_id)
        if not vers:
            return
        v = vers[-1]
        self.index_document(canonical_id, v["version_id"], v["content"] or "")

    def search_similar(self, text: str, k: int = 5) -> List[Tuple[str, float]]:
        if self.ann and HAVE_VEC:
            try:
                return self._search_ann(text, k)
            except Exception:  # 退回暴力
                pass
        return self._search_brute(text, k)

    def _search_ann(self, text: str, k: int) -> List[Tuple[str, float]]:
        q = self.provider.embed(text)
        self._ensure_vec(len(q))
        name = self._vec_table
        rows = self.store.conn.execute(
            f"SELECT doc_id, distance FROM {name} "
            f"WHERE embedding MATCH ? ORDER BY distance LIMIT ?",
            (sqlite_vec.serialize_float32(q), k)).fetchall()  # type: ignore
        # 距离转相似度（cosine 距离 = 1 - 余弦），越高越相似
        return [(r["doc_id"], max(0.0, 1.0 - r["distance"])) for r in rows]

    def _search_brute(self, text: str, k: int) -> List[Tuple[str, float]]:
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
