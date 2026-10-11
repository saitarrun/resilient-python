"""Idempotency keys: make retried operations safe to repeat.

Retries are only safe when the operation is idempotent — charging a card
twice because the *response* was lost is the classic failure. The fix used
across payments (Stripe), queues, and webhooks: the caller sends a stable
key with the request; the receiver executes once per key and replays the
stored result for duplicates.

Typical use::

    from resilient import MemoryIdempotencyStore, idempotent

    store = MemoryIdempotencyStore()

    @idempotent(store, ttl=24 * 3600)
    def charge(order_id, amount, idempotency_key):
        ...  # only runs once per key; repeats return the stored result

By default the key is derived from the call's arguments. Pass ``key=`` to
derive it yourself (e.g. from a request header)::

    @idempotent(store, key=lambda order_id, **kw: kw["idempotency_key"])
    def charge(order_id, **kw): ...

Scope notes, stated plainly:

- ``MemoryIdempotencyStore`` is per-process. Behind multiple workers, back
  the :class:`IdempotencyStore` protocol with Redis (``SET key value NX EX``)
  or your database.
- Concurrent duplicate *in-flight* calls can both execute with the memory
  store; true exactly-once needs an atomic check-and-set at the store.
"""
from __future__ import annotations

import functools
import threading
import time
from typing import Any, Callable, Dict, Hashable, Optional, Protocol, Tuple


class IdempotencyStore(Protocol):
    """Pluggable result store. ``get`` returns ``(hit, value)``."""

    def get(self, key: Hashable) -> Tuple[bool, Any]: ...
    def set(self, key: Hashable, value: Any, ttl: float) -> None: ...


class MemoryIdempotencyStore:
    """Thread-safe in-memory store with TTL expiry.

    Suitable for single-process services and tests. Expired entries are
    purged lazily on write and on read of the expired key.
    """

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._lock = threading.Lock()
        self._data: Dict[Hashable, Tuple[Any, float]] = {}

    def get(self, key: Hashable) -> Tuple[bool, Any]:
        with self._lock:
            entry = self._data.get(key)
            if entry is None:
                return False, None
            value, expires_at = entry
            if self._clock() >= expires_at:
                del self._data[key]
                return False, None
            return True, value

    def set(self, key: Hashable, value: Any, ttl: float) -> None:
        if ttl <= 0:
            raise ValueError("ttl must be positive")
        with self._lock:
            self._purge_locked()
            self._data[key] = (value, self._clock() + ttl)

    def _purge_locked(self) -> None:
        # Caller must hold self._lock.
        now = self._clock()
        expired = [k for k, (_, exp) in self._data.items() if now >= exp]
        for k in expired:
            del self._data[k]

    def __len__(self) -> int:
        with self._lock:
            self._purge_locked()
            return len(self._data)


def _default_key(*args: Any, **kwargs: Any) -> Hashable:
    try:
        hash((args, tuple(sorted(kwargs.items()))))
    except TypeError as exc:
        raise TypeError(
            "idempotency key must be hashable; pass key= explicitly "
            f"for unhashable arguments ({exc})"
        ) from exc
    return (args, tuple(sorted(kwargs.items())))


def idempotent(
    store: IdempotencyStore,
    *,
    ttl: float = 3600.0,
    key: Optional[Callable[..., Hashable]] = None,
) -> Callable:
    """Decorator: execute once per idempotency key, replay stored results.

    - ``store``: any :class:`IdempotencyStore` (memory, Redis, database).
    - ``ttl``: how long a key suppresses re-execution, in seconds.
    - ``key``: callable ``(*args, **kwargs) -> Hashable`` deriving the key;
      defaults to the call's arguments.
    """
    if ttl <= 0:
        raise ValueError("ttl must be positive")
    key_fn = key if key is not None else _default_key

    def decorate(fn: Callable) -> Callable:
        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            k = key_fn(*args, **kwargs)
            hit, value = store.get(k)
            if hit:
                return value
            result = fn(*args, **kwargs)
            store.set(k, result, ttl)
            return result

        return wrapper

    return decorate
