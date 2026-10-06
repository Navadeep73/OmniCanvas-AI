"""routes/meta.py - health check, provider status, and measured quality summary."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from db import get_db
from rag.embeddings import get_embedder
from rag.vector_store import get_vector_store
from services import evals
from services.model_service import provider_status


router = APIRouter(prefix="/api", tags=["Meta"])


@router.get("/health")
def health():
    embedder = get_embedder()
    return {
        "status": "ok",
        "providers": provider_status(),
        "embeddings": {"name": embedder.name, "semantic": not embedder.name.startswith("hash")},
        "vector_store": get_vector_store().kind,
    }


@router.get("/evals/summary")
def evals_summary(db: Session = Depends(get_db)):
    return evals.summarize(db)
