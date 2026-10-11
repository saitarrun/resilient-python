import unittest

from resilient import CircuitBreaker, CircuitOpenError, CircuitState


class FakeClock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t

    def advance(self, seconds):
        self.t += seconds


def boom():
    raise IOError("dependency down")


def ok():
    return "fine"


class CircuitBreakerTests(unittest.TestCase):
    def test_closed_passes_calls_through(self):
        breaker = CircuitBreaker()
        self.assertEqual(breaker.call(ok), "fine")
        self.assertEqual(breaker.state, CircuitState.CLOSED)

    def test_opens_after_threshold_consecutive_failures(self):
        breaker = CircuitBreaker(failure_threshold=3, expected_exception=(IOError,))
        for _ in range(3):
            with self.assertRaises(IOError):
                breaker.call(boom)
        self.assertEqual(breaker.state, CircuitState.OPEN)
        with self.assertRaises(CircuitOpenError):
            breaker.call(ok)

    def test_success_resets_failure_count(self):
        breaker = CircuitBreaker(failure_threshold=3, expected_exception=(IOError,))
        with self.assertRaises(IOError):
            breaker.call(boom)
        with self.assertRaises(IOError):
            breaker.call(boom)
        self.assertEqual(breaker.call(ok), "fine")
        self.assertEqual(breaker.consecutive_failures, 0)
        # One more failure is not enough to trip it again.
        with self.assertRaises(IOError):
            breaker.call(boom)
        self.assertEqual(breaker.state, CircuitState.CLOSED)

    def test_half_open_probe_success_closes_circuit(self):
        clock = FakeClock()
        breaker = CircuitBreaker(
            failure_threshold=1,
            recovery_timeout=10.0,
            clock=clock,
            expected_exception=(IOError,),
        )
        with self.assertRaises(IOError):
            breaker.call(boom)
        self.assertEqual(breaker.state, CircuitState.OPEN)
        clock.advance(10.0)
        self.assertEqual(breaker.state, CircuitState.HALF_OPEN)
        self.assertEqual(breaker.call(ok), "fine")
        self.assertEqual(breaker.state, CircuitState.CLOSED)

    def test_half_open_probe_failure_reopens_immediately(self):
        clock = FakeClock()
        breaker = CircuitBreaker(
            failure_threshold=5,
            recovery_timeout=10.0,
            clock=clock,
            expected_exception=(IOError,),
        )
        for _ in range(5):
            with self.assertRaises(IOError):
                breaker.call(boom)
        clock.advance(11.0)
        with self.assertRaises(IOError):
            breaker.call(boom)  # the single probe fails
        self.assertEqual(breaker.state, CircuitState.OPEN)
        with self.assertRaises(CircuitOpenError):
            breaker.call(ok)

    def test_open_circuit_does_not_call_function(self):
        calls = {"n": 0}
        breaker = CircuitBreaker(failure_threshold=1, expected_exception=(IOError,))

        def guarded():
            calls["n"] += 1
            return "x"

        with self.assertRaises(IOError):
            breaker.call(boom)
        with self.assertRaises(CircuitOpenError):
            breaker.call(guarded)
        self.assertEqual(calls["n"], 0)

    def test_unexpected_exception_neither_trips_nor_resets(self):
        breaker = CircuitBreaker(failure_threshold=1, expected_exception=(IOError,))

        def bug():
            raise ValueError("my bug, not the dependency's")

        with self.assertRaises(ValueError):
            breaker.call(bug)
        self.assertEqual(breaker.state, CircuitState.CLOSED)
        self.assertEqual(breaker.consecutive_failures, 0)

    def test_decorator_usage(self):
        breaker = CircuitBreaker(failure_threshold=1, expected_exception=(IOError,))

        @breaker
        def f():
            raise IOError("x")

        with self.assertRaises(IOError):
            f()
        with self.assertRaises(CircuitOpenError):
            f()

    def test_reset_forces_closed(self):
        breaker = CircuitBreaker(failure_threshold=1, expected_exception=(IOError,))
        with self.assertRaises(IOError):
            breaker.call(boom)
        breaker.reset()
        self.assertEqual(breaker.state, CircuitState.CLOSED)
        self.assertEqual(breaker.call(ok), "fine")


if __name__ == "__main__":
    unittest.main()
