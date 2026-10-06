"""
services/vector_store.py
------------------------
Vector index for child chunks.

SQL is the source of truth for chunk *text*; the vector store only maps
chunk id -> embedding. Every query is filtered by `session_id`, so one chat
can never retrieve passages from another chat's documents.
"""

from __future__ import annotations

import logging
from functools import lru_cache
from typing import Protocol

from config import settings

log = logging.getLogger("omnicanvas.vectors")


class VectorStore(Protocol):
    kind: str

    def add(self, ids: list[str], vectors: list[list[float]], metadatas: list[dict]) -> None: ...

    def query(self, vector: list[float], k: int, session_id: str) -> list[tuple[str, float]]: ...

    def delete(self, *, doc_id: str | None = None, session_id: str | None = None) -> None: ...


class MemoryStore:
    """Brute-force cosine search. Fine for tests and small corpora."""

    kind = "memory"

    def __init__(self) -> None:
        self._items: dict[str, tuple[list[float], dict]] = {}

    def add(self, ids, vectors, metadatas) -> None:
        for item_id, vector, meta in zip(ids, vectors, metadatas):
            self._items[item_id] = (vector, meta)

    def query(self, vector, k, session_id):
        scored = []
        for item_id, (stored, meta) in self._items.items():
            if meta.get("session_id") != session_id:
                continue
            similarity = sum(a * b for a, b in zip(vector, stored))
            scored.append((item_id, similarity))
        scored.sort(key=lambda pair: pair[1], reverse=True)
        return scored[:k]

    def delete(self, *, doc_id=None, session_id=None) -> None:
        for item_id in list(self._items):
            meta = self._items[item_id][1]
            if doc_id and meta.get("doc_id") == doc_id:
                del self._items[item_id]
            elif session_id and meta.get("session_id") == session_id:
                del self._items[item_id]


class ChromaStore:
    kind = "chroma"

    def __init__(self, path: str, collection: str) -> None:
        import chromadb

        self._client = chromadb.PersistentClient(path=path)
        self._collection = self._client.get_or_create_collection(
            name=collection, metadata={"hnsw:space": "cosine"}
        )

    def add(self, ids, vectors, metadatas) -> None:
        for start in range(0, len(ids), 256):
            end = start + 256
            self._collection.add(
                ids=ids[start:end], embeddings=vectors[start:end], metadatas=metadatas[start:end]
            )

    def query(self, vector, k, session_id):
        total = self._collection.count()
        if total == 0:
            return []
        try:
            result = self._collection.query(
                query_embeddings=[vector],
                n_results=min(k, total),
                where={"session_id": session_id},
            )
        except Exception as exc:  # degrade to keyword-only retrieval rather than fail the chat
            log.warning("Vector query failed (%s). Falling back to keyword search only.", exc)
            return []
        ids = result.get("ids", [[]])[0]
        distances = result.get("distances", [[]])[0]
        return [(item_id, 1.0 - float(dist)) for item_id, dist in zip(ids, distances)]

    def delete(self, *, doc_id=None, session_id=None) -> None:
        if doc_id:
            self._collection.delete(where={"doc_id": doc_id})
        elif session_id:
            self._collection.delete(where={"session_id": session_id})


@lru_cache(maxsize=1)
def get_vector_store() -> VectorStore:
    from rag.embeddings import get_embedder


    collection = f"{settings.collection_name}_{get_embedder().name}"
    try:
        return ChromaStore(settings.chroma_path, collection)
    except Exception as exc:
        log.warning("Chroma unavailable (%s). Using in-memory vectors; they reset on restart.", exc)
        return MemoryStore()
