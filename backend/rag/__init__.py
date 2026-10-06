"""
backend/rag
-----------
OmniCanvas Dedicated Retrieval-Augmented Generation (RAG) Engine.

MODULE CONTENTS:
1. ingestion.py    - Document processing, OCR, Vision captions & text extraction.
2. chunking.py     - Parent/Child chunking with page number tracking.
3. embeddings.py   - Gemini neural embeddings & offline hash vector embeddings.
4. vector_store.py - ChromaDB session-isolated vector database.
5. bm25.py         - Okapi BM25 keyword search & Reciprocal Rank Fusion (RRF).
6. retriever.py    - Master hybrid search orchestrator.
"""
