"""
services/chat_service.py
------------------------
The chat pipeline, as a generator of events that the route turns into
Server-Sent Events.

  scrub PII -> save user message -> (rewrite follow-up) -> hybrid retrieve
  -> stream the answer -> verify citations + groundedness -> persist -> log eval

Event types: meta | token | done | error
"""

from __future__ import annotations

import logging
import re
import time
from functools import lru_cache
from typing import Iterator

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from sqlalchemy import delete, func, select

from config import settings
from db import SessionLocal
from models import ChatMessage, ChatSession, Document, utcnow
from rag.embeddings import get_embedder
from rag.retriever import HybridRetriever, RetrievalResult
from rag.vector_store import get_vector_store
from services.artifacts import extract_artifacts
from services.evals import build_quality, log_eval
from services.guardrails import groundedness, scrub_pii, validate_citations
from services.model_service import (
    ModelUnavailable,
    complete_text,
    get_chat_model,
    parse_index_list,
    pick_utility_provider,
    stream_text,
)
from services.prompts import RERANK_PROMPT, REWRITE_PROMPT, SYSTEM_PROMPT, build_user_prompt
from services.sql_repo import SqlChunkRepo


log = logging.getLogger("omnicanvas.chat")

HISTORY_TURNS = 8


# ------------------------------------------------------------------- retriever


def _llm_reranker(provider: str):
    def rerank(question: str, passages: list[str]) -> list[int]:
        numbered = "\n\n".join(f"[{i + 1}] {p[:500]}" for i, p in enumerate(passages[:15]))
        try:
            raw = complete_text(
                pick_utility_provider(provider),
                [HumanMessage(content=RERANK_PROMPT.format(question=question, passages=numbered))],
            )
            return parse_index_list(raw)
        except Exception as exc:
            log.warning("Rerank skipped: %s", exc)
            return []

    return rerank


@lru_cache(maxsize=2)
def _retriever(rerank_provider: str | None) -> HybridRetriever:
    return HybridRetriever(
        repo=SqlChunkRepo(),
        embedder=get_embedder(),
        store=get_vector_store(),
        k=settings.retrieve_k,
        candidate_pool=settings.candidate_pool,
        reranker=_llm_reranker(rerank_provider) if rerank_provider else None,
    )


def get_retriever(provider: str) -> HybridRetriever:
    return _retriever(provider if settings.rerank_mode == "llm" else None)


# --------------------------------------------------------------------- helpers


def _title_from(prompt: str) -> str:
    text = re.sub(r"\s+", " ", prompt).strip()
    if len(text) <= 48:
        return text.rstrip(".?!") or "New chat"
    cut = text[:48].rsplit(" ", 1)[0]
    return cut.rstrip(".,;:?!") + "..."


def _rewrite(question: str, history: list[ChatMessage], provider: str) -> str:
    if not settings.rewrite_queries or not history:
        return question
    transcript = "\n".join(
        f"{'User' if m.sender == 'user' else 'Assistant'}: {m.content[:400]}" for m in history[-6:]
    )
    try:
        rewritten = complete_text(
            pick_utility_provider(provider),
            [HumanMessage(content=REWRITE_PROMPT.format(history=transcript, question=question))],
        )
        rewritten = rewritten.strip().strip('"')
        return rewritten if 3 <= len(rewritten) <= 400 else question
    except Exception as exc:
        log.warning("Query rewrite skipped: %s", exc)
        return question


def _friendly_error(exc: Exception) -> str:
    text = str(exc)
    lowered = text.lower()
    if "api key" in lowered or "api_key" in lowered or "permission" in lowered or "401" in lowered:
        return "The model rejected the API key. Check the key in your .env file."
    if "quota" in lowered or "429" in lowered or "rate" in lowered:
        return "The model is rate-limited right now. Wait a few seconds and try again."
    if "timeout" in lowered or "timed out" in lowered:
        return "The model took too long to respond. Try again, or switch models."
    return f"The model could not answer: {text[:200]}"


# -------------------------------------------------------------------- pipeline


def run_chat(req: ChatRequest) -> Iterator[dict]:
    started = time.perf_counter()

    # Own session: FastAPI closes request-scoped sessions before a stream finishes.
    with SessionLocal() as db:
        session = db.get(ChatSession, req.session_id)
        if session is None:
            session = ChatSession(session_id=req.session_id, title="New chat", model_provider=req.provider)
            db.add(session)
            db.commit()
        session.model_provider = req.provider

        pii_labels: list[str] = []
        if req.regenerate:
            last_user = db.scalars(
                select(ChatMessage)
                .where(ChatMessage.session_id == session.session_id, ChatMessage.sender == "user")
                .order_by(ChatMessage.id.desc())
                .limit(1)
            ).first()
            if last_user is None:
                yield {"type": "error", "message": "There is nothing to regenerate yet."}
                return
            db.execute(
                delete(ChatMessage).where(
                    ChatMessage.session_id == session.session_id, ChatMessage.id > last_user.id
                )
            )
            db.commit()
            question = last_user.content
            user_row = last_user
        else:
            if not req.message.strip():
                yield {"type": "error", "message": "Type a question first."}
                return
            question, pii_labels = (
                scrub_pii(req.message) if settings.redact_input_pii else (req.message, [])
            )
            user_row = ChatMessage(
                session_id=session.session_id,
                sender="user",
                content=question,
                model_provider=req.provider,
                pii_labels=pii_labels or None,
            )
            db.add(user_row)
            db.commit()

        history = list(
            db.scalars(
                select(ChatMessage)
                .where(ChatMessage.session_id == session.session_id, ChatMessage.id < user_row.id)
                .order_by(ChatMessage.id.desc())
                .limit(HISTORY_TURNS)
            )
        )[::-1]

        ready_docs = db.scalar(
            select(func.count(Document.id)).where(
                Document.session_id == session.session_id, Document.status == "ready"
            )
        )

        # ---- retrieval
        retrieval = RetrievalResult()
        search_query = question
        if ready_docs:
            search_query = _rewrite(question, history, req.provider)
            try:
                retrieval = get_retriever(req.provider).retrieve(session.session_id, search_query)
            except Exception as exc:
                log.exception("Retrieval failed")
                yield {"type": "error", "message": f"Searching your documents failed: {str(exc)[:160]}"}
                return

        contexts = retrieval.contexts
        yield {
            "type": "meta",
            "sources": [c.public() for c in contexts],
            "rewritten": search_query if search_query != question else None,
            "retrieval_ms": retrieval.ms,
            "blocked_passages": retrieval.blocked,
            "pii_redacted": pii_labels,
            "documents_searched": ready_docs or 0,
        }

        # ---- generation
        messages = [SystemMessage(content=SYSTEM_PROMPT)]
        for past in history:
            cls = HumanMessage if past.sender == "user" else AIMessage
            messages.append(cls(content=past.content))
        messages.append(HumanMessage(content=build_user_prompt(question, contexts)))

        try:
            model = get_chat_model(req.provider, req.temperature)
        except ModelUnavailable as exc:
            yield {"type": "error", "message": str(exc)}
            return

        parts: list[str] = []
        first_token_ms: float | None = None
        saved = False

        def persist(final: bool, quality: dict | None, sources: list[dict], artifacts: list[dict]) -> int:
            nonlocal saved
            row = ChatMessage(
                session_id=session.session_id,
                sender="assistant",
                content="".join(parts),
                model_provider=req.provider,
                sources=sources or None,
                artifacts=artifacts or None,
                quality=quality,
            )
            db.add(row)
            session.updated_at = utcnow()
            db.commit()
            saved = True
            return row.id

        try:
            try:
                for piece in stream_text(model, messages):
                    if first_token_ms is None:
                        first_token_ms = round((time.perf_counter() - started) * 1000, 1)
                    parts.append(piece)
                    yield {"type": "token", "text": piece}
            except Exception as exc:
                log.exception("Generation failed")
                if not parts:
                    yield {"type": "error", "message": _friendly_error(exc)}
                    return
                parts.append("\n\n*The answer was cut short because the model connection dropped.*")

            # ---- verification
            answer = "".join(parts)
            valid, invalid = validate_citations(answer, {c.ref for c in contexts})
            grounded = groundedness(answer, [c.text for c in contexts])
            _, output_pii = scrub_pii(answer)
            artifacts = extract_artifacts(answer)
            total_ms = round((time.perf_counter() - started) * 1000, 1)

            quality = build_quality(
                grounded=grounded,
                valid_refs=valid,
                invalid_refs=invalid,
                contexts=contexts,
                retrieval_ms=retrieval.ms,
                first_token_ms=first_token_ms,
                total_ms=total_ms,
                output_pii=output_pii,
            )
            cited_sources = [c.public() for c in contexts if c.ref in valid]

            message_id = persist(True, quality, cited_sources, artifacts)
            log_eval(db, session.session_id, message_id, quality)

            user_count = db.scalar(
                select(func.count(ChatMessage.id)).where(
                    ChatMessage.session_id == session.session_id, ChatMessage.sender == "user"
                )
            )
            if user_count == 1 and session.title in {"New chat", "New Chat", "New Workspace"}:
                session.title = _title_from(question)
            db.commit()

            yield {
                "type": "done",
                "message_id": message_id,
                "title": session.title,
                "artifacts": artifacts,
                "sources": cited_sources,
                "quality": quality,
            }
        finally:
            # Client pressed Stop (generator closed mid-stream): keep what was written.
            if parts and not saved:
                try:
                    persist(False, None, [], [])
                except Exception:
                    log.debug("Could not save partial answer", exc_info=True)
