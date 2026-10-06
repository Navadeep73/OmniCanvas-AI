"""
services/embeddings.py
----------------------
Two embedders behind one tiny interface:

* GeminiEmbedder  - real semantic embeddings (needs GEMINI_API_KEY).
* HashEmbedder    - deterministic, offline, lexical-ish vectors. Used for tests,
                    CI, and so the app still *runs* with no key. It is not a
                    substitute for semantic embeddings; the UI/README say so.

`embedder.name` is part of the vector collection name, so switching embedders
never mixes incompatible vectors in one index.
"""

from __future__ import annotations

import hashlib
import logging
import math
import re
from functools import lru_cache
from typing import Protocol

from config import settings
from rag.bm25 import tokenize


log = logging.getLogger("omnicanvas.embeddings")


class Embedder(Protocol):
    name: str

    def embed_documents(self, texts: list[str]) -> list[list[float]]: ...

    def embed_query(self, text: str) -> list[float]: ...


class HashEmbedder:
    """Signed feature hashing over stemmed unigrams and bigrams, L2-normalised."""

    def __init__(self, dim: int = 512):
        self.dim = dim
        self.name = f"hash{dim}"

    def _vector(self, text: str) -> list[float]:
        tokens = tokenize(text)
        features = list(tokens) + [f"{a}_{b}" for a, b in zip(tokens, tokens[1:])]
        vec = [0.0] * self.dim
        for feature in features:
            digest = hashlib.md5(feature.encode("utf-8")).digest()
            index = int.from_bytes(digest[:4], "little") % self.dim
            sign = 1.0 if digest[4] & 1 else -1.0
            vec[index] += sign
        vec = [math.copysign(math.sqrt(abs(v)), v) for v in vec]  # sub-linear tf
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._vector(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._vector(text)


class GeminiEmbedder:
    def __init__(self, model: str, api_key: str):
        from langchain_google_genai import GoogleGenerativeAIEmbeddings

        self._client = GoogleGenerativeAIEmbeddings(model=model, google_api_key=api_key)
        slug = re.sub(r"[^a-z0-9]+", "", model.lower().replace("models/", ""))
        self.name = f"gemini{slug}"[:40]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for start in range(0, len(texts), 64):
            vectors.extend(self._client.embed_documents(texts[start : start + 64]))
        return vectors

    def embed_query(self, text: str) -> list[float]:
        return self._client.embed_query(text)


@lru_cache(maxsize=1)
def get_embedder() -> Embedder:
    if settings.has_gemini:
        try:
            return GeminiEmbedder(settings.embedding_model, settings.gemini_api_key)
        except Exception as exc:  # missing package, bad model name, ...
            log.warning("Gemini embeddings unavailable (%s). Falling back to hashing.", exc)
    else:
        log.warning("GEMINI_API_KEY not set. Using offline hash embeddings (lexical only).")
    return HashEmbedder()
