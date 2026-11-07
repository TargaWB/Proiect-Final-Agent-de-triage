"""RAG cu ChromaDB, expus ca retrievere LangChain (apar ca spanuri RETRIEVER in Phoenix,
cu documentele si scorurile folosite -- adica "pe ce baza a decis agentul").

Doua colectii:
- history: tichetele istorice (data/tickets.csv) -> precedente + exemple few-shot + citari
- submitted: tichetele trimise in aplicatie (din SQLite) -> detectie de duplicate / "ai mai trimis"
"""

import csv
from typing import List

import chromadb
from langchain_core.callbacks import CallbackManagerForRetrieverRun
from langchain_core.documents import Document
from langchain_core.retrievers import BaseRetriever

from agent import db
from agent.config import CHROMA_PATH, FEW_SHOT_K, SIMILAR_DISTANCE, TICKETS_CSV
from agent.embeddings import embeddings

HISTORY = "history"
SUBMITTED = "submitted"
_client = None


def _chroma():
    global _client
    if _client is None:
        _client = chromadb.PersistentClient(path=CHROMA_PATH)
    return _client


def _collection(name):
    return _chroma().get_or_create_collection(name, metadata={"hnsw:space": "cosine"})


def history_text(t: dict) -> str:
    return f"{t['subject']}. {t['description']}"


def load_history() -> List[dict]:
    with open(TICKETS_CSV, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def build_index() -> dict:
    """Reconstruieste ambele colectii. SQLite ramane sursa de adevar, deci nu se pierde nimic."""
    for name in (HISTORY, SUBMITTED):
        try:
            _chroma().delete_collection(name)
        except Exception:
            pass
    rows = load_history()
    col = _collection(HISTORY)
    for i in range(0, len(rows), 64):
        batch = rows[i:i + 64]
        docs = [history_text(t) for t in batch]
        col.add(
            ids=[t["id"] for t in batch],
            documents=docs,
            embeddings=embeddings.embed_documents(docs),
            metadatas=[{
                "subject": t["subject"], "priority": t["true_priority"], "category": t["true_category"],
                "team": t["true_team"], "resolution": t.get("resolution", "")[:400],
            } for t in batch],
        )
    submitted = db.indexable_tickets()
    for t in submitted:
        index_submitted(t)
    return {"history": len(rows), "submitted": len(submitted)}


def ensure_index():
    if _collection(HISTORY).count() == 0:
        build_index()


def index_submitted(t: dict):
    _collection(SUBMITTED).upsert(ids=[str(t["id"])], documents=[t["text"]],
                                  embeddings=[embeddings.embed_query(t["text"])],
                                  metadatas=[{"code": db.code(t["id"])}])


def _query(name: str, text: str, k: int):
    col = _collection(name)
    n = col.count()
    if n == 0:
        return []
    res = col.query(query_embeddings=[embeddings.embed_query(text)], n_results=min(k, n))
    return [(res["ids"][0][i], res["documents"][0][i], res["metadatas"][0][i], res["distances"][0][i])
            for i in range(len(res["ids"][0]))]


class HistoryRetriever(BaseRetriever):
    """Top-k tichete istorice similare. Distanta cosinus in metadata (mai mic = mai similar)."""
    k: int = FEW_SHOT_K

    def _get_relevant_documents(self, query: str, *, run_manager: CallbackManagerForRetrieverRun) -> List[Document]:
        results = [Document(id=tid, page_content=doc, metadata={"id": tid, "distance": round(d, 4), **meta})
                   for tid, doc, meta, d in _query(HISTORY, query, self.k * 3)]
        # deduplica pe (subiect, echipa) -- pastreaza cel mai similar per pereche (distanta minima).
        # Un subiect generic ("Email login failed") poate avea mai multe cauze/solutii istorice
        # (VPN, parola expirata, Outlook corupt), fiecare rezolvata de alta echipa. Deduplicarea
        # doar pe subiect ar pastra o singura rezolvare si ar ascunde LLM-ului celelalte
        # posibilitati -- tocmai alternativele de care are nevoie ca sa aleaga corect.
        seen: dict[tuple, Document] = {}
        for doc in results:
            subj = doc.metadata.get("subject", doc.page_content[:80])
            team = doc.metadata.get("team", "")
            key = (subj, team)
            if key not in seen or doc.metadata["distance"] < seen[key].metadata["distance"]:
                seen[key] = doc
        ordered = sorted(seen.values(), key=lambda d: d.metadata["distance"])
        return ordered[:self.k]


class SubmittedRetriever(BaseRetriever):
    """Tichete trimise anterior in aplicatie, sub pragul de similaritate."""
    k: int = 3
    max_distance: float = SIMILAR_DISTANCE

    def _get_relevant_documents(self, query: str, *, run_manager: CallbackManagerForRetrieverRun) -> List[Document]:
        out = []
        for tid, doc, meta, d in _query(SUBMITTED, query, self.k):
            if d <= self.max_distance:
                out.append(Document(id=meta["code"], page_content=doc, metadata={"ticket_id": int(tid), "distance": round(d, 4), **meta}))
        return out


history_retriever = HistoryRetriever()
submitted_retriever = SubmittedRetriever()