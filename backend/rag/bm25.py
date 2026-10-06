"""
services/bm25.py
----------------
Small, dependency-free BM25 keyword index and Reciprocal Rank Fusion.

BM25 catches exact terms (names, numbers, acronyms) that embeddings blur;
embeddings catch paraphrases that keywords miss. We fuse both.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from typing import Hashable, Sequence

_TOKEN = re.compile(r"[a-z0-9]+")

STOPWORDS = frozenset(
    """a an and are as at be but by for from has have he her his i in is it its of on or
    she that the their they this to was we were what when where which who why will with
    you your do does did how not can could should would about into than then there these
    those them our us if so such also may might more most other some any each per via
    been being am been over under again further once here only own same too very just""".split()
)


def stem(token: str) -> str:
    """A deliberately tiny suffix stripper, applied to documents and queries alike."""
    if len(token) > 5 and token.endswith("ing"):
        return token[:-3]
    if len(token) > 4 and token.endswith("ed"):
        return token[:-2]
    if len(token) > 4 and token.endswith("es"):
        return token[:-2]
    if len(token) > 3 and token.endswith("s") and not token.endswith("ss"):
        return token[:-1]
    return token


def tokenize(text: str, keep_stopwords: bool = False) -> list[str]:
    tokens = _TOKEN.findall(text.lower())
    if not keep_stopwords:
        tokens = [t for t in tokens if t not in STOPWORDS]
    return [stem(t) for t in tokens]


class BM25:
    def __init__(self, documents: Sequence[Sequence[str]], k1: float = 1.5, b: float = 0.75):
        self.k1 = k1
        self.b = b
        self.documents = [list(doc) for doc in documents]
        self.size = len(self.documents)
        self.avg_len = (sum(len(d) for d in self.documents) / self.size) if self.size else 0.0
        self.term_freqs = [Counter(doc) for doc in self.documents]

        doc_freq: Counter[str] = Counter()
        for freqs in self.term_freqs:
            doc_freq.update(freqs.keys())
        self.idf = {
            term: math.log(1 + (self.size - df + 0.5) / (df + 0.5)) for term, df in doc_freq.items()
        }

    def scores(self, query_tokens: Sequence[str]) -> list[float]:
        results = [0.0] * self.size
        if not self.size:
            return results
        for term in set(query_tokens):
            idf = self.idf.get(term)
            if idf is None:
                continue
            for i, freqs in enumerate(self.term_freqs):
                tf = freqs.get(term)
                if not tf:
                    continue
                length_norm = 1 - self.b + self.b * (len(self.documents[i]) / (self.avg_len or 1))
                results[i] += idf * (tf * (self.k1 + 1)) / (tf + self.k1 * length_norm)
        return results

    def top(self, query_tokens: Sequence[str], k: int) -> list[tuple[int, float]]:
        scored = [(i, s) for i, s in enumerate(self.scores(query_tokens)) if s > 0]
        scored.sort(key=lambda pair: pair[1], reverse=True)
        return scored[:k]


def reciprocal_rank_fusion(
    rankings: Sequence[Sequence[Hashable]], k: int = 60
) -> list[tuple[Hashable, float]]:
    """Merge several ranked id lists. Items ranked high in many lists win."""
    fused: dict[Hashable, float] = {}
    for ranking in rankings:
        for rank, item in enumerate(ranking):
            fused[item] = fused.get(item, 0.0) + 1.0 / (k + rank + 1)
    return sorted(fused.items(), key=lambda pair: pair[1], reverse=True)
