"""Embedding abstraction — swappable backends.

Backends:
  - LocalTransformer: bge-m3 (1024-dim, Chinese+English, local CPU)
  - APIEmbedding:   DeepSeek/OpenAI-compatible embedding API
  - Fallback:       Auto-try local, fall back to API

Design: The abstract base class lets you swap backends without changing
any consuming code. Local model for privacy/zero-cost, API for quality.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Optional

logger = logging.getLogger(__name__)

DEFAULT_LOCAL_MODEL = "BAAI/bge-m3"


class EmbeddingBackend(ABC):
    """Abstract embedding backend."""

    @abstractmethod
    async def encode(self, texts: list[str]) -> list[list[float]]:
        """Encode texts to vectors."""
        ...

    @abstractmethod
    async def encode_query(self, text: str) -> list[float]:
        """Encode a single query text (may use different instruction prefix)."""
        ...

    @property
    @abstractmethod
    def dim(self) -> int:
        """Embedding dimension."""
        ...

    @property
    @abstractmethod
    def name(self) -> str:
        """Backend identifier."""
        ...


class LocalTransformer(EmbeddingBackend):
    """Local sentence-transformers model — zero API cost, privacy-safe."""

    def __init__(self, model_name: str = DEFAULT_LOCAL_MODEL):
        self._model_name = model_name
        self._model: Optional[object] = None
        self._dim: Optional[int] = None

    async def _lazy_load(self):
        if self._model is not None:
            return
        try:
            from sentence_transformers import SentenceTransformer
            self._model = SentenceTransformer(
                self._model_name,
                device="cpu",
            )
            self._dim = self._model.get_embedding_dimension()
            logger.info("Loaded local embedding model: %s (dim=%d)", self._model_name, self._dim)
        except ImportError:
            raise RuntimeError(
                "sentence-transformers not installed. Run: pip install sentence-transformers"
            )
        except Exception as exc:
            raise RuntimeError(f"Failed to load model {self._model_name}: {exc}")

    async def encode(self, texts: list[str]) -> list[list[float]]:
        await self._lazy_load()
        embeddings = self._model.encode(
            texts,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        return embeddings.tolist()

    async def encode_query(self, text: str) -> list[float]:
        await self._lazy_load()
        embedding = self._model.encode(
            text,
            normalize_embeddings=True,
            show_progress_bar=False,
            prompt="Represent this query for retrieving relevant knowledge: ",
        )
        return embedding.tolist()

    @property
    def dim(self) -> int:
        if self._dim is None:
            return 1024  # bge-m3 default
        return self._dim

    @property
    def name(self) -> str:
        return f"local/{self._model_name}"


class APIEmbedding(EmbeddingBackend):
    """DeepSeek/OpenAI-compatible embedding API."""

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.deepseek.com/v1",
        model: str = "deepseek-embed",
    ):
        import httpx
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self._http = httpx.AsyncClient(timeout=30.0)
        self._dim = 1536

    async def encode(self, texts: list[str]) -> list[list[float]]:
        resp = await self._http.post(
            f"{self.base_url}/embeddings",
            headers={"Authorization": f"Bearer {self.api_key}"},
            json={"input": texts, "model": self.model},
        )
        resp.raise_for_status()
        data = resp.json()
        return [item["embedding"] for item in sorted(data["data"], key=lambda x: x["index"])]

    async def encode_query(self, text: str) -> list[float]:
        results = await self.encode([text])
        return results[0]

    @property
    def dim(self) -> int:
        return self._dim

    @property
    def name(self) -> str:
        return f"api/{self.model}"

    async def close(self):
        await self._http.aclose()


# ── Factory ───────────────────────────────────────────────


def create_embedding(backend: str = "local", **kwargs) -> EmbeddingBackend:
    """Create an embedding backend.

    Args:
        backend: "local" | "api"
        **kwargs: passed to the backend constructor
    """
    if backend == "local":
        return LocalTransformer(**kwargs)
    elif backend == "api":
        return APIEmbedding(**kwargs)
    else:
        raise ValueError(f"Unknown embedding backend: {backend}")
