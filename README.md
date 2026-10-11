# resilient-python

[![Python 3.9+](https://img.shields.io/badge/python-3.9%2B-blue)](https://www.python.org)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![No dependencies](https://img.shields.io/badge/dependencies-zero-brightgreen)]()

Production grade resilience patterns for Python — the four primitives every
distributed system ends up reimplementing, done once and done right.
Dependency free, fully tested, standard library only.

| Pattern | Module | One line |
|---|---|---|
| Retries | `resilient.retry` | Exponential backoff with full jitter, retry filters, total deadline |
| Circuit breaker | `resilient.circuit` | Fail fast when a dependency is down; half open probing for recovery |
| Rate limiting | `resilient.ratelimit` | Token bucket — smooth bursts, no boundary stampedes |
| Idempotency | `resilient.idempotency` | Keys that make retried operations safe to repeat |

## Install

```bash
pip install resilient-python
```

Or vendor the single `resilient/` package — it has zero dependencies.

## Quickstart

```python
from resilient import retry, CircuitBreaker, TokenBucket, MemoryIdempotencyStore, idempotent

# 1. Retry transient failures — backoff with jitter, bounded budget
@retry(max_attempts=4, retry_on=(TimeoutError, ConnectionError), deadline=10.0)
def fetch(url): ...

# 2. Stop calling what is clearly down
breaker = CircuitBreaker(failure_threshold=5, recovery_timeout=30.0)

@breaker
def call_payments_api(...): ...

# 3. Protect a shared downstream: 100 req/s sustained, bursts of 20
bucket = TokenBucket(rate=100.0, capacity=20.0)
if not bucket.try_acquire():
    return 429

# 4. Make retries safe: execute once per key, replay the stored result
store = MemoryIdempotencyStore()

@idempotent(store, ttl=24 * 3600)
def charge(order_id, amount, idempotency_key): ...
```

## The patterns, in depth

### Retry — `resilient.retry`

Naive fixed delay retries synchronize clients and turn a recovering
dependency into a thundering herd. This defaults to exponential backoff
with **full jitter** (each sleep uniform in `[0, delay]`), which
decorrelates concurrent clients.

```python
from resilient import retry, compute_delay

@retry(
    max_attempts=5,
    base_delay=0.2,      # first backoff; doubles each attempt
    max_delay=30.0,      # caps the exponential growth
    jitter=True,         # decorrelate clients (default on)
    retry_on=(TimeoutError, ConnectionError),  # narrow this!
    deadline=60.0,       # total budget across all attempts
)
def fetch_report(report_id): ...
```

Gotchas this handles for you:

- **Narrow `retry_on`.** Retrying a `ValueError` from bad input just burns
  time. Only retry what a retry can fix.
- **`deadline` bounds the total budget** so one slow dependency cannot hold
  a request or worker hostage. If the next backoff would exceed it, the
  last error raises immediately.
- Works bare (`@retry`) or parametrized. `sleep`, `clock`, and `rng` are
  injectable so your tests never actually wait.

### Circuit breaker — `resilient.circuit`

Retries help with *transient* failures. When a dependency is down hard,
retrying adds load to something that cannot answer. The breaker fails fast
instead: `CLOSED` → `OPEN` after `failure_threshold` consecutive failures →
`HALF_OPEN` after `recovery_timeout` lets one probe through → `CLOSED` on
success, back to `OPEN` on failure.

```python
from resilient import CircuitBreaker, CircuitOpenError

breaker = CircuitBreaker(failure_threshold=5, recovery_timeout=30.0)

try:
    breaker.call(risky_downstream, arg)
except CircuitOpenError:
    return fallback()  # fail fast, shed load
```

Design notes:

- Only exceptions in `expected_exception` trip the breaker. A bug in your
  own code should not open the circuit — waiting would never fix it.
- Thread safe. `breaker.state` and `breaker.reset()` are there for
  health endpoints and ops runbooks.

### Rate limiter — `resilient.ratelimit`

Token bucket: the bucket holds `capacity` tokens, refills at `rate` per
second, and each operation consumes tokens. Unlike fixed window counters,
it bounds bursts to `capacity` at *every* instant — no 2x spike at window
boundaries.

```python
from resilient import TokenBucket

bucket = TokenBucket(rate=100.0, capacity=20.0)

bucket.acquire(timeout=5.0)   # block until allowed (False on timeout)
bucket.try_acquire()          # non-blocking: True/False right now
```

Thread safe with exact accounting under contention.

### Idempotency — `resilient.idempotency`

Retries are only safe when the operation is idempotent. The pattern used
across payments and webhooks: the caller sends a stable key; the receiver
executes once per key and replays the stored result for duplicates.

```python
from resilient import MemoryIdempotencyStore, idempotent

store = MemoryIdempotencyStore()

@idempotent(store, ttl=24 * 3600, key=lambda order, **kw: kw["idempotency_key"])
def charge(order, idempotency_key): ...
```

Honest scope notes: the memory store is per process — behind multiple
workers, implement the tiny `IdempotencyStore` protocol on Redis
(`SET key value NX EX`) or your database. Concurrent duplicate in flight
calls need an atomic check and set at the store for true exactly once.

## How the pieces compose

The standard resilient call path stacks them outside in:

```
idempotency → circuit breaker → retry → rate limiter → the actual call
```

Idempotency outermost (a retried request must not double execute),
breaker next (fail fast before burning retry budget), retry around the
call, limiter innermost guarding the downstream.

## Testing

```bash
python -m unittest discover -s tests -v
```

37 tests, all deterministic — clocks, sleeps, and RNG are injected, so the
suite never actually waits on real time (except two small rate limiter
blocking checks measured in milliseconds).

## Roadmap

- Async variants (`aretry`, async breaker/limiter)
- Redis idempotency store recipe
- Adaptive retry budgets and hedged requests

Contributions welcome — issues and PRs.

## License

MIT. See [LICENSE](LICENSE).
