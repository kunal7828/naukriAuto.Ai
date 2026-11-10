"""Repository pattern over the local Q&A cache.

Provides exact-match and semantic-similarity lookup, plus persistence.
"""
from app.utils.process_question import build_query, normalize
from app.database.db_record import makeDBItem
from app.database.db import (
    findAnswer,
    findAnswerSemantic,
    add_item,
    save_db,
    get_db,
)
from app.ai.embedding_model import get_embedding


def findAnswerFromPreviousResponse(
    question: str,
    available_options: list[str] | None,
    semantic_threshold: float | None = None,
) -> str | None:
    """Look up a cached answer for the given question + options.

    Falls back to semantic similarity when ``semantic_threshold`` is set
    and an exact match is not found.
    """
    full_question = build_query(question, available_options)
    normalized_question = normalize(full_question)
    answer = findAnswer(normalized_question)
    if answer is not None:
        return answer

    if semantic_threshold is not None:
        try:
            question_embedding = get_embedding(normalized_question)
        except Exception:
            question_embedding = None
        if question_embedding:
            return findAnswerSemantic(question_embedding, threshold=semantic_threshold)
    return None


def saveResponseToDB(
    question: str,
    available_options: list[str] | None,
    answer: str,
) -> None:
    full_question = build_query(question, available_options)
    normalized_question = normalize(full_question)
    question_embedding = get_embedding(normalized_question)
    db_item = makeDBItem(question, normalized_question, question_embedding, answer)
    add_item(db_item)
    save_db()


def ensure_db_exists(path: str | None = None) -> None:
    """Ensure the database file exists; create it if missing."""
    import os
    import json

    from app.database.db import _resolve_path  # type: ignore[attr-defined]

    resolved = _resolve_path(path)
    if not os.path.exists(resolved):
        os.makedirs(os.path.dirname(resolved), exist_ok=True)
        with open(resolved, "w", encoding="utf-8") as f:
            json.dump([], f)