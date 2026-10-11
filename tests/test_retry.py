import random
import unittest

from resilient import compute_delay, retry


class FakeClock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t

    def advance(self, seconds):
        self.t += seconds


class ComputeDelayTests(unittest.TestCase):
    def test_doubles_without_jitter(self):
        rng = random.Random(0)
        self.assertAlmostEqual(compute_delay(1, jitter=False, rng=rng), 0.1)
        self.assertAlmostEqual(compute_delay(2, jitter=False, rng=rng), 0.2)
        self.assertAlmostEqual(compute_delay(3, jitter=False, rng=rng), 0.4)

    def test_caps_at_max_delay(self):
        self.assertAlmostEqual(compute_delay(100, jitter=False), 30.0)
        self.assertAlmostEqual(
            compute_delay(10, jitter=False, base_delay=1.0, max_delay=5.0), 5.0
        )

    def test_jitter_stays_in_bounds(self):
        rng = random.Random(1)
        for _ in range(200):
            delay = compute_delay(3, rng=rng)  # unjittered would be 0.4
            self.assertGreaterEqual(delay, 0.0)
            self.assertLessEqual(delay, 0.4)

    def test_rejects_attempt_zero(self):
        with self.assertRaises(ValueError):
            compute_delay(0)


class RetryTests(unittest.TestCase):
    def test_bare_decorator_succeeds_first_try(self):
        calls = []

        @retry
        def f():
            calls.append(1)
            return "ok"

        self.assertEqual(f(), "ok")
        self.assertEqual(len(calls), 1)

    def test_retries_then_succeeds_with_backoff(self):
        sleeps = []
        attempts = {"n": 0}

        @retry(max_attempts=4, jitter=False, base_delay=0.1, sleep=sleeps.append)
        def f():
            attempts["n"] += 1
            if attempts["n"] < 3:
                raise ConnectionError("down")
            return "ok"

        self.assertEqual(f(), "ok")
        self.assertEqual(attempts["n"], 3)
        self.assertEqual(sleeps, [0.1, 0.2])  # sleeps after attempts 1 and 2

    def test_gives_up_and_reraises_last_error(self):
        @retry(max_attempts=3, jitter=False, sleep=lambda s: None)
        def f():
            raise ConnectionError("nope")

        with self.assertRaises(ConnectionError):
            f()

    def test_non_retryable_error_propagates_immediately(self):
        calls = {"n": 0}

        @retry(max_attempts=5, sleep=lambda s: None, retry_on=(ConnectionError,))
        def f():
            calls["n"] += 1
            raise ValueError("bad input")

        with self.assertRaises(ValueError):
            f()
        self.assertEqual(calls["n"], 1)

    def test_deadline_stops_before_blowing_budget(self):
        clock = FakeClock()
        sleeps = []

        def sleep(s):
            sleeps.append(s)
            clock.advance(s)

        calls = {"n": 0}

        @retry(
            max_attempts=10,
            jitter=False,
            base_delay=1.0,
            deadline=2.5,
            sleep=sleep,
            clock=clock,
        )
        def f():
            calls["n"] += 1
            raise ConnectionError("down")

        with self.assertRaises(ConnectionError):
            f()
        # Attempt 1 fails -> sleep 1.0 (budget ok). Attempt 2 fails -> next
        # sleep of 2.0 would exceed the 2.5 deadline, so raise instead.
        self.assertEqual(calls["n"], 2)
        self.assertEqual(sleeps, [1.0])

    def test_preserves_metadata(self):
        @retry(max_attempts=2)
        def documented():
            """Docstring."""

        self.assertEqual(documented.__name__, "documented")

    def test_rejects_bad_config(self):
        with self.assertRaises(ValueError):
            retry(max_attempts=0)
        with self.assertRaises(ValueError):
            retry(deadline=0)


if __name__ == "__main__":
    unittest.main()
