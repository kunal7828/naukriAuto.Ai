"""Sentence-transformers embedding model (lazy-loaded on first use)."""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.database.db_record import DBItem

_model = None


def _get_model():
    """Lazy-load the SentenceTransformer model on first use."""
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer
        _model = SentenceTransformer("all-MiniLM-L6-v2")
    return _model


def get_embedding(text: str) -> list[float]:
    """Encode text into a vector embedding."""
    model = _get_model()
    return model.encode(text).tolist()


def find_similar(
    question_emb: list[float],
    db: list["DBItem"],
    threshold: float = 0.85,
) -> str | None:
    """Return the best cached answer whose embedding is above ``threshold``."""
    from sklearn.metrics.pairwise import cosine_similarity

    best_score = 0.0
    best_answer: str | None = None
    for item in db:
        emb = item.get("embedding")
        if not emb:
            continue
        try:
            score = cosine_similarity([question_emb], [emb])[0][0]
        except Exception:
            continue
        if score > best_score:
            best_score = score
            best_answer = item.get("answer")
    if best_score >= threshold:
        return best_answer
    return None