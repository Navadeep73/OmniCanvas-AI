# OmniCanvas AI — Multimodal Hybrid RAG 

**OmniCanvas AI** is an enterprise-grade **Multimodal Retrieval-Augmented Generation (RAG)** platform designed for document intelligence, page-accurate citation tracking, and automated guardrail safety. It combines **Okapi BM25 keyword matching** with **ChromaDB neural vector embeddings** via **Reciprocal Rank Fusion (RRF)**, powered by **FastAPI** and **Gemini 2.5 Flash / Groq**.

---

## 🌟 RAG Engine Highlights & Core Innovations

- 🧠 **Hybrid Retrieval Architecture**: Blends BM25 lexical keyword matching with ChromaDB vector embeddings using Reciprocal Rank Fusion ($RRF$) for optimal retrieval recall.
- 📑 **Parent/Child Hierarchical Chunking**: Preserves large parent passage contexts (~1200 chars) while indexing fine child sub-chunks (~350 chars) with exact page number tracking (`[p.1]`, `[p.2]`).
- 👁️ **Multimodal OCR & Vision Parsing**: Employs Gemini Vision to transcribe scanned PDF pages, extract complex tables into clean Markdown grids, and generate detailed visual captions for figures.
- 🛡️ **Production-Grade Guardrails**: 
  - **Input PII Redaction**: Automatically redacts credit cards (Luhn-checked), SSNs, emails, phone numbers, and API keys.
  - **Prompt Injection Defense**: Filters instruction-hijacking patterns from retrieved document passages.
  - **Claim Groundedness Scoring**: Calculates real-time claim support metrics (`95% well supported`) on every generated response.
- 🎨 **Interactive Live Canvas & 3D UI**: Features a live sandboxed execution canvas for HTML/SVG/Mermaid visualizers 

---

## 🏗️ Multimodal RAG Data Pipeline

```
                       [ Uploaded PDF / Image / Text ]
                                      │
                                      ▼
                       [ backend/rag/ingestion.py ]
                         • PyMuPDF Text & Table Extraction
                         • Gemini Vision OCR for Scanned Pages
                                      │
                                      ▼
                        [ backend/rag/chunking.py ]
                         • Hierarchical Parent/Child Passage Split
                         • Page Number Tracking & Metadata
                                      │
                   ┌──────────────────┴──────────────────┐
                   ▼                                     ▼
      [ backend/rag/bm25.py ]               [ backend/rag/embeddings.py ]
        • Okapi BM25 Indexing                 • Gemini Neural Embeddings
                   │                                     │
                   └──────────────────┬──────────────────┘
                                      ▼
                       [ backend/rag/vector_store.py ]
                         • ChromaDB Session-Isolated Store
                                      │
                                      ▼
                        [ backend/rag/retriever.py ]
                         • Reciprocal Rank Fusion (RRF) Search
                         • Reranking & Injection Defense
                                      │
                                      ▼
                     [ backend/services/chat_service.py ]
                         • PII Redaction & Prompt Context Injection
                         • SSE Token Streaming & Groundedness Verification
```

---

## ⚡ Technical Stack

### RAG & AI Engine Layer (`backend/rag/` & `backend/services/`)
- **Language & Framework**: Python 3.11+, FastAPI, Uvicorn, Pydantic v2.
- **Vector Database**: ChromaDB (Persistent Session-Isolated Vector Collections).
- **Keyword Search**: Custom Okapi BM25 + Reciprocal Rank Fusion (RRF).
- **LLM & Vision Models**: Google Gemini 2.5 Flash, Groq (GPT-OSS 120B), Google `gemini-embedding-001`.
- **Database & Storage**: SQLite 3 (WAL mode) + SQLAlchemy 2.0 ORM.

### Interactive UI Layer (`frontend/`)
- **3D Core**: Three.js WebGL Hologram with custom GLSL vertex displacement shaders.
- **Document Viewer**: PDF.js with golden thread SVG bezier citation animations.
- **Canvas Drawer**: Sandboxed iframe for live HTML, SVG, React JSX, and Mermaid diagrams.

---

## 📁 Repository Structure

```
omnicanvas/
├── backend/
│   ├── main.py              # FastAPI Web Server & Static File Mounts
│   ├── config.py            # Typed System Settings & Environment Variables
│   ├── db.py                # SQLite Database Connection & WAL Optimization
│   ├── models.py            # SQLAlchemy Models (ChatSession, Message, Document, Chunk)
│   ├── schemas.py           # Pydantic v2 Request/Response Validation Schemas
│   ├── routes/              # REST & SSE Endpoint Handlers (chat, upload, sessions, export)
│   ├── services/            # Chat Pipeline, Guardrails (PII/Injection), Artifact Extractor
│   └── rag/                 # 🧠 Dedicated Multimodal RAG Engine
│       ├── ingestion.py     # PDF, Image, Table & Vision OCR Processing
│       ├── chunking.py      # Parent/Child Passage Splitter with Page Tracking
│       ├── embeddings.py   # Gemini Neural Embedder & Hash Vector Fallback
│       ├── vector_store.py # ChromaDB Session-Isolated Vector Database
│       ├── bm25.py          # Okapi BM25 Search & Reciprocal Rank Fusion
│       └── retriever.py     # Master Hybrid RAG Search Orchestrator
└── frontend/                # Glassmorphism UI, Three.js 3D Orb, PDF Viewer, Canvas Drawer
```

---

## 💻 Quick Start & Local Setup

### 1. Clone Repository & Install Dependencies
```bash
git clone https://github.com/YOUR_USERNAME/omnicanvas.git
cd omnicanvas

# Create Virtual Environment
python -m venv .venv
source .venv/bin/activate       # On Windows: .\.venv\Scripts\activate
pip install -r backend/requirements.txt
```

### 2. Configure Environment Variables
Copy `.env.example` to `.env` and add your **Gemini API Key**:
```bash
cp .env.example .env
```
```env
GEMINI_API_KEY=your_gemini_api_key_here
```

### 3. Launch FastAPI Server
```bash
cd backend
python -m uvicorn main:app --reload --port 8000
```
Open **[http://localhost:8000](http://localhost:8000)** in your browser!

---

## 🐳 Docker Deployment

```bash
docker compose up --build -d
```
Open **[http://localhost:8000](http://localhost:8000)**!

---

## ☁️ Deployment on Render

1. Push your repository to **GitHub**.
2. Connect your repo to **[Render Dashboard](https://dashboard.render.com/)** as a **Web Service**.
3. Render automatically detects the **`Dockerfile`**.
4. Set Environment Variable: `GEMINI_API_KEY = your_key`.
5. Attach a **Persistent Disk** at path `/data` (1 GB size).
6. Click **Deploy Web Service**!

---

## 📜 License

MIT License. Developed for advanced RAG research and document intelligence applications.
