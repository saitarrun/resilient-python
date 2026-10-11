"""Token bucket rate limiter: smooth bursts, protect shared resources.

The bucket holds up to ``capacity`` tokens and refills at ``rate`` tokens
per second. Each operation consumes tokens; when the bucket is empty the
caller waits (or gets ``False``) instead of hammering the downstream.

Why a bucket and not a fixed window: fixed windows allow ``2 * limit``
requests at a boundary (the classic end-of-window burst). A bucket bounds
the burst to ``capacity`` at *every* instant.

Typical use::

    from resilient import TokenBucket

    # 100 requests/second sustained, bursts up to 20
    bucket = TokenBucket(rate=100.0, capacity=20.0)

    if bucket.try_acquire():
        call_external_api()
    else:
        return 429

    # or block until allowed (with an optional timeout):
    bucket.acquire(timeout=5.0)
"""
from __future__ import annotations

import threading
import time
from typing import Callable


class TokenBucket:
    """Thread-safe token bucket. See module docstring for the model."""

    def __init__(
        self,
        rate: float,
        capacity: float,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if rate <= 0:
            raise ValueError("rate must be positive")
        if capacity <= 0:
            raise ValueError("capacity must be positive")
        self.rate = rate
        self.capacity = capacity
        self._clock = clock
        self._lock = threading.Lock()
        self._tokens = capacity
        self._updated = clock()

    @property
    def available(self) -> float:
        """Tokens currently available (refills lazily)."""
        with self._lock:
            self._refill()
            return self._tokens

    def _refill(self) -> None:
        # Caller must hold self._lock.
        now = self._clock()
        elapsed = now - self._updated
        if elapsed > 0:
            self._tokens = min(self.capacity, self._tokens + elapsed * self.rate)
            self._updated = now

    def try_acquire(self, tokens: float = 1.0) -> bool:
        """Take ``tokens`` if available right now; never blocks."""
        if tokens <= 0:
            raise ValueError("tokens must be positive")
        if tokens > self.capacity:
            raise ValueError("tokens requested exceeds bucket capacity")
        with self._lock:
            self._refill()
            if self._tokens >= tokens:
                self._tokens -= tokens
                return True
            return False

    def acquire(self, tokens: float = 1.0, timeout: float | None = None) -> bool:
        """Block until ``tokens`` are available.

        Returns ``True`` once acquired, ``False`` if ``timeout`` seconds
        pass first. ``timeout=None`` waits indefinitely, ``timeout=0``
        behaves like :meth:`try_acquire`.
        """
        if tokens <= 0:
            raise ValueError("tokens must be positive")
        if tokens > self.capacity:
            raise ValueError("tokens requested exceeds bucket capacity")
        if timeout is not None and timeout < 0:
            raise ValueError("timeout must be non-negative")
        deadline = None if timeout is None else self._clock() + timeout
        while True:
            with self._lock:
                self._refill()
                if self._tokens >= tokens:
                    self._tokens -= tokens
                    return True
                wait = (tokens - self._tokens) / self.rate
            if deadline is not None:
                remaining = deadline - self._clock()
                if remaining <= 0:
                    return False
                wait = min(wait, remaining)
            # Sleep in small slices so we notice refills promptly without
            # busy looping.
            time.sleep(min(wait, 0.05))
