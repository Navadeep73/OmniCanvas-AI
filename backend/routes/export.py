"""routes/export.py - download a chat as Markdown, including its sources."""

from __future__ import annotations

import re

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from db import get_db
from models import ChatMessage, ChatSession

router = APIRouter(prefix="/api/export", tags=["Export"])


@router.get("/{session_id}/markdown")
def export_markdown(session_id: str, db: Session = Depends(get_db)):
    session = db.get(ChatSession, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Chat not found")

    messages = db.scalars(
        select(ChatMessage).where(ChatMessage.session_id == session_id).order_by(ChatMessage.id)
    )
    lines = [f"# {session.title}", "", f"Exported from OmniCanvas. Model: {session.model_provider}.", ""]
    documents = [f"- {d.filename}" for d in session.documents]
    if documents:
        lines += ["**Documents**", *documents, ""]

    for message in messages:
        lines += [f"## {'You' if message.sender == 'user' else 'OmniCanvas'}", "", message.content, ""]
        if message.sources:
            lines.append("**Sources**")
            for source in message.sources:
                lines.append(f"- [{source['ref']}] {source['filename']}, page {source['page']}")
            lines.append("")

    slug = re.sub(r"[^a-z0-9]+", "-", session.title.lower()).strip("-")[:40] or "chat"
    return Response(
        content="\n".join(lines),
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="omnicanvas-{slug}.md"'},
    )
