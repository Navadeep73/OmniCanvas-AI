"""
services/sql_repo.py
--------------------
SQL-backed ChunkRepo for the hybrid retriever.
"""

from __future__ import annotations

from sqlalchemy import select

from db import SessionLocal
from models import Chunk, Document
from rag.retriever import ChildRow, ParentRow



class SqlChunkRepo:
    def children(self, session_id: str) -> list[ChildRow]:
        with SessionLocal() as db:
            rows = db.execute(
                select(Chunk.id, Chunk.doc_id, Chunk.parent_id, Chunk.page, Chunk.kind, Chunk.text)
                .join(Document, Document.id == Chunk.doc_id)
                .where(Chunk.session_id == session_id, Chunk.level == "child", Document.status == "ready")
                .order_by(Chunk.id)
            ).all()
        return [ChildRow(r.id, r.doc_id, r.parent_id or 0, r.page, r.kind, r.text) for r in rows]

    def parents(self, ids: list[int]) -> dict[int, ParentRow]:
        if not ids:
            return {}
        with SessionLocal() as db:
            rows = db.execute(
                select(Chunk, Document.filename)
                .join(Document, Document.id == Chunk.doc_id)
                .where(Chunk.id.in_(ids), Chunk.level == "parent")
            ).all()
        return {
            chunk.id: ParentRow(chunk.id, chunk.doc_id, filename, chunk.page, chunk.page_end, chunk.kind, chunk.text)
            for chunk, filename in rows
        }
