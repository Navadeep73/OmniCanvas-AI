"""
main.py
-------
OmniCanvas FastAPI Server Entrypoint.

WHAT THIS FILE DOES:
1. Initializes the FastAPI web server instance.
2. Configures CORS middleware for browser access.
3. Sets security headers (X-Content-Type-Options, Referrer-Policy, Frame-Options).
4. Registers all API route modules (`meta`, `sessions`, `documents`, `upload`, `chat`, `export`).
5. Mounts and serves the frontend user interface (`index.html`, `/js`, `/css`, `/assets`).

TO RUN LOCALLY:
    cd backend
    uvicorn main:app --reload --port 8000
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from config import settings
from db import init_db
from routes import chat, documents, export, meta, sessions, upload

# Configure server logging format
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("omnicanvas")

# Resolve absolute path to frontend static directory
FRONTEND_DIR = (Path(__file__).resolve().parent.parent / "frontend").resolve()


@asynccontextmanager
async def lifespan(_: FastAPI):
    """Application lifespan context manager: initializes database on startup."""
    init_db()
    log.info(
        "OmniCanvas Server Ready. Gemini Key Configured=%s, Groq Key Configured=%s, Data Path=%s",
        settings.has_gemini, settings.has_groq, settings.data_dir,
    )
    yield


# Initialize FastAPI application instance
app = FastAPI(
    title="OmniCanvas AI",
    description="3D Holographic AI Document Assistant & Live Coding Canvas.",
    version="2.0.0",
    lifespan=lifespan,
)

# Configure Cross-Origin Resource Sharing (CORS)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["Content-Type"],
)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    """HTTP middleware to attach essential security headers to every response."""
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Permissions-Policy", "microphone=(self), camera=(), geolocation=()")
    if request.url.path.startswith(("/js/", "/css/")):
        response.headers.setdefault("Cache-Control", "no-cache")
    return response


# Register all API endpoints
for module in (meta, sessions, documents, upload, chat, export):
    app.include_router(module.router)


@app.exception_handler(Exception)
async def unhandled(_: Request, exc: Exception):
    """Global exception handler for catching unhandled server errors."""
    log.exception("Unhandled error occurred", exc_info=exc)
    return JSONResponse(status_code=500, content={"detail": "Something went wrong on the server."})


# Mount static frontend files when frontend directory exists
if FRONTEND_DIR.exists():
    for folder in ("css", "js", "assets"):
        path = FRONTEND_DIR / folder
        if path.exists():
            app.mount(f"/{folder}", StaticFiles(directory=path), name=folder)

    @app.get("/", include_in_schema=False)
    def index():
        """Serves the main OmniCanvas web application HTML interface."""
        return FileResponse(FRONTEND_DIR / "index.html")

    @app.get("/favicon.svg", include_in_schema=False)
    def favicon():
        """Serves the application logo icon."""
        return FileResponse(FRONTEND_DIR / "assets" / "logo.svg", media_type="image/svg+xml")
else:

    @app.get("/", include_in_schema=False)
    def no_frontend():
        """Fallback status endpoint if frontend folder is absent."""
        return {"message": "OmniCanvas API is running."}


# Direct execution entrypoint
if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=False)
