"""
config.py
---------
OmniCanvas Application Settings & Configuration Module.

WHAT THIS FILE DOES:
1. Loads environment variables from the `.env` file (e.g. GEMINI_API_KEY, GROQ_API_KEY).
2. Defines typed configuration settings (API keys, models, storage directories, rate limits).
3. Provides a single `settings` object that the rest of the application imports.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

# Suppress heavy machine learning framework logs that are not required
os.environ.setdefault("USE_TF", "0")
os.environ.setdefault("TRANSFORMERS_NO_TF", "1")
os.environ.setdefault("PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION", "python")

# Identify directory paths
BASE_DIR = Path(__file__).resolve().parent
ROOT_DIR = BASE_DIR.parent

# Load environment variables from .env file
for _candidate in (ROOT_DIR / ".env", BASE_DIR / ".env"):
    if _candidate.exists():
        load_dotenv(_candidate)


def _env(name: str, default: str = "") -> str:
    """Helper to read a string environment variable safely."""
    return os.environ.get(name, default).strip()


def _bool(name: str, default: bool) -> bool:
    """Helper to parse boolean flags (e.g. 'true', '1', 'yes')."""
    raw = _env(name)
    if not raw:
        return default
    return raw.lower() in {"1", "true", "yes", "on"}


def _int(name: str, default: int) -> int:
    """Helper to parse integer values safely with fallback defaults."""
    try:
        return int(_env(name) or default)
    except ValueError:
        return default


def _list(name: str, default: str) -> list[str]:
    """Helper to parse comma-separated string lists."""
    return [item.strip() for item in (_env(name) or default).split(",") if item.strip()]


@dataclass(frozen=True)
class Settings:
    """Immutable application settings data structure."""
    
    # AI Provider Keys & Models
    gemini_api_key: str        # Gemini API Key for LLM and embeddings
    groq_api_key: str          # Groq API Key for fast open-source model inference
    gemini_model: str          # Gemini model name (default: gemini-2.5-flash)
    groq_model: str            # Groq model name (default: openai/gpt-oss-120b)
    embedding_model: str       # Text embedding model name
    llm_timeout: int           # Maximum timeout in seconds for AI model requests

    # Storage Paths & Limits
    data_dir: Path             # Root data directory for SQLite & uploads
    database_url: str          # SQLite database connection URL
    chroma_path: str           # ChromaDB vector store directory path
    upload_dir: Path           # Uploaded PDF and file storage directory
    collection_name: str       # ChromaDB collection name for document vectors
    max_upload_mb: int         # Maximum upload file size in Megabytes

    # RAG Retrieval Configuration
    retrieve_k: int            # Number of top relevant document passages to retrieve
    candidate_pool: int        # Candidate pool size before reranking
    rewrite_queries: bool      # Whether to rewrite follow-up questions for search clarity
    rerank_mode: str           # Reranking mode ("none" or "llm")
    use_vision: bool           # Whether to use Gemini Vision for document images/tables
    vision_pages_limit: int    # Maximum pages to process with Vision model

    # Security & Guardrails
    redact_input_pii: bool     # Redact PII (Credit cards, SSNs, Emails) from user inputs
    cors_origins: list[str]    # Allowed CORS web origins
    rate_chat_per_min: int     # Maximum chat messages per minute per client
    rate_upload_per_min: int   # Maximum document uploads per minute per client

    @property
    def has_gemini(self) -> bool:
        """Returns True if Gemini API key is configured."""
        return bool(self.gemini_api_key)

    @property
    def has_groq(self) -> bool:
        """Returns True if Groq API key is configured."""
        return bool(self.groq_api_key)

    @property
    def max_upload_bytes(self) -> int:
        """Calculates maximum upload file size in bytes."""
        return self.max_upload_mb * 1024 * 1024

    @classmethod
    def load(cls) -> "Settings":
        """Loads and initializes settings from environment variables."""
        data_dir = Path(_env("DATA_DIR") or ROOT_DIR / "data").resolve()
        data_dir.mkdir(parents=True, exist_ok=True)

        upload_dir = Path(_env("UPLOAD_DIR") or data_dir / "uploads").resolve()
        upload_dir.mkdir(parents=True, exist_ok=True)

        db_default = f"sqlite:///{(data_dir / 'omnicanvas.db').as_posix()}"
        return cls(
            gemini_api_key=_env("GEMINI_API_KEY"),
            groq_api_key=_env("GROQ_API_KEY"),
            gemini_model=_env("GEMINI_MODEL", "gemini-2.5-flash"),
            groq_model=_env("GROQ_MODEL", "openai/gpt-oss-120b"),
            embedding_model=_env("EMBEDDING_MODEL", "models/gemini-embedding-001"),
            llm_timeout=_int("LLM_TIMEOUT", 90),
            data_dir=data_dir,
            database_url=_env("DATABASE_URL") or db_default,
            chroma_path=_env("CHROMA_PATH") or str(data_dir / "chroma"),
            upload_dir=upload_dir,
            collection_name=_env("COLLECTION_NAME", "omnicanvas_chunks"),
            max_upload_mb=_int("MAX_UPLOAD_MB", 25),
            retrieve_k=_int("RETRIEVE_K", 5),
            candidate_pool=_int("CANDIDATE_POOL", 24),
            rewrite_queries=_bool("REWRITE_QUERIES", True),
            rerank_mode=_env("RERANK_MODE", "none").lower(),
            use_vision=_bool("USE_VISION", True),
            vision_pages_limit=_int("VISION_PAGES_LIMIT", 6),
            redact_input_pii=_bool("REDACT_INPUT_PII", True),
            cors_origins=_list("CORS_ORIGINS", "http://localhost:8000,http://127.0.0.1:8000"),
            rate_chat_per_min=_int("RATE_LIMIT_CHAT_PER_MIN", 30),
            rate_upload_per_min=_int("RATE_LIMIT_UPLOAD_PER_MIN", 10),
        )


# Global singleton settings object
settings = Settings.load()
