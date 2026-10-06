"""routes/upload.py - validated file upload that starts background indexing."""

from __future__ import annotations

import os
import re
import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from config import settings
from db import get_db
from models import ChatSession, Document
from rag.ingestion import ingest_document
from schemas import DocumentOut
from services.ratelimit import RateLimiter


router = APIRouter(prefix="/api/upload", tags=["Uploads"])
limit_uploads = RateLimiter("upload", settings.rate_upload_per_min)

TEXT_EXTENSIONS = {".txt", ".md", ".py", ".js", ".ts", ".html", ".css", ".json", ".csv", ".yaml", ".yml"}
IMAGE_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}


def _classify(extension: str, head: bytes) -> tuple[str, str]:
    """Return (kind, mime) after checking the file's real signature, not just its name."""
    if extension == ".pdf":
        if not head.startswith(b"%PDF"):
            raise HTTPException(status_code=400, detail="That file isn't a valid PDF.")
        return "pdf", "application/pdf"
    if extension in IMAGE_TYPES:
        signatures = (b"\x89PNG", b"\xff\xd8\xff", b"RIFF")
        if not head.startswith(signatures):
            raise HTTPException(status_code=400, detail="That file isn't a valid image.")
        return "image", IMAGE_TYPES[extension]
    if extension in TEXT_EXTENSIONS:
        if b"\x00" in head:
            raise HTTPException(status_code=400, detail="That file looks binary, not text.")
        return "text", "text/plain"
    raise HTTPException(
        status_code=400,
        detail="Unsupported file type. Use a PDF, image (PNG/JPG/WebP) or a text/code file.",
    )


@router.post("", response_model=DocumentOut, status_code=status.HTTP_201_CREATED)
async def upload_document(
    background: BackgroundTasks,
    file: UploadFile = File(...),
    session_id: str = Form(...),
    db: Session = Depends(get_db),
    _: None = Depends(limit_uploads),
):
    if not file.filename:
        raise HTTPException(status_code=400, detail="The file has no name.")

    session = db.get(ChatSession, session_id)
    if session is None:
        session = ChatSession(session_id=session_id, title="New chat")
        db.add(session)
        db.commit()

    original = os.path.basename(file.filename)
    extension = os.path.splitext(original)[1].lower()

    # Read in chunks so an oversized upload is rejected without filling memory.
    size = 0
    chunks: list[bytes] = []
    while True:
        block = await file.read(1024 * 1024)
        if not block:
            break
        size += len(block)
        if size > settings.max_upload_bytes:
            raise HTTPException(
                status_code=413, detail=f"That file is larger than the {settings.max_upload_mb} MB limit."
            )
        chunks.append(block)
    data = b"".join(chunks)
    if not data:
        raise HTTPException(status_code=400, detail="That file is empty.")

    kind, mime = _classify(extension, data[:2048])

    safe = re.sub(r"[^A-Za-z0-9._\-]+", "_", original)[:120] or "upload"
    stored = f"{uuid.uuid4().hex[:12]}_{safe}"
    (settings.upload_dir / stored).write_bytes(data)

    doc = Document(
        session_id=session_id, filename=original[:255], stored_name=stored, mime=mime, kind=kind, size=size
    )
    db.add(doc)
    db.commit()

    background.add_task(ingest_document, doc.id)
    return doc
