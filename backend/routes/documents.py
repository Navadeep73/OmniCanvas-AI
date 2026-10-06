"""routes/documents.py - list, inspect, view and delete uploaded documents."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from config import settings
from db import get_db
from models import Document
from rag.ingestion import slice_text_pages
from schemas import DocumentOut
from services.doc_service import purge_document_assets



router = APIRouter(tags=["Documents"])


def _doc_or_404(db: Session, doc_id: str) -> Document:
    doc = db.get(Document, doc_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found")
    return doc


@router.get("/api/sessions/{session_id}/documents", response_model=list[DocumentOut])
def list_documents(session_id: str, db: Session = Depends(get_db)):
    return list(
        db.scalars(select(Document).where(Document.session_id == session_id).order_by(Document.created_at))
    )


@router.get("/api/documents/{doc_id}", response_model=DocumentOut)
def get_document(doc_id: str, db: Session = Depends(get_db)):
    return _doc_or_404(db, doc_id)


@router.get("/api/documents/{doc_id}/file")
def get_document_file(doc_id: str, db: Session = Depends(get_db)):
    doc = _doc_or_404(db, doc_id)
    path = settings.upload_dir / doc.stored_name
    if not path.exists():
        raise HTTPException(status_code=404, detail="The stored file is missing")
    return FileResponse(
        path,
        media_type=doc.mime,
        headers={"Content-Disposition": "inline", "X-Content-Type-Options": "nosniff"},
    )


@router.get("/api/documents/{doc_id}/text")
def get_document_text(doc_id: str, db: Session = Depends(get_db)):
    doc = _doc_or_404(db, doc_id)
    if doc.kind != "text":
        raise HTTPException(status_code=400, detail="Only text documents have a text view")
    path = settings.upload_dir / doc.stored_name
    text = path.read_text(encoding="utf-8", errors="ignore")
    return {"pages": slice_text_pages(text)}


@router.delete("/api/documents/{doc_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_document(doc_id: str, db: Session = Depends(get_db)):
    doc = _doc_or_404(db, doc_id)
    purge_document_assets(doc)
    db.delete(doc)
    db.commit()
