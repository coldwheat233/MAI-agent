"""Knowledge engine — hybrid search + concept boundary detection.

Usage:
    from mai_agent.knowledge import KnowledgeStore, ConceptDetector, create_embedding

    # With local model (recommended for personal use)
    embedding = create_embedding("local")
    store = KnowledgeStore(".mai/chroma", embedding)
    detector = ConceptDetector(store, api_key="sk-...")

    await store.add("dist_lock", "分布式锁: 在分布式系统中...")
    results = await store.search("互斥锁")
    concepts = await detector.extract(text)
    checked = await detector.check_boundary(concepts)
"""

from mai_agent.knowledge.embedding import (
    EmbeddingBackend,
    LocalTransformer,
    APIEmbedding,
    create_embedding,
)
from mai_agent.knowledge.vector_store import KnowledgeStore
from mai_agent.knowledge.concept_detector import (
    ConceptDetector,
    DetectedConcept,
)

__all__ = [
    "EmbeddingBackend",
    "LocalTransformer",
    "APIEmbedding",
    "create_embedding",
    "KnowledgeStore",
    "ConceptDetector",
    "DetectedConcept",
]
