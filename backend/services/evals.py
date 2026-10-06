"""
services/evals.py
-----------------
Online quality signals, recorded per answer. Every number is measured, none are constants.

  groundedness       share of checkable claims supported by the retrieved sources (heuristic)
  citation_validity  share of [S#] tags that point at a real retrieved source
  top_similarity     best vector similarity among the cited/retrieved passages
  *_ms               retrieval, first token and total latency

For offline retrieval quality against a golden set, see eval/run_eval.py.
"""

from __future__ import annotations

from sqlalchemy import select

from models import EvalLog


def build_quality(
    *,
    grounded,
    valid_refs: list[str],
    invalid_refs: list[str],
    contexts: list,
    retrieval_ms: float,
    first_token_ms: float | None,
    total_ms: float,
    output_pii: list[str],
) -> dict:
    cited_total = len(valid_refs) + len(invalid_refs)
    return {
        "groundedness": grounded.score,
        "claims_checked": grounded.total,
        "unsupported": grounded.unsupported,
        "citation_validity": (len(valid_refs) / cited_total) if cited_total else None,
        "invalid_citations": invalid_refs,
        "cited": bool(valid_refs),
        "sources_retrieved": len(contexts),
        "top_similarity": max((c.score for c in contexts), default=None),
        "retrieval_ms": retrieval_ms,
        "first_token_ms": first_token_ms,
        "total_ms": total_ms,
        "output_pii": output_pii,
    }


def log_eval(db, session_id: str, message_id: int | None, quality: dict) -> None:
    db.add(EvalLog(session_id=session_id, message_id=message_id, metrics=quality))


def summarize(db, limit: int = 200) -> dict:
    rows = db.scalars(select(EvalLog).order_by(EvalLog.id.desc()).limit(limit)).all()

    def mean(key: str):
        values = [r.metrics.get(key) for r in rows if isinstance(r.metrics.get(key), (int, float))]
        return round(sum(values) / len(values), 3) if values else None

    return {
        "answers_measured": len(rows),
        "groundedness": mean("groundedness"),
        "citation_validity": mean("citation_validity"),
        "retrieval_ms": mean("retrieval_ms"),
        "first_token_ms": mean("first_token_ms"),
        "total_ms": mean("total_ms"),
    }
