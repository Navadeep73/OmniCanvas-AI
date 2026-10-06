"""
services/doc_service.py
-----------------------
Removing a document (or a whole session) must clean up three places:
the SQL rows, the vector index and the file on disk.
"""

from __future__ import annotations

import logging

from config import settings
from models import Document
from rag.vector_store import get_vector_store


log = logging.getLogger("omnicanvas.docs")


def purge_document_assets(doc: Document) -> None:
    """Delete vectors and the stored file. SQL rows are removed by the caller."""
    try:
        get_vector_store().delete(doc_id=doc.id)
    except Exception as exc:
        log.warning("Vector cleanup failed for %s: %s", doc.id, exc)
    try:
        (settings.upload_dir / doc.stored_name).unlink(missing_ok=True)
    except OSError as exc:
        log.warning("File cleanup failed for %s: %s", doc.stored_name, exc)
