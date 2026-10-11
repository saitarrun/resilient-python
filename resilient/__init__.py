"""resilient — production grade resilience patterns for Python.

Four primitives that every distributed system ends up reimplementing:

- :mod:`resilient.retry` — retries with exponential backoff and jitter
- :mod:`resilient.circuit` — circuit breaker with half-open probing
- :mod:`resilient.ratelimit` — token bucket rate limiter
- :mod:`resilient.idempotency` — idempotency keys for exactly-once effects

Dependency free. Standard library only.
"""

from resilient.circuit import CircuitBreaker, CircuitOpenError, CircuitState
from resilient.idempotency import (
    IdempotencyStore,
    MemoryIdempotencyStore,
    idempotent,
)
from resilient.ratelimit import TokenBucket
from resilient.retry import compute_delay, retry

__all__ = [
    "CircuitBreaker",
    "CircuitOpenError",
    "CircuitState",
    "IdempotencyStore",
    "MemoryIdempotencyStore",
    "TokenBucket",
    "compute_delay",
    "idempotent",
    "retry",
]

__version__ = "0.1.0"
