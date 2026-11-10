"""JSON-backed Q&A cache with exact-match and optional semantic lookup."""
import json
import os
from typing import Iterable

from app.database.db_record import DBItem

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DEFAULT_DB_PATH = os.path.join(BASE_DIR, "data", "db.json")

# In-memory cache
_db_cache: list[DBItem] | None = None
_db_path: str | None = None


def _resolve_path(path: str | None) -> str:
    if path is None:
        return DEFAULT_DB_PATH
    if os.path.isabs(path):
        return path
    return os.path.join(BASE_DIR, path)


def load_db(path: str | None = None) -> None:
    """Load the database from disk into the in-memory cache."""
    global _db_cache, _db_path
    resolved = _resolve_path(path)
    _db_path = resolved
    if _db_cache is not None:
        return  # already loaded
    try:
        with open(resolved, "r", encoding="utf-8") as f:
            data = json.load(f)
            _db_cache = data if isinstance(data, list) else []
    except (FileNotFoundError, json.JSONDecodeError):
        _db_cache = []


def get_db(path: str | None = None) -> list[DBItem]:
    load_db(path)
    return _db_cache  # type: ignore[return-value]


def add_item(item: DBItem, path: str | None = None) -> None:
    load_db(path)
    _db_cache.append(item)


def save_db(path: str | None = None) -> None:
    if _db_cache is None:
        return
    resolved = path or _db_path or _resolve_path(None)
    os.makedirs(os.path.dirname(resolved), exist_ok=True)
    with open(resolved, "w", encoding="utf-8") as f:
        json.dump(_db_cache, f, indent=2, default=str)


def findAnswer(normalizedQuestion: str, path: str | None = None) -> str | None:
    """Exact-match lookup by normalized question string."""
    for item in get_db(path):
        if item.get("normalized") == normalizedQuestion:
            return item.get("answer")
    return None


def findAnswerSemantic(
    question_embedding: list[float],
    threshold: float = 0.85,
    path: str | None = None,
) -> str | None:
    """Semantic similarity lookup using precomputed embeddings."""
    try:
        from app.ai.embedding_model import find_similar
    except Exception:
        return None
    return find_similar(question_embedding, get_db(path), threshold=threshold)


def reset_cache() -> None:
    """Clear the in-memory cache (mainly for tests)."""
    global _db_cache
    _db_cache = None


def all_items(path: str | None = None) -> Iterable[DBItem]:
    return get_db(path)