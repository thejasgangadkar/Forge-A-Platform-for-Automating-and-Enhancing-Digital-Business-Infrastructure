"""RAG vector store (ChromaDB) keyed by workspace.

Stores business knowledge (scraped pages, descriptions) chunked with overlap,
and retrieves the most relevant chunks for a given workspace + query.
"""
import os
import re
import chromadb
from chromadb.config import Settings
from chromadb.utils import embedding_functions

DB_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "chroma_db")


def _chunk(text: str, size: int = 900, overlap: int = 150) -> list[str]:
    """Sentence-aware chunking with overlap."""
    text = re.sub(r"\s+", " ", text or "").strip()
    if not text:
        return []
    if len(text) <= size:
        return [text]
    chunks, start = [], 0
    while start < len(text):
        end = min(start + size, len(text))
        # try to break on a sentence boundary near the end
        slice_ = text[start:end]
        dot = slice_.rfind(". ")
        if dot > size * 0.5 and end < len(text):
            end = start + dot + 1
        chunks.append(text[start:end].strip())
        start = max(end - overlap, end) if end >= len(text) else end - overlap
    return [c for c in chunks if c]


class VectorStore:
    def __init__(self):
        self.client = chromadb.PersistentClient(
            path=DB_DIR, settings=Settings(anonymized_telemetry=False))
        self.embedding_fn = embedding_functions.DefaultEmbeddingFunction()
        self.col = self.client.get_or_create_collection(
            name="business_context", embedding_function=self.embedding_fn)

    def add_business_context(self, business_id: str, text: str, metadata: dict | None = None) -> bool:
        meta = dict(metadata or {})
        meta["business_id"] = business_id
        chunks = _chunk(text)
        if not chunks:
            return False
        # stable-ish unique ids
        import uuid
        ids, metas = [], []
        for i, _ in enumerate(chunks):
            ids.append(f"{business_id}_{uuid.uuid4().hex[:8]}_{i}")
            metas.append(dict(meta))
        self.col.add(documents=chunks, metadatas=metas, ids=ids)
        return True

    def copy_context(self, from_id: str, to_id: str) -> int:
        """Re-key context stored under a temporary id onto a workspace id."""
        try:
            res = self.col.get(where={"business_id": from_id})
        except Exception:
            return 0
        docs = res.get("documents") or []
        if not docs:
            return 0
        import uuid
        ids = [f"{to_id}_{uuid.uuid4().hex[:8]}_{i}" for i in range(len(docs))]
        metas = [{"business_id": to_id} for _ in docs]
        self.col.add(documents=docs, metadatas=metas, ids=ids)
        return len(docs)

    def delete_context(self, business_id: str) -> int:
        """Remove every chunk stored for a workspace. Returns the count deleted.

        Needed when a workspace is deleted: leaving the vectors behind would let a
        removed business keep answering RAG queries.
        """
        try:
            existing = self.col.get(where={"business_id": business_id})
            ids = existing.get("ids") or []
            if ids:
                self.col.delete(ids=ids)
            return len(ids)
        except Exception as e:
            print(f"[rag] delete_context failed for {business_id}: {e}")
            return 0

    def query_business_context(self, business_id: str, query: str, n_results: int = 4) -> list[str]:
        try:
            res = self.col.query(
                query_texts=[query], n_results=n_results,
                where={"business_id": business_id})
            docs = res.get("documents") or []
            return docs[0] if docs else []
        except Exception:
            return []


vector_store = VectorStore()
