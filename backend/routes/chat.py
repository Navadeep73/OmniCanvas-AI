"""routes/chat.py - streaming (SSE) and non-streaming chat endpoints."""

from __future__ import annotations

import json
from typing import Iterator

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from config import settings
from schemas import ChatRequest
from services.chat_service import run_chat
from services.ratelimit import RateLimiter

router = APIRouter(prefix="/api/chat", tags=["Chat"])
limit_chat = RateLimiter("chat", settings.rate_chat_per_min)


def _sse(events: Iterator[dict]) -> Iterator[str]:
    try:
        for event in events:
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
    finally:
        close = getattr(events, "close", None)
        if close:
            close()  # propagate client disconnects so partial answers are saved


@router.post("/stream")
def chat_stream(payload: ChatRequest, _: None = Depends(limit_chat)):
    return StreamingResponse(
        _sse(run_chat(payload)),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
    )


@router.post("")
def chat_once(payload: ChatRequest, _: None = Depends(limit_chat)):
    """Same pipeline without streaming, for scripts and tests."""
    text: list[str] = []
    meta: dict = {}
    done: dict = {}
    error: str | None = None
    for event in run_chat(payload):
        if event["type"] == "token":
            text.append(event["text"])
        elif event["type"] == "meta":
            meta = event
        elif event["type"] == "done":
            done = event
        elif event["type"] == "error":
            error = event["message"]
    return {"message": "".join(text), "error": error, "meta": meta, **done}
