"""routes/sessions.py - create, list, rename, delete chat sessions and read their messages."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from db import get_db
from models import ChatMessage, ChatSession
from rag.vector_store import get_vector_store
from schemas import MessageOut, SessionCreate, SessionOut, SessionUpdate
from services.doc_service import purge_document_assets



router = APIRouter(prefix="/api/sessions", tags=["Sessions"])


def _get_or_404(db: Session, session_id: str) -> ChatSession:
    session = db.get(ChatSession, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Chat not found")
    return session


@router.get("", response_model=list[SessionOut])
def list_sessions(db: Session = Depends(get_db)):
    return list(db.scalars(select(ChatSession).order_by(ChatSession.updated_at.desc())))


@router.post("", response_model=SessionOut, status_code=status.HTTP_201_CREATED)
def create_session(payload: SessionCreate, db: Session = Depends(get_db)):
    session = ChatSession(
        session_id=uuid.uuid4().hex, title=payload.title or "New chat", model_provider=payload.model_provider
    )
    db.add(session)
    db.commit()
    return session


@router.get("/{session_id}", response_model=SessionOut)
def get_session(session_id: str, db: Session = Depends(get_db)):
    return _get_or_404(db, session_id)


@router.patch("/{session_id}", response_model=SessionOut)
def rename_session(session_id: str, payload: SessionUpdate, db: Session = Depends(get_db)):
    session = _get_or_404(db, session_id)
    session.title = payload.title.strip()[:255]
    db.commit()
    return session


@router.get("/{session_id}/messages", response_model=list[MessageOut])
def get_messages(session_id: str, db: Session = Depends(get_db)):
    _get_or_404(db, session_id)
    return list(
        db.scalars(select(ChatMessage).where(ChatMessage.session_id == session_id).order_by(ChatMessage.id))
    )


@router.delete("/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_session(session_id: str, db: Session = Depends(get_db)):
    session = _get_or_404(db, session_id)
    for doc in list(session.documents):
        purge_document_assets(doc)
    try:
        get_vector_store().delete(session_id=session_id)
    except Exception:
        pass
    db.delete(session)
    db.commit()
