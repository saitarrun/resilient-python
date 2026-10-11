"""Retry with exponential backoff and jitter.

Why this exists: naive fixed-delay retries synchronize clients and turn a
recovering dependency into a thundering herd. Exponential backoff spreads
load over time; full jitter decorrelates clients from each other. Both are
on by default here.

Typical use::

    from resilient import retry

    @retry(max_attempts=4, retry_on=(TimeoutError, ConnectionError))
    def fetch(url):
        ...

Rules of thumb enforced by the defaults:

- Never retry non-retryable errors. ``retry_on`` defaults to ``Exception``,
  but you should narrow it — retrying a ``ValueError`` from bad input just
  burns time.
- Bound the total budget with ``deadline`` so a slow dependency cannot hold
  a request (or a worker) hostage indefinitely.
"""
from __future__ import annotations

import functools
import random
import time
from typing import Any, Callable, Optional, Tuple, Type


def compute_delay(
    attempt: int,
    base_delay: float = 0.1,
    max_delay: float = 30.0,
    jitter: bool = True,
    rng: random.Random = random,
) -> float:
    """Delay in seconds before attempt ``attempt`` (1-based).

    Attempt 1 runs immediately, so this is the sleep *after* a failed
    attempt: ``compute_delay(1)`` ~= ``base_delay``, then it doubles each
    time up to ``max_delay``. With ``jitter`` the result is uniform in
    ``[0, delay]`` (full jitter), which keeps concurrent clients from
    retrying in lockstep.
    """
    if attempt < 1:
        raise ValueError("attempt must be >= 1")
    delay = min(base_delay * (2 ** (attempt - 1)), max_delay)
    if jitter:
        delay = rng.uniform(0.0, delay)
    return delay


def retry(
    _fn: Optional[Callable] = None,
    *,
    max_attempts: int = 3,
    base_delay: float = 0.1,
    max_delay: float = 30.0,
    jitter: bool = True,
    retry_on: Tuple[Type[BaseException], ...] = (Exception,),
    deadline: Optional[float] = None,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
    rng: Optional[random.Random] = None,
) -> Callable:
    """Decorator factory: retry the wrapped call on transient failure.

    Works bare (``@retry``) or parametrized (``@retry(max_attempts=5)``).

    - ``max_attempts``: total tries *including* the first one.
    - ``deadline``: total seconds budgeted across all attempts. If the next
      backoff would exceed it, the last error is raised immediately instead
      of sleeping past the budget.
    - ``sleep`` / ``clock`` / ``rng`` are injectable so tests stay
      deterministic without real waiting.
    """
    if max_attempts < 1:
        raise ValueError("max_attempts must be >= 1")
    if deadline is not None and deadline <= 0:
        raise ValueError("deadline must be positive")
    rng = rng if rng is not None else random.Random()

    def decorate(fn: Callable) -> Callable:
        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            start = clock()
            last_exc: Optional[BaseException] = None
            for attempt in range(1, max_attempts + 1):
                try:
                    return fn(*args, **kwargs)
                except retry_on as exc:
                    last_exc = exc
                    if attempt == max_attempts:
                        break
                    delay = compute_delay(attempt, base_delay, max_delay, jitter, rng)
                    if deadline is not None and clock() - start + delay > deadline:
                        break
                    sleep(delay)
                # Exceptions outside retry_on propagate immediately, unretried.
            assert last_exc is not None  # loop always runs at least once
            raise last_exc

        return wrapper

    if _fn is not None:
        return decorate(_fn)
    return decorate
