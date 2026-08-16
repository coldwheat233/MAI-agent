"""Vector store — Chroma-backed with hybrid search (BM25 + vector).

Two-tier search:
  1. Vector search via Chroma (semantic similarity)
  2. BM25 keyword search via internal index (exact term matching)
  3. Results merged, deduplicated, scored

Storage: .mai/chroma/ (persisted across sessions)
"""

from __future__ import annotations

import logging
import re
from collections import defaultdict
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)


class _BM25Index:
    """Minimal BM25 keyword search (no external dependency).

    BM25 = term frequency in document × log(inverse document frequency).
    Scores are computed per-term and summed.
    """

    def __init__(self):
        self._docs: list[str] = []     # document texts
        self._ids: list[str] = []       # document IDs
        self._k1 = 1.2                 # term frequency saturation
        self._b = 0.75                 # length normalization

    def add(self, doc_id: str, text: str) -> None:
        self._ids.append(doc_id)
        self._docs.append(text)

    def remove(self, doc_id: str) -> None:
        if doc_id in self._ids:
            idx = self._ids.index(doc_id)
            self._ids.pop(idx)
            self._docs.pop(idx)

    def search(self, query: str, top_k: int = 10) -> list[tuple[str, float]]:
        if not self._docs:
            return []

        # Tokenize — character bigrams for Chinese, word-level for English
        def tokenize(s: str) -> list[str]:
            tokens: list[str] = []
            # Extract Chinese spans → character bigrams
            for ch_span in re.findall(r"[一-鿿]+", s):
                span = ch_span
                # Bigrams: "分布式锁" → ["分布", "布式", "式锁"]
                for i in range(len(span) - 1):
                    tokens.append(span[i:i+2])
                # Also keep the full span for exact matches
                if len(span) >= 2:
                    tokens.append(span)
            # Extract English/word tokens
            for word in re.findall(r"[a-zA-Z0-9]+", s.lower()):
                if len(word) >= 2:
                    tokens.append(word)
            return tokens

        query_tokens = tokenize(query)
        if not query_tokens:
            return []

        doc_tokens_list = [tokenize(d) for d in self._docs]
        avg_len = sum(len(dt) for dt in doc_tokens_list) / max(1, len(doc_tokens_list))

        # IDF
        doc_count = len(self._docs)
        idf: dict[str, float] = {}
        for token in query_tokens:
            df = sum(1 for dt in doc_tokens_list if token in dt)
            idf[token] = (doc_count - df + 0.5) / (df + 0.5) + 1.0

        # Score each document
        scores: list[tuple[str, float]] = []
        for i, doc_tokens in enumerate(doc_tokens_list):
            score = 0.0
            doc_len = len(doc_tokens)
            tf_counter: dict[str, int] = defaultdict(int)
            for t in doc_tokens:
                tf_counter[t] += 1
            for token in set(query_tokens) & set(doc_tokens):
                tf = tf_counter[token]
                numerator = tf * (self._k1 + 1)
                denominator = tf + self._k1 * (1 - self._b + self._b * doc_len / avg_len)
                score += idf[token] * numerator / denominator
            if score > 0:
                scores.append((self._ids[i], score))

        scores.sort(key=lambda x: x[1], reverse=True)
        return scores[:top_k]


class KnowledgeStore:
    """Hybrid search over persisted knowledge.

    Combines:
      - Chroma vector DB for semantic search
      - BM25 index for exact term matching
      - Merged + deduplicated results with normalized scores
    """

    def __init__(
        self,
        persist_dir: str = ".mai/chroma",
        embedding_backend=None,  # Optional[EmbeddingBackend]
    ):
        self.persist_dir = persist_dir
        self._embedding = embedding_backend
        self._chroma: Optional[object] = None
        self._collection: Optional[object] = None
        self._bm25 = _BM25Index()
        self._texts: dict[str, str] = {}      # Local text cache
        self._metas: dict[str, dict] = {}     # Local metadata cache

    async def _ensure_chroma(self):
        """Initialize Chroma. Gracefully degrade to BM25-only if unavailable."""
        if self._chroma is not None:
            return
        if getattr(self, "_chroma_failed", False):
            return  # Already tried and failed — use BM25 only

        try:
            import chromadb
            self._chroma = chromadb.PersistentClient(path=self.persist_dir)

            try:
                self._collection = self._chroma.get_collection("knowledge")
            except Exception:
                dim = self._embedding.dim if self._embedding else 1024
                self._collection = self._chroma.create_collection(
                    "knowledge",
                    metadata={"hnsw:space": "cosine"},
                )
        except ImportError:
            self._chroma_failed = True
            logger.info("chromadb not installed — using BM25-only mode")
        except Exception as exc:
            self._chroma_failed = True
            logger.warning("Chroma init failed (%s) — using BM25-only mode", exc)

    async def add(
        self,
        doc_id: str,
        text: str,
        metadata: Optional[dict[str, Any]] = None,
    ) -> None:
        """Insert or update a knowledge entry."""
        await self._ensure_chroma()

        # Vector embedding + Chroma upsert
        if self._collection is not None:
            if self._embedding:
                vector = (await self._embedding.encode([text]))[0]
            else:
                vector = None
            self._collection.upsert(
                ids=[doc_id],
                documents=[text],
                embeddings=[vector] if vector else None,
                metadatas=[metadata or {}],
            )

        # Local cache
        self._texts[doc_id] = text
        self._metas[doc_id] = metadata or {}

        # Always add to BM25 index (works standalone)
        self._bm25.remove(doc_id)
        self._bm25.add(doc_id, text)

        logger.debug("Knowledge entry added: %s", doc_id)

    async def search(
        self,
        query: str,
        top_k: int = 10,
        alpha: float = 0.7,  # vector weight (0 = pure BM25, 1 = pure vector)
    ) -> list[dict[str, Any]]:
        """Hybrid search: vector + BM25, merged and ranked.

        Args:
            query: Search query text
            top_k: Number of results to return
            alpha: Weight of vector score vs BM25 (0.0 = BM25 only, 1.0 = vector only)

        Returns:
            List of {id, text, score, metadata, sources}
        """
        await self._ensure_chroma()

        # Vector search (only if Chroma + embedding available)
        vector_results: dict[str, float] = {}
        if self._embedding and alpha > 0 and self._collection is not None:
            try:
                query_vec = await self._embedding.encode_query(query)
                chroma_results = self._collection.query(
                    query_embeddings=[query_vec],
                    n_results=top_k * 2,  # Over-fetch for merging
                )
                ids = chroma_results.get("ids", [[]])[0]
                distances = chroma_results.get("distances", [[]])[0]
                docs = chroma_results.get("documents", [[]])[0]
                metas = chroma_results.get("metadatas", [[]])[0] if "metadatas" in chroma_results else [{}] * len(ids)
                for i, doc_id in enumerate(ids):
                    # Convert cosine distance → similarity (Chroma uses cosine distance)
                    sim = 1.0 - distances[i] if i < len(distances) else 0.0
                    vector_results[doc_id] = sim
            except Exception as exc:
                logger.warning("Vector search failed: %s", exc)

        # BM25 search
        bm25_results: dict[str, float] = {}
        if alpha < 1.0:
            bm25_scores = self._bm25.search(query, top_k=top_k * 2)
            max_bm25 = max(s for _, s in bm25_scores) if bm25_scores else 1.0
            bm25_results = {did: s / max_bm25 for did, s in bm25_scores}  # Normalize

        # Merge with weighted scoring
        all_ids = set(vector_results.keys()) | set(bm25_results.keys())
        merged: list[tuple[str, float]] = []
        for doc_id in all_ids:
            v_score = vector_results.get(doc_id, 0.0)
            b_score = bm25_results.get(doc_id, 0.0)
            combined = alpha * v_score + (1 - alpha) * b_score
            merged.append((doc_id, combined))

        merged.sort(key=lambda x: x[1], reverse=True)
        merged = merged[:top_k]

        # Fetch full text for results
        results = []
        for doc_id, score in merged:
            # Try Chroma first, fall back to local cache
            text = self._texts.get(doc_id, "")
            meta = self._metas.get(doc_id, {})
            if not text and self._collection is not None:
                try:
                    chroma_result = self._collection.get(ids=[doc_id])
                    text = chroma_result.get("documents", [""])[0] if chroma_result.get("documents") else ""
                    meta = chroma_result.get("metadatas", [{}])[0] if chroma_result.get("metadatas") else {}
                except Exception:
                    pass
            results.append({
                "id": doc_id,
                "text": text,
                "score": round(score, 4),
                "metadata": meta,
                "sources": {
                    "vector": round(vector_results.get(doc_id, 0), 4),
                    "bm25": round(bm25_results.get(doc_id, 0), 4),
                },
            })

        return results

    async def delete(self, doc_id: str) -> None:
        """Remove a knowledge entry."""
        await self._ensure_chroma()
        if self._collection is not None:
            try:
                self._collection.delete(ids=[doc_id])
            except Exception:
                pass
        self._bm25.remove(doc_id)

    async def count(self) -> int:
        """Total entries in the store."""
        await self._ensure_chroma()
        if self._collection is not None:
            try:
                return self._collection.count()
            except Exception:
                return 0
        return len(self._bm25._ids)


# ── 单例缓存 ─────────────────────────────────────────────

_stores: dict[str, "KnowledgeStore"] = {}


def get_store(persist_dir: str = ".mai/chroma", embedding_backend=None) -> "KnowledgeStore":
    """按 persist_dir 缓存的 KnowledgeStore（保持 BM25 索引跨调用持久）。

    engine._detect_concepts 每次 submit 都会触发，若每次 new 一个 store，BM25 索引
    会随实例一起丢失，边界检测退化为"永远未知"。缓存后 BM25 跨调用累积。
    """
    if persist_dir not in _stores:
        _stores[persist_dir] = KnowledgeStore(
            persist_dir=persist_dir, embedding_backend=embedding_backend,
        )
    return _stores[persist_dir]
