"""Einfaches In-Memory-Rate-Limiting (z.B. für Login-Versuche)."""
from __future__ import annotations

import time
from collections import deque


class RateLimiter:
    """Sliding-Window-Limiter: max. ``max_attempts`` pro ``window_seconds`` je Schlüssel."""

    def __init__(self, max_attempts: int = 5, window_seconds: int = 300) -> None:
        self.max_attempts = max_attempts
        self.window = window_seconds
        self._hits: dict[str, deque[float]] = {}

    def allow(self, key: str, now: float | None = None) -> bool:
        """Registriert einen Versuch. False, wenn das Limit erreicht ist."""
        if now is None:
            now = time.monotonic()
        hits = self._hits.setdefault(key, deque())
        while hits and hits[0] <= now - self.window:
            hits.popleft()
        if len(hits) >= self.max_attempts:
            return False
        hits.append(now)
        return True

    def reset(self, key: str) -> None:
        """Setzt den Zähler zurück (z.B. nach erfolgreichem Login)."""
        self._hits.pop(key, None)

    def reset_all(self) -> None:
        self._hits.clear()
