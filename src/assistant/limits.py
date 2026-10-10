"""Tiny in-memory sliding-window rate limiter (one per browser session)."""
from __future__ import annotations

import time
from collections import deque


class RateLimiter:
    def __init__(self, max_calls: int, per_seconds: float = 3600.0, clock=time.monotonic):
        self.max, self.per, self.clock, self._hits = max_calls, per_seconds, clock, deque()

    def allow(self) -> bool:
        now = self.clock()
        while self._hits and now - self._hits[0] >= self.per:
            self._hits.popleft()
        if len(self._hits) >= self.max:
            return False
        self._hits.append(now)
        return True
