"""
services/retriever.py
---------------------
Hybrid retrieval over parent/child chunks.

    question
      |-- BM25 over child chunks  --\
      |                              >-- Reciprocal Rank Fusion --> (optional rerank)
      |-- vector search (children) -/                                   |
                                                                  map to parents,
                                                                  drop injected text,
                                                                  return top-k contexts

The retriever only needs a `ChunkRepo` (where chunk text lives), an embedder and a
vector store. SQL implements `ChunkRepo` in production; `InMemoryChunkRepo` below
powers unit tests and the offline eval harness with identical logic.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable, Protocol

from rag.bm25 import BM25, reciprocal_rank_fusion, tokenize
from rag.chunking import PageBlock, build_chunks
from services.guardrails import detect_injection



@dataclass
class ChildRow:
    id: int
    doc_id: str
    parent_id: int
    page: int
    kind: str
    text: str


@dataclass
class ParentRow:
    id: int
    doc_id: str
    filename: str
    page: int
    page_end: int
    kind: str
    text: str


class ChunkRepo(Protocol):
    def children(self, session_id: str) -> list[ChildRow]: ...

    def parents(self, ids: list[int]) -> dict[int, ParentRow]: ...


@dataclass
class Context:
    ref: str  # "S1", "S2", ... the tag the model cites
    doc_id: str
    filename: str
    page: int
    page_end: int
    kind: str
    text: str
    evidence: str  # best-matching child passage, used for highlighting
    score: float  # cosine similarity of the best child (0 if vector missed it)

    def public(self) -> dict:
        return {
            "ref": self.ref,
            "doc_id": self.doc_id,
            "filename": self.filename,
            "page": self.page,
            "page_end": self.page_end,
            "kind": self.kind,
            "snippet": self.evidence[:420],
            "score": self.score,
        }


@dataclass
class RetrievalResult:
    contexts: list[Context] = field(default_factory=list)
    blocked: int = 0  # passages dropped for looking like injected instructions
    candidates: int = 0
    ms: float = 0.0


class HybridRetriever:
    def __init__(
        self,
        repo: ChunkRepo,
        embedder,
        store,
        k: int = 5,
        candidate_pool: int = 24,
        reranker: Callable[[str, list[str]], list[int]] | None = None,
    ) -> None:
        self.repo = repo
        self.embedder = embedder
        self.store = store
        self.k = k
        self.candidate_pool = candidate_pool
        self.reranker = reranker
        self._bm25_cache: dict[str, tuple[int, BM25, list[ChildRow]]] = {}

    def _index(self, session_id: str) -> tuple[BM25, list[ChildRow]] | None:
        children = self.repo.children(session_id)
        if not children:
            self._bm25_cache.pop(session_id, None)
            return None
        signature = hash(tuple(c.id for c in children))
        cached = self._bm25_cache.get(session_id)
        if cached and cached[0] == signature:
            return cached[1], cached[2]
        index = BM25([tokenize(c.text) for c in children])
        self._bm25_cache[session_id] = (signature, index, children)
        return index, children

    def retrieve(self, session_id: str, query: str, k: int | None = None) -> RetrievalResult:
        started = time.perf_counter()
        k = k or self.k

        built = self._index(session_id)
        if built is None:
            return RetrievalResult()
        index, children = built
        by_id = {c.id: c for c in children}

        keyword_hits = index.top(tokenize(query), self.candidate_pool)
        keyword_ids = [children[i].id for i, _ in keyword_hits]

        vector_hits = self.store.query(
            self.embedder.embed_query(query), self.candidate_pool, session_id
        )
        vector_ids = [int(item_id) for item_id, _ in vector_hits]
        similarity = {int(item_id): sim for item_id, sim in vector_hits}

        fused_ids = [
            int(cid)
            for cid, _ in reciprocal_rank_fusion([keyword_ids, vector_ids])
            if int(cid) in by_id
        ][: self.candidate_pool]

        if self.reranker and len(fused_ids) > 1:
            order = self.reranker(query, [by_id[cid].text for cid in fused_ids])
            reordered = [fused_ids[i] for i in order if 0 <= i < len(fused_ids)]
            reordered += [cid for cid in fused_ids if cid not in reordered]
            fused_ids = reordered

        # Collapse children to their parents, keeping the best child as evidence.
        best_child: dict[int, ChildRow] = {}
        parent_order: list[int] = []
        for cid in fused_ids:
            child = by_id[cid]
            if child.parent_id not in best_child:
                best_child[child.parent_id] = child
                parent_order.append(child.parent_id)
            if len(parent_order) >= k + 3:  # a few spares in case some are blocked
                break

        parents = self.repo.parents(parent_order)
        contexts: list[Context] = []
        blocked = 0
        for parent_id in parent_order:
            parent = parents.get(parent_id)
            if parent is None:
                continue
            if detect_injection(parent.text).flagged:
                blocked += 1
                continue
            child = best_child[parent_id]
            contexts.append(
                Context(
                    ref=f"S{len(contexts) + 1}",
                    doc_id=parent.doc_id,
                    filename=parent.filename,
                    page=parent.page,
                    page_end=parent.page_end,
                    kind=parent.kind,
                    text=parent.text,
                    evidence=child.text,
                    score=round(similarity.get(child.id, 0.0), 3),
                )
            )
            if len(contexts) >= k:
                break

        return RetrievalResult(
            contexts=contexts,
            blocked=blocked,
            candidates=len(fused_ids),
            ms=round((time.perf_counter() - started) * 1000, 1),
        )


class InMemoryChunkRepo:
    """ChunkRepo + indexer used by tests and the offline eval harness."""

    def __init__(self, embedder, store) -> None:
        self.embedder = embedder
        self.store = store
        self._children: list[ChildRow] = []
        self._parents: dict[int, ParentRow] = {}
        self._sessions: dict[int, str] = {}
        self._next_id = 1

    def add_document(
        self, session_id: str, doc_id: str, filename: str, blocks: list[PageBlock]
    ) -> tuple[int, int]:
        parents, children = build_chunks(blocks)
        parent_ids: dict[int, int] = {}
        for parent in parents:
            pid = self._next_id
            self._next_id += 1
            parent_ids[parent.idx] = pid
            self._parents[pid] = ParentRow(
                pid, doc_id, filename, parent.page, parent.page_end, parent.kind, parent.text
            )

        rows = []
        for child in children:
            cid = self._next_id
            self._next_id += 1
            row = ChildRow(cid, doc_id, parent_ids[child.parent_idx], child.page, child.kind, child.text)
            rows.append(row)
            self._children.append(row)
            self._sessions[cid] = session_id

        vectors = self.embedder.embed_documents([r.text for r in rows])
        self.store.add(
            [str(r.id) for r in rows],
            vectors,
            [{"session_id": session_id, "doc_id": doc_id} for _ in rows],
        )
        return len(parents), len(children)

    def children(self, session_id: str) -> list[ChildRow]:
        return [c for c in self._children if self._sessions[c.id] == session_id]

    def parents(self, ids: list[int]) -> dict[int, ParentRow]:
        return {i: self._parents[i] for i in ids if i in self._parents}
