"""
models.py
---------
Database Schema Models Module (SQLAlchemy 2.0).

WHAT THIS FILE DOES:
Defines the database tables stored in SQLite (`omnicanvas.db`):
1. `ChatSession`: Represents a user's chat conversation.
2. `ChatMessage`: Stores individual chat history messages (user & assistant answers).
3. `Document`: Represents uploaded files (PDF, images, code/text).
4. `Chunk`: Parent and child text chunks extracted from documents for RAG vector search.
5. `EvalLog`: Tracks answer quality metrics (groundedness, citation accuracy).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db import Base


def utcnow() -> datetime:
    """Helper to generate current UTC timestamp."""
    return datetime.now(timezone.utc)


def new_id() -> str:
    """Helper to generate a unique random UUID string."""
    return uuid.uuid4().hex


class ChatSession(Base):
    """Chat conversation thread."""
    __tablename__ = "chat_sessions"

    session_id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    title: Mapped[str] = mapped_column(String(255), default="New chat")
    model_provider: Mapped[str] = mapped_column(String(32), default="gemini")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    # Relationships to messages and uploaded documents
    messages: Mapped[list["ChatMessage"]] = relationship(
        back_populates="session", cascade="all, delete-orphan", order_by="ChatMessage.id"
    )
    documents: Mapped[list["Document"]] = relationship(
        back_populates="session", cascade="all, delete-orphan", order_by="Document.created_at"
    )

    @property
    def id(self) -> str:
        return self.session_id


class ChatMessage(Base):
    """Single chat message in a conversation thread."""
    __tablename__ = "chat_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(
        ForeignKey("chat_sessions.session_id", ondelete="CASCADE"), index=True
    )
    sender: Mapped[str] = mapped_column(String(16))  # "user" or "assistant"
    content: Mapped[str] = mapped_column(Text)
    model_provider: Mapped[str] = mapped_column(String(32), default="gemini")
    sources: Mapped[list | None] = mapped_column(JSON, nullable=True)     # Cited document page sources
    artifacts: Mapped[list | None] = mapped_column(JSON, nullable=True)   # Generated code/HTML/SVG canvas artifacts
    quality: Mapped[dict | None] = mapped_column(JSON, nullable=True)     # Groundedness quality scores
    pii_labels: Mapped[list | None] = mapped_column(JSON, nullable=True)  # Labels of redacted sensitive info
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    session: Mapped[ChatSession] = relationship(back_populates="messages")


class Document(Base):
    """Uploaded file metadata and indexing state."""
    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    session_id: Mapped[str] = mapped_column(
        ForeignKey("chat_sessions.session_id", ondelete="CASCADE"), index=True
    )
    filename: Mapped[str] = mapped_column(String(255))
    stored_name: Mapped[str] = mapped_column(String(300))
    mime: Mapped[str] = mapped_column(String(100), default="application/octet-stream")
    kind: Mapped[str] = mapped_column(String(16))  # "pdf" | "text" | "image"
    size: Mapped[int] = mapped_column(Integer, default=0)
    pages: Mapped[int] = mapped_column(Integer, default=0)
    chunks: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(16), default="queued")  # queued | reading | indexing | ready | failed
    progress: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    session: Mapped[ChatSession] = relationship(back_populates="documents")
    chunk_rows: Mapped[list["Chunk"]] = relationship(cascade="all, delete-orphan", passive_deletes=True)


class Chunk(Base):
    """Extracted text passage chunk for RAG hybrid search."""
    __tablename__ = "chunks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    doc_id: Mapped[str] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    session_id: Mapped[str] = mapped_column(String(64), index=True)
    level: Mapped[str] = mapped_column(String(8), index=True)  # "parent" (larger context) or "child" (fine chunk)
    parent_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    page: Mapped[int] = mapped_column(Integer, default=1)
    page_end: Mapped[int] = mapped_column(Integer, default=1)
    kind: Mapped[str] = mapped_column(String(16), default="text")
    text: Mapped[str] = mapped_column(Text)


class EvalLog(Base):
    """Log entry for evaluating RAG answer accuracy."""
    __tablename__ = "eval_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(String(64), index=True)
    message_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    metrics: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
