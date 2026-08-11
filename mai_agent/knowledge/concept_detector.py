"""Concept boundary detector — LLM-powered unknown concept identification.

Three-stage pipeline:
  1. Extract named entities and technical terms from text
  2. Hybrid search (vector + BM25) against knowledge store → known or unknown?
  3. For unknowns: assess complexity → auto-absorb (simple) or queue for review (complex)

The LLM is the final judge — vector search narrows the candidates, LLM decides.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Optional

from mai_agent.llm.client import LLMClient
from mai_agent.knowledge.vector_store import KnowledgeStore

logger = logging.getLogger(__name__)


@dataclass
class DetectedConcept:
    term: str
    context: str = ""              # Where it was found
    is_known: bool = False          # In knowledge boundary?
    complexity: str = "low"         # low | medium | high
    summary: str = ""               # Brief explanation (if known)
    search_results: list = field(default_factory=list)  # If unknown, search snippets
    action: str = "ignore"          # auto_absorb | manual_review | ignore


EXTRACT_PROMPT = """You are a technical concept extractor. From the given text, extract ALL named technical concepts.

A "concept" can be:
  - A framework, library, or tool (e.g., FastAPI, Redis, LangGraph)
  - A technical term or pattern (e.g., distributed lock, cold-hot separation, KV cache)
  - An algorithm or data structure (e.g., B-tree, RAFT consensus)
  - A protocol or standard (e.g., OAuth2, WebSocket, gRPC)

For each concept, provide:
  - term: the exact name
  - context: the sentence or phrase where it appears
  - complexity: "low" (one-line definition suffices), "medium" (needs explanation + example), "high" (requires deep study)

Output ONLY a JSON array. No other text.
Example: [{"term": "Redis", "context": "we use Redis for caching", "complexity": "low"}]
"""

JUDGE_PROMPT = """You are judging whether two pieces of text refer to the SAME technical concept.

Query concept: {query_term} — {query_context}
Candidate match: {candidate_text}
Similarity score: {score}

Are these the same concept? Answer ONLY "yes" or "no".
"""


class ConceptDetector:
    """LLM-driven concept boundary detection."""

    def __init__(
        self,
        knowledge_store: KnowledgeStore,
        llm_client: Optional[LLMClient] = None,
        api_key: str = "",
        base_url: str = "https://api.deepseek.com/v1",
        model: str = "deepseek-v4-pro",
    ):
        self.store = knowledge_store
        self.llm = llm_client or LLMClient(api_key=api_key, base_url=base_url, model=model)

    async def extract(self, text: str) -> list[DetectedConcept]:
        """Extract technical concepts from text via LLM."""
        if not text.strip():
            return []

        try:
            response = await self.llm.chat(
                messages=[
                    {"role": "system", "content": EXTRACT_PROMPT},
                    {"role": "user", "content": text[:8000]},
                ],
                temperature=0.0,
                max_tokens=1024,
            )
            concepts = json.loads(response.content or "[]")
        except (json.JSONDecodeError, Exception) as exc:
            logger.warning("Concept extraction failed: %s", exc)
            return []

        results = []
        for c in concepts:
            results.append(DetectedConcept(
                term=c.get("term", ""),
                context=c.get("context", ""),
                complexity=c.get("complexity", "low"),
            ))
        return results

    async def check_boundary(self, concepts: list[DetectedConcept]) -> list[DetectedConcept]:
        """For each concept, check if it's within the user's knowledge boundary.

        Pipeline:
          1. Vector + BM25 search against knowledge store
          2. For top candidate: LLM judge whether it's the same concept
          3. Known → mark is_known=True / Unknown → set action
        """
        for concept in concepts:
            if not concept.term:
                concept.action = "ignore"
                continue

            # Search knowledge store
            query = f"{concept.term} {concept.context}"
            candidates = await self.store.search(query, top_k=5)

            if not candidates:
                concept.action = self._decide_action(concept.complexity)
                continue

            # Best candidate — check if it's really the same concept via LLM
            best = candidates[0]
            if best["score"] > 0.85:
                # High confidence from search alone — mark as known
                concept.is_known = True
                concept.summary = best["text"][:200]
                concept.action = "ignore"
            elif best["score"] > 0.5:
                # Medium confidence — ask LLM to judge
                is_match = await self._llm_judge(concept, best)
                if is_match:
                    concept.is_known = True
                    concept.summary = best["text"][:200]
                    concept.action = "ignore"
                else:
                    concept.search_results = candidates[:3]
                    concept.action = self._decide_action(concept.complexity)
            else:
                # Low confidence — unknown
                concept.search_results = candidates[:3]
                concept.action = self._decide_action(concept.complexity)

        return concepts

    async def _llm_judge(self, concept: DetectedConcept, candidate: dict) -> bool:
        """Ask LLM whether the candidate matches the concept."""
        prompt = JUDGE_PROMPT.format(
            query_term=concept.term,
            query_context=concept.context,
            candidate_text=candidate["text"],
            score=candidate["score"],
        )
        try:
            response = await self.llm.chat(
                messages=[
                    {"role": "user", "content": prompt},
                ],
                temperature=0.0,
                max_tokens=10,
            )
            return (response.content or "").strip().lower().startswith("yes")
        except Exception:
            return False

    def _decide_action(self, complexity: str) -> str:
        if complexity == "low":
            return "auto_absorb"
        elif complexity == "medium":
            return "manual_review"
        else:
            return "manual_review"
