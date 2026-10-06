"""
services/model_service.py
-------------------------
LLM access: provider factory, streaming, one-shot completion and vision captions.

A provider that is selected but not configured raises `ModelUnavailable` with a
message the UI can show. We never silently fall back to a different provider.
"""

from __future__ import annotations

import base64
import json
import re
from typing import Any, Iterator

from config import settings


class ModelUnavailable(RuntimeError):
    """Raised when the chosen provider has no key or its package is missing."""


def provider_status() -> dict[str, dict[str, Any]]:
    return {
        "gemini": {"configured": settings.has_gemini, "model": settings.gemini_model, "label": "Gemini 2.5 Flash"},
        "groq": {"configured": settings.has_groq, "model": settings.groq_model, "label": "GPT-OSS 120B on Groq"},
    }


def get_chat_model(provider: str = "gemini", temperature: float = 0.4) -> Any:
    name = (provider or "gemini").lower()

    if name == "groq":
        if not settings.has_groq:
            raise ModelUnavailable("Groq isn't configured. Add GROQ_API_KEY to your .env file, or switch to Gemini.")
        try:
            from langchain_groq import ChatGroq
        except ImportError as exc:
            raise ModelUnavailable("Install langchain-groq to use Groq.") from exc
        return ChatGroq(
            api_key=settings.groq_api_key,
            model=settings.groq_model,
            temperature=temperature,
            timeout=settings.llm_timeout,
            max_retries=2,
        )

    if not settings.has_gemini:
        raise ModelUnavailable("Gemini isn't configured. Add GEMINI_API_KEY to your .env file.")
    try:
        from langchain_google_genai import ChatGoogleGenerativeAI
    except ImportError as exc:
        raise ModelUnavailable("Install langchain-google-genai to use Gemini.") from exc
    return ChatGoogleGenerativeAI(
        google_api_key=settings.gemini_api_key,
        model=settings.gemini_model,
        temperature=temperature,
        timeout=settings.llm_timeout,
        max_retries=2,
    )


def chunk_text(chunk: Any) -> str:
    """Normalise a streamed chunk: providers return str or a list of content blocks."""
    content = getattr(chunk, "content", chunk)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and block.get("type", "text") == "text":
                parts.append(block.get("text", ""))
        return "".join(parts)
    return ""


def stream_text(model: Any, messages: list) -> Iterator[str]:
    for chunk in model.stream(messages):
        piece = chunk_text(chunk)
        if piece:
            yield piece


def complete_text(provider: str, messages: list, temperature: float = 0.0) -> str:
    model = get_chat_model(provider, temperature)
    return chunk_text(model.invoke(messages)).strip()


def pick_utility_provider(preferred: str) -> str:
    """Cheap helper calls (rewrite, rerank) use whichever provider is configured."""
    if preferred == "groq" and settings.has_groq:
        return "groq"
    return "gemini" if settings.has_gemini else ("groq" if settings.has_groq else preferred)


def describe_image(png_bytes: bytes, prompt: str, mime: str = "image/png") -> str:
    """Caption or transcribe an image with Gemini vision. Returns '' if unavailable."""
    if not settings.has_gemini:
        return ""
    from langchain_core.messages import HumanMessage

    model = get_chat_model("gemini", 0.0)
    data_uri = f"data:{mime};base64,{base64.b64encode(png_bytes).decode('ascii')}"
    message = HumanMessage(
        content=[{"type": "text", "text": prompt}, {"type": "image_url", "image_url": {"url": data_uri}}]
    )
    return chunk_text(model.invoke([message])).strip()


def parse_index_list(raw: str) -> list[int]:
    """Parse a model reply like '[3,1,2]' into zero-based indices. Tolerant of noise."""
    match = re.search(r"\[[\d,\s]*\]", raw or "")
    if not match:
        return []
    try:
        return [int(n) - 1 for n in json.loads(match.group(0))]
    except (ValueError, TypeError):
        return []
