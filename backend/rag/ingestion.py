"""
services/ingestion.py
---------------------
Turns an uploaded file into searchable chunks, in the background, reporting progress.

PDF pipeline (per page)
  1. text            PyMuPDF text extraction
  2. tables          PyMuPDF table finder -> markdown (its own chunks, so numbers stay aligned)
  3. figures         pages with images/vector art -> Gemini vision caption (capped per file)
  4. scanned pages   (almost no text) -> Gemini vision transcription

Then: parent/child chunking -> embeddings -> SQL rows + vector index.
Status moves queued -> reading -> indexing -> ready (or failed with a readable error).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable

from sqlalchemy import select

from config import settings
from db import SessionLocal
from models import Chunk, Document
from rag.chunking import PageBlock, build_chunks
from rag.embeddings import get_embedder
from rag.vector_store import get_vector_store
from services.model_service import describe_image
from services.prompts import VISION_FIGURE_PROMPT, VISION_IMAGE_PROMPT, VISION_OCR_PROMPT


log = logging.getLogger("omnicanvas.ingest")

TEXT_PAGE_CHARS = 3500
MAX_OCR_PAGES = 40

ProgressFn = Callable[[int], None]


# ----------------------------------------------------------------------- helpers


def slice_text_pages(text: str, size: int = TEXT_PAGE_CHARS) -> list[str]:
    """Plain-text files have no pages; cut them into stable sections that act as pages."""
    text = text.replace("\r\n", "\n")
    pages: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + size, len(text))
        if end < len(text):
            newline = text.rfind("\n", start + size // 2, end)
            if newline != -1:
                end = newline + 1
        pages.append(text[start:end])
        start = end
    return pages or [""]


def rows_to_markdown(rows: list[list]) -> str:
    cleaned = [
        [("" if cell is None else str(cell)).replace("\n", " ").replace("|", "/").strip() for cell in row]
        for row in rows
        if row
    ]
    cleaned = [row for row in cleaned if any(row)]
    if len(cleaned) < 2 or max(len(r) for r in cleaned) < 2:
        return ""
    width = max(len(r) for r in cleaned)
    cleaned = [r + [""] * (width - len(r)) for r in cleaned]
    lines = ["| " + " | ".join(cleaned[0]) + " |", "| " + " | ".join(["---"] * width) + " |"]
    lines += ["| " + " | ".join(row) + " |" for row in cleaned[1:]]
    return "\n".join(lines)


# -------------------------------------------------------------------- extraction


def extract_pdf(path: Path, on_progress: ProgressFn | None = None) -> tuple[list[PageBlock], int]:
    import fitz  # PyMuPDF

    use_vision = settings.use_vision and settings.has_gemini
    blocks: list[PageBlock] = []
    figures_done = 0
    ocr_done = 0

    document = fitz.open(str(path))
    try:
        total = len(document)
        for index in range(total):
            page = document[index]
            number = index + 1
            text = page.get_text("text") or ""
            if text.strip():
                blocks.append(PageBlock(number, text))

            try:
                for table in page.find_tables().tables:
                    markdown = rows_to_markdown(table.extract())
                    if markdown:
                        blocks.append(PageBlock(number, markdown, "table"))
            except Exception as exc:  # table finder is best-effort
                log.debug("Table extraction skipped on page %s: %s", number, exc)

            if use_vision:
                is_scan = len(text.strip()) < 30
                has_visuals = bool(page.get_images(full=True)) or len(page.get_drawings()) > 40
                try:
                    if is_scan and ocr_done < MAX_OCR_PAGES:
                        ocr_done += 1
                        png = page.get_pixmap(matrix=fitz.Matrix(1.6, 1.6)).tobytes("png")
                        transcript = describe_image(png, VISION_OCR_PROMPT)
                        if transcript:
                            blocks.append(PageBlock(number, transcript))
                    elif has_visuals and figures_done < settings.vision_pages_limit:
                        figures_done += 1
                        png = page.get_pixmap(matrix=fitz.Matrix(1.6, 1.6)).tobytes("png")
                        caption = describe_image(png, VISION_FIGURE_PROMPT)
                        if caption:
                            blocks.append(PageBlock(number, f"Visual on page {number}: {caption}", "figure"))
                except Exception as exc:
                    log.warning("Vision failed on page %s: %s", number, exc)

            if on_progress:
                on_progress(5 + int(30 * (index + 1) / max(total, 1)))
    finally:
        document.close()
    return blocks, total


def extract_text_file(path: Path) -> tuple[list[PageBlock], int]:
    text = path.read_text(encoding="utf-8", errors="ignore")
    pages = slice_text_pages(text)
    return [PageBlock(i + 1, page) for i, page in enumerate(pages) if page.strip()], len(pages)


def extract_image(path: Path, mime: str) -> tuple[list[PageBlock], int]:
    if not settings.has_gemini:
        raise RuntimeError("Understanding images needs a Gemini API key. Add GEMINI_API_KEY to your .env file.")
    description = describe_image(path.read_bytes(), VISION_IMAGE_PROMPT, mime=mime)
    if not description:
        raise RuntimeError("The image could not be read. Try a clearer or larger image.")
    return [PageBlock(1, description, "figure")], 1


# ------------------------------------------------------------------- the job


def _update(doc_id: str, **fields) -> None:
    with SessionLocal() as db:
        doc = db.get(Document, doc_id)
        if doc:
            for key, value in fields.items():
                setattr(doc, key, value)
            db.commit()


def ingest_document(doc_id: str) -> None:
    """Background task entry point. Never raises; failures are recorded on the row."""
    with SessionLocal() as db:
        doc = db.get(Document, doc_id)
        if doc is None:
            return
        path = settings.upload_dir / doc.stored_name
        kind, mime, session_id = doc.kind, doc.mime, doc.session_id

    store = get_vector_store()
    try:
        _update(doc_id, status="reading", progress=3)

        def progress(value: int) -> None:
            _update(doc_id, progress=min(value, 95))

        if kind == "pdf":
            blocks, pages = extract_pdf(path, progress)
        elif kind == "image":
            blocks, pages = extract_image(path, mime)
        else:
            blocks, pages = extract_text_file(path)

        parents, children = build_chunks(blocks)
        if not children:
            raise RuntimeError(
                "No readable text was found. If this is a scan, add a Gemini key so pages can be transcribed."
            )

        _update(doc_id, status="indexing", progress=40, pages=pages)

        embedder = get_embedder()
        vectors: list[list[float]] = []
        batch = 64
        for start in range(0, len(children), batch):
            vectors.extend(embedder.embed_documents([c.text for c in children[start : start + batch]]))
            _update(doc_id, progress=40 + int(50 * min(start + batch, len(children)) / len(children)))

        with SessionLocal() as db:
            parent_ids: dict[int, int] = {}
            for parent in parents:
                row = Chunk(
                    doc_id=doc_id, session_id=session_id, level="parent",
                    page=parent.page, page_end=parent.page_end, kind=parent.kind, text=parent.text,
                )
                db.add(row)
                db.flush()
                parent_ids[parent.idx] = row.id

            child_rows = []
            for child in children:
                row = Chunk(
                    doc_id=doc_id, session_id=session_id, level="child",
                    parent_id=parent_ids[child.parent_idx],
                    page=child.page, page_end=child.page, kind=child.kind, text=child.text,
                )
                db.add(row)
                child_rows.append(row)
            db.flush()

            store.add(
                [str(r.id) for r in child_rows],
                vectors,
                [{"session_id": session_id, "doc_id": doc_id} for _ in child_rows],
            )
            db.commit()

        _update(doc_id, status="ready", progress=100, chunks=len(children), error=None)
        log.info("Indexed %s: %d pages, %d parents, %d children", doc_id, pages, len(parents), len(children))

    except Exception as exc:
        log.exception("Ingestion failed for %s", doc_id)
        try:
            store.delete(doc_id=doc_id)
            with SessionLocal() as db:
                for chunk in db.scalars(select(Chunk).where(Chunk.doc_id == doc_id)):
                    db.delete(chunk)
                db.commit()
        except Exception:
            log.debug("Cleanup after failed ingestion also failed", exc_info=True)
        _update(doc_id, status="failed", progress=0, error=str(exc)[:400])
