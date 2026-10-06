"""
services/chunking.py
--------------------
Parent/child chunking.

Small *child* chunks are what we embed and search (precise matching).
Larger *parent* chunks are what the model reads (enough context to answer).
Every chunk remembers the page it came from so answers can cite pages.

Pure Python, no third-party imports.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class PageBlock:
    """A piece of extracted content: page text, a table, or a figure caption."""

    page: int
    text: str
    kind: str = "text"  # text | table | figure


@dataclass
class ParentChunk:
    idx: int
    page: int
    page_end: int
    kind: str
    text: str


@dataclass
class ChildChunk:
    idx: int
    parent_idx: int
    page: int
    kind: str
    text: str


_SENTENCE_BREAK = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'(\[])")


def normalize(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\u00a0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def split_paragraphs(text: str) -> list[str]:
    """Blank-line separated paragraphs, with hard-wrapped lines re-joined."""
    paragraphs = []
    for raw in re.split(r"\n\s*\n", text):
        joined = re.sub(r"\s*\n\s*", " ", raw).strip()
        if joined:
            paragraphs.append(joined)
    return paragraphs


def split_long(text: str, limit: int) -> list[str]:
    """Split on sentence boundaries, falling back to words for giant sentences."""
    if len(text) <= limit:
        return [text]

    pieces: list[str] = []
    current = ""
    for sentence in _SENTENCE_BREAK.split(text):
        if len(sentence) > limit:
            if current:
                pieces.append(current)
                current = ""
            buffer = ""
            for word in sentence.split():
                if buffer and len(buffer) + len(word) + 1 > limit:
                    pieces.append(buffer)
                    buffer = word
                else:
                    buffer = f"{buffer} {word}".strip()
            current = buffer
            continue
        if current and len(current) + len(sentence) + 1 > limit:
            pieces.append(current)
            current = sentence
        else:
            current = f"{current} {sentence}".strip()
    if current:
        pieces.append(current)
    return pieces


def split_table(text: str, limit: int) -> list[str]:
    """Split a markdown table by rows, repeating the header on every part."""
    lines = text.split("\n")
    if len(text) <= limit or len(lines) < 4:
        return [text]

    header = "\n".join(lines[:2])
    parts: list[str] = []
    current = header
    for row in lines[2:]:
        if len(current) + len(row) + 1 > limit and current != header:
            parts.append(current)
            current = header
        current = f"{current}\n{row}"
    if current != header:
        parts.append(current)
    return parts


def _pack(pieces: list[str], limit: int, sep: str) -> list[str]:
    groups: list[str] = []
    current = ""
    for piece in pieces:
        if current and len(current) + len(sep) + len(piece) > limit:
            groups.append(current)
            current = piece
        else:
            current = f"{current}{sep}{piece}" if current else piece
    if current:
        groups.append(current)

    # Fold a tiny trailing group into the previous one.
    if len(groups) >= 2 and len(groups[-1]) < 200:
        if len(groups[-2]) + len(sep) + len(groups[-1]) <= int(limit * 1.3):
            groups[-2] = f"{groups[-2]}{sep}{groups[-1]}"
            groups.pop()
    return groups


def split_children(text: str, size: int, overlap: int, kind: str = "text") -> list[str]:
    """Overlapping, sentence-aware child windows."""
    if len(text) <= size:
        return [text]

    if kind == "table":
        return split_table(text, size)

    sentences: list[str] = []
    for sentence in _SENTENCE_BREAK.split(text):
        sentences.extend(split_long(sentence, size))

    chunks: list[str] = []
    current: list[str] = []
    current_len = 0
    for sentence in sentences:
        if current and current_len + len(sentence) + 1 > size:
            chunks.append(" ".join(current))
            carry: list[str] = []
            carried = 0
            for previous in reversed(current):
                if carried >= overlap:
                    break
                carry.insert(0, previous)
                carried += len(previous) + 1
            current = carry
            current_len = sum(len(item) + 1 for item in current)
            if current_len + len(sentence) + 1 > size:
                current, current_len = [], 0
        current.append(sentence)
        current_len += len(sentence) + 1
    if current:
        chunks.append(" ".join(current))
    return chunks


def build_chunks(
    blocks: list[PageBlock],
    parent_chars: int = 1800,
    child_chars: int = 520,
    overlap: int = 90,
) -> tuple[list[ParentChunk], list[ChildChunk]]:
    parents: list[ParentChunk] = []
    children: list[ChildChunk] = []

    for block in blocks:
        text = normalize(block.text)
        if not text:
            continue

        if block.kind == "table":
            groups = split_table(text, parent_chars)
        else:
            if block.kind == "text":
                units = split_paragraphs(text)
            else:
                units = [re.sub(r"\s*\n\s*", " ", text)]
            pieces: list[str] = []
            for unit in units:
                pieces.extend(split_long(unit, parent_chars))
            groups = _pack(pieces, parent_chars, "\n\n")

        for group in groups:
            parent = ParentChunk(len(parents), block.page, block.page, block.kind, group)
            parents.append(parent)
            for child_text in split_children(group, child_chars, overlap, block.kind):
                children.append(
                    ChildChunk(len(children), parent.idx, block.page, block.kind, child_text)
                )

    return parents, children
