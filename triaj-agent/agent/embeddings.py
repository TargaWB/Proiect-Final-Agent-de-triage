"""Embedding local, multilingv (RO + EN), prin fastembed/ONNX: fara torch, fara API, fara cost.
Expus ca langchain Embeddings, ca sa fie folosit de framework (si urmarit in Phoenix)."""

from typing import List

import numpy as np
from langchain_core.embeddings import Embeddings

from agent.config import EMBED_MODEL

_model = None


def _get():
    global _model
    if _model is None:
        from fastembed import TextEmbedding
        _model = TextEmbedding(EMBED_MODEL)
    return _model


def _embed(texts: List[str]) -> List[List[float]]:
    v = np.array(list(_get().embed(list(texts))), dtype=np.float32)
    v /= np.linalg.norm(v, axis=1, keepdims=True)
    return v.tolist()


class LocalEmbeddings(Embeddings):
    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        return _embed(texts)

    def embed_query(self, text: str) -> List[float]:
        return _embed([text])[0]


embeddings = LocalEmbeddings()
