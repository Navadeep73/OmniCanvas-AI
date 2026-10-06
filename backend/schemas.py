"""
schemas.py
----------
API Request & Response Data Schemas (Pydantic v2).

WHAT THIS FILE DOES:
Defines input validation schemas and JSON output serializations for REST API requests:
1. `ChatRequest`: Input schema for chat prompt streaming requests.
2. `SessionCreate` / `SessionUpdate` / `SessionOut`: Input/Output schemas for managing chat sessions.
3. `MessageOut`: Output schema for individual user and AI assistant messages.
4. `DocumentOut`: Output schema for uploaded files and indexing status.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ChatRequest(BaseModel):
    """Payload for submitting a chat prompt or requesting a response regeneration."""
    session_id: str = Field(..., min_length=1, max_length=64)
    message: str = Field("", max_length=8000)
    provider: Literal["gemini", "groq"] = "gemini"
    temperature: float = Field(0.4, ge=0.0, le=1.5)
    regenerate: bool = False


class SessionCreate(BaseModel):
    """Payload for creating a new chat session."""
    title: str = Field("New chat", max_length=255)
    model_provider: Literal["gemini", "groq"] = "gemini"


class SessionUpdate(BaseModel):
    """Payload for updating/renaming an existing chat session title."""
    title: str = Field(..., min_length=1, max_length=255)


class SessionOut(BaseModel):
    """JSON output representation of a chat session."""
    model_config = ConfigDict(from_attributes=True)

    id: str
    session_id: str
    title: str
    model_provider: str
    created_at: datetime
    updated_at: datetime


class MessageOut(BaseModel):
    """JSON output representation of a chat message."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    session_id: str
    sender: str
    content: str
    model_provider: str
    sources: list[dict[str, Any]] | None = None
    artifacts: list[dict[str, Any]] | None = None
    quality: dict[str, Any] | None = None
    pii_labels: list[str] | None = None
    created_at: datetime


class DocumentOut(BaseModel):
    """JSON output representation of an uploaded document."""
    model_config = ConfigDict(from_attributes=True)

    id: str
    session_id: str
    filename: str
    kind: str
    mime: str
    size: int
    pages: int
    chunks: int
    status: str
    progress: int
    error: str | None = None
    created_at: datetime
