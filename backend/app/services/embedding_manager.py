import threading
from typing import Any


class EmbeddingManager:
    """Caching wrapper for embed_text from app.services.embedding_service."""

    def __init__(self) -> None:
        self.cache: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def get_embedding(self, text: str) -> list[float]:
        """
        Return a normalized cached embedding for the given text.

        If the text has already been embedded, return the cached vector.
        Otherwise, compute the embedding using embed_text and cache the result.
        """
        normalized_text = text.strip().lower()

        if not normalized_text:
            return [0.0] * 384

        with self._lock:
            if normalized_text in self.cache:
                print("[CACHE HIT]:", normalized_text)
                return self.cache[normalized_text]

        print("[CACHE MISS]:", normalized_text)
        from app.services.embedding_service import embed_text

        embedding = embed_text(normalized_text)

        with self._lock:
            self.cache[normalized_text] = embedding

        return embedding
