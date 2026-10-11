"""Circuit breaker: stop calling a dependency that is clearly down.

Retries help with *transient* failures. When a dependency is down hard,
retrying just adds load to something that cannot answer — and burns your
own threads/timeouts waiting. A circuit breaker fails fast instead.

States::

    CLOSED --(failure_threshold consecutive failures)--> OPEN
      |                                                  |
      |<-----------(probe succeeds)-----------------------|
      |                                                  v
      +<---------------(probe fails)-------------- HALF_OPEN
        (recovery_timeout elapsed, one probe allowed)

Only exceptions matching ``expected_exception`` trip the breaker. A bug in
your own code (say, ``ValueError`` when you only expect ``IOError``) should
not open the circuit — it would never heal by waiting.

Typical use::

    from resilient import CircuitBreaker

    breaker = CircuitBreaker(failure_threshold=5, recovery_timeout=30.0)

    @breaker
    def call_payments_api(...): ...

    # or explicitly:
    breaker.call(call_payments_api, ...)
"""
from __future__ import annotations

import functools
import threading
import time
from enum import Enum
from typing import Any, Callable, Tuple, Type


class CircuitOpenError(Exception):
    """Raised when a call is rejected because the circuit is open."""


class CircuitState(Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreaker:
    """Thread-safe circuit breaker. See module docstring for the model."""

    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: float = 30.0,
        expected_exception: Tuple[Type[BaseException], ...] = (Exception,),
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if failure_threshold < 1:
            raise ValueError("failure_threshold must be >= 1")
        if recovery_timeout <= 0:
            raise ValueError("recovery_timeout must be positive")
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.expected_exception = expected_exception
        self._clock = clock
        self._lock = threading.Lock()
        self._state = CircuitState.CLOSED
        self._consecutive_failures = 0
        self._opened_at: float | None = None

    @property
    def state(self) -> CircuitState:
        """Current state, promoting OPEN to HALF_OPEN once timeout elapses."""
        with self._lock:
            self._maybe_half_open()
            return self._state

    @property
    def consecutive_failures(self) -> int:
        with self._lock:
            return self._consecutive_failures

    def _maybe_half_open(self) -> None:
        # Caller must hold self._lock.
        if (
            self._state is CircuitState.OPEN
            and self._opened_at is not None
            and self._clock() - self._opened_at >= self.recovery_timeout
        ):
            self._state = CircuitState.HALF_OPEN

    def _on_success(self) -> None:
        # Caller must hold self._lock.
        self._consecutive_failures = 0
        self._state = CircuitState.CLOSED
        self._opened_at = None

    def _on_failure(self) -> None:
        # Caller must hold self._lock.
        self._consecutive_failures += 1
        if (
            self._state is CircuitState.HALF_OPEN
            or self._consecutive_failures >= self.failure_threshold
        ):
            self._state = CircuitState.OPEN
            self._opened_at = self._clock()

    def call(self, fn: Callable, *args: Any, **kwargs: Any) -> Any:
        """Run ``fn`` through the breaker, raising :class:`CircuitOpenError`
        instead of calling it while the circuit is open."""
        with self._lock:
            self._maybe_half_open()
            if self._state is CircuitState.OPEN:
                raise CircuitOpenError(
                    f"circuit open: rejecting call to {getattr(fn, '__name__', fn)}"
                )
        try:
            result = fn(*args, **kwargs)
        except self.expected_exception:
            with self._lock:
                self._on_failure()
            raise
        # Unexpected exceptions propagate without tripping or resetting:
        # they say nothing about the dependency's health.
        with self._lock:
            self._on_success()
        return result

    def __call__(self, fn: Callable) -> Callable:
        """Use the breaker as a decorator: ``@breaker``."""

        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            return self.call(fn, *args, **kwargs)

        return wrapper

    def reset(self) -> None:
        """Force the breaker closed (useful in tests and ops runbooks)."""
        with self._lock:
            self._state = CircuitState.CLOSED
            self._consecutive_failures = 0
            self._opened_at = None
