"""
services/artifacts.py
---------------------
Pulls previewable code blocks (HTML, SVG, JSX, Mermaid, ...) out of a model reply.

Only languages the canvas can actually render become artifacts. Everything else
(Python, SQL, shell...) stays an ordinary code block with a copy button.
"""

from __future__ import annotations

import hashlib
import re

RENDERABLE = {
    "html": "html",
    "htm": "html",
    "svg": "svg",
    "css": "css",
    "javascript": "javascript",
    "js": "javascript",
    "jsx": "jsx",
    "react": "jsx",
    "mermaid": "mermaid",
}

_FENCE = re.compile(r"```([\w+\-]*)[^\n]*\n(.*?)```", re.DOTALL)
_TITLE = re.compile(r"<title>(.*?)</title>", re.IGNORECASE | re.DOTALL)

_LABELS = {
    "html": "Interactive page",
    "svg": "Vector graphic",
    "css": "Style preview",
    "javascript": "Script output",
    "jsx": "React component",
    "mermaid": "Diagram",
}


def extract_artifacts(text: str) -> list[dict]:
    artifacts: list[dict] = []
    for match in _FENCE.finditer(text or ""):
        lang = RENDERABLE.get((match.group(1) or "").lower())
        code = match.group(2).strip("\n")
        if not lang or len(code.strip()) < 40:
            continue

        title = _LABELS[lang]
        if lang == "html":
            found = _TITLE.search(code)
            if found and found.group(1).strip():
                title = found.group(1).strip()[:60]

        digest = hashlib.sha1(code.encode("utf-8")).hexdigest()[:8]
        artifacts.append({"id": f"a{len(artifacts) + 1}-{digest}", "lang": lang, "title": title, "code": code})
    return artifacts
