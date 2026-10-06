"""
services/guardrails.py
----------------------
Input and output guardrails. Pure Python, fully unit-tested.

Input
  * scrub_pii          - redact emails, phones, cards (Luhn-checked), national IDs, API keys
  * detect_injection   - spot instruction-hijacking text (used on retrieved passages)

Output
  * extract_citations / validate_citations - every [S#] tag must point at a real source
  * groundedness       - claim-by-claim check that statements are supported by the sources

Groundedness here is a *transparent heuristic* (content-word coverage plus number
matching), not an LLM judge. It is cheap, deterministic, and good at catching
unsupported numbers and off-topic claims. It cannot catch every subtle paraphrase
error, and the UI words it as "Check this answer", never as a guarantee.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from rag.bm25 import tokenize


# --------------------------------------------------------------------------- PII


def _luhn_ok(candidate: str) -> bool:
    digits = [int(c) for c in re.sub(r"\D", "", candidate)]
    if not 13 <= len(digits) <= 19:
        return False
    checksum = 0
    for i, digit in enumerate(reversed(digits)):
        if i % 2 == 1:
            digit *= 2
            if digit > 9:
                digit -= 9
        checksum += digit
    return checksum % 10 == 0


# Order matters: secrets first so their digits are not mistaken for phone numbers.
_PII_RULES: list[tuple[str, re.Pattern[str], object]] = [
    ("api_key", re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b"), None),
    ("api_key", re.compile(r"\bgsk_[A-Za-z0-9]{20,}\b"), None),
    ("api_key", re.compile(r"\bsk-[A-Za-z0-9_\-]{20,}\b"), None),
    ("api_key", re.compile(r"\bAQ\.[A-Za-z0-9_\-]{30,}\b"), None),
    ("email", re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b"), None),
    ("card", re.compile(r"(?<!\d)(?:\d[ \-]?){13,19}(?!\d)"), _luhn_ok),
    ("ssn", re.compile(r"(?<!\d)\d{3}-\d{2}-\d{4}(?!\d)"), None),
    ("aadhaar", re.compile(r"(?<!\d)(?<!\d[ \-])\d{4}[ \-]\d{4}[ \-]\d{4}(?!\d)(?![ \-]\d)"), None),
    (
        "phone",
        re.compile(r"(?<!\d)(?:\+\d{1,3}[\s.\-]?)?(?:\(\d{3}\)|\d{3})[\s.\-]\d{3}[\s.\-]\d{4}(?!\d)"),
        None,
    ),
    ("phone", re.compile(r"(?<!\d)(?:\+91[\s\-]?)?[6-9]\d{9}(?!\d)"), None),
]


def scrub_pii(text: str) -> tuple[str, list[str]]:
    """Return (clean_text, sorted unique labels that were redacted)."""
    if not text:
        return "", []

    found: set[str] = set()
    cleaned = text
    for label, pattern, validator in _PII_RULES:

        def _replace(match: re.Match[str], label=label, validator=validator) -> str:
            if validator is not None and not validator(match.group(0)):
                return match.group(0)
            found.add(label)
            return f"[REDACTED_{label.upper()}]"

        cleaned = pattern.sub(_replace, cleaned)
    return cleaned, sorted(found)


# ---------------------------------------------------------------------- injection

_INJECTION_PATTERNS = [
    r"ignore\s+(?:all\s+|any\s+|the\s+)?(?:previous|prior|above|earlier|preceding)\s+(?:instructions?|prompts?|rules|messages)",
    r"disregard\s+(?:all\s+|any\s+|the\s+)?(?:previous|prior|above|earlier|system)?\s*(?:instructions?|prompts?|rules)",
    r"forget\s+(?:all\s+|everything\s+|your\s+)?(?:previous\s+|prior\s+)?(?:instructions?|rules|training)",
    r"(?:reveal|show|print|repeat|output)\s+(?:me\s+)?(?:your|the)\s+(?:system|hidden|initial)\s+(?:prompt|instructions?)",
    r"\byou\s+are\s+now\s+(?:a|an|in)\b",
    r"\bnew\s+instructions?\s*:",
    r"\bsystem\s+prompt\s*:",
    r"<\s*/?\s*system\s*>",
    r"\[\s*system\s*\]",
    r"\bdeveloper\s+mode\b",
    r"\bjailbreak\b",
    r"do\s+not\s+(?:tell|inform|mention\s+(?:this\s+)?to)\s+the\s+user",
]
_INJECTION_RE = [re.compile(p, re.IGNORECASE) for p in _INJECTION_PATTERNS]


@dataclass
class InjectionResult:
    score: int = 0
    matches: list[str] = field(default_factory=list)

    @property
    def flagged(self) -> bool:
        return self.score > 0


def detect_injection(text: str) -> InjectionResult:
    """Count instruction-hijack patterns. Retrieved passages that match are dropped.

    Trade-off: a security paper that quotes "ignore previous instructions" as an
    example will be dropped too. We surface the dropped count to the user.
    """
    result = InjectionResult()
    if not text:
        return result
    for pattern in _INJECTION_RE:
        match = pattern.search(text)
        if match:
            result.score += 1
            result.matches.append(match.group(0)[:60])
    return result


# ---------------------------------------------------------------------- citations

_CITE_GROUP = re.compile(r"\[(S\d+(?:\s*[,;]\s*S\d+)*)\]")


def extract_citations(answer: str) -> list[str]:
    """Unique source refs in order of first appearance, e.g. ['S2', 'S1']."""
    seen: list[str] = []
    for group in _CITE_GROUP.findall(answer or ""):
        for ref in re.split(r"[,;]", group):
            ref = ref.strip()
            if ref and ref not in seen:
                seen.append(ref)
    return seen


def validate_citations(answer: str, valid_refs: set[str]) -> tuple[list[str], list[str]]:
    cited = extract_citations(answer)
    return [r for r in cited if r in valid_refs], [r for r in cited if r not in valid_refs]


# ------------------------------------------------------------------- groundedness

_BEYOND = re.compile(r"\*{0,2}\s*beyond\s+your\s+(?:pdf|document|file|upload)", re.IGNORECASE)
_FENCE = re.compile(r"```.*?```", re.DOTALL)
_SENTENCES = re.compile(r"(?<=[.!?])\s+")
_NUMBER = re.compile(r"\d[\d,]*\.?\d*")


@dataclass
class GroundednessResult:
    score: float | None  # None = nothing to check
    supported: int = 0
    total: int = 0
    unsupported: list[str] = field(default_factory=list)


def _strip_markdown(text: str) -> str:
    text = re.sub(r"\[S\d+(?:\s*[,;]\s*S\d+)*\]", "", text)
    text = re.sub(r"[*_`>#|]", " ", text)
    text = re.sub(r"^\s*[-+]\s+|^\s*\d+\.\s+", "", text, flags=re.MULTILINE)
    return re.sub(r"\s+", " ", text).strip()


def split_claims(answer: str) -> list[str]:
    """Checkable sentences: skips code, the 'Beyond your PDF' section, and fragments."""
    body = _FENCE.sub(" ", answer or "")
    marker = _BEYOND.search(body)
    if marker:
        body = body[: marker.start()]

    claims = []
    for paragraph in re.split(r"\n\s*\n|\n(?=\s*(?:[-*+]|\d+\.)\s)", body):
        cleaned = _strip_markdown(paragraph)
        for sentence in _SENTENCES.split(cleaned):
            if len(sentence.split()) >= 6:
                claims.append(sentence.strip())
    return claims


def _numbers(text: str) -> set[str]:
    return {n.replace(",", "").rstrip(".") for n in _NUMBER.findall(text)}


def groundedness(answer: str, context_texts: list[str]) -> GroundednessResult:
    if not context_texts:
        return GroundednessResult(score=None)

    claims = split_claims(answer)
    context_tokens = [set(tokenize(t)) for t in context_texts]
    union_tokens = set().union(*context_tokens) if context_tokens else set()
    context_numbers = _numbers(" ".join(context_texts))

    supported = 0
    checked = 0
    unsupported: list[str] = []
    for claim in claims:
        words = set(tokenize(claim))
        if len(words) < 3:
            continue
        checked += 1

        best_single = max((len(words & ctx) / len(words) for ctx in context_tokens), default=0.0)
        union_cover = len(words & union_tokens) / len(words)
        covered = best_single >= 0.5 or union_cover >= 0.65

        claim_numbers = _numbers(claim)
        numbers_ok = not claim_numbers or claim_numbers <= context_numbers

        if covered and numbers_ok:
            supported += 1
        else:
            unsupported.append(claim[:220])

    if checked == 0:
        return GroundednessResult(score=None)
    return GroundednessResult(
        score=round(supported / checked, 2),
        supported=supported,
        total=checked,
        unsupported=unsupported[:3],
    )
