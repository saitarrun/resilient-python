import unittest

from resilient import MemoryIdempotencyStore, idempotent


class FakeClock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t

    def advance(self, seconds):
        self.t += seconds


class IdempotencyTests(unittest.TestCase):
    def test_repeat_call_returns_stored_result(self):
        store = MemoryIdempotencyStore()
        calls = {"n": 0}

        @idempotent(store)
        def charge(order_id, amount):
            calls["n"] += 1
            return f"charged {amount}"

        self.assertEqual(charge("o1", 100), "charged 100")
        self.assertEqual(charge("o1", 100), "charged 100")
        self.assertEqual(calls["n"], 1)

    def test_different_arguments_execute_again(self):
        store = MemoryIdempotencyStore()
        calls = {"n": 0}

        @idempotent(store)
        def charge(order_id):
            calls["n"] += 1
            return order_id

        charge("o1")
        charge("o2")
        self.assertEqual(calls["n"], 2)

    def test_kwargs_order_does_not_matter(self):
        store = MemoryIdempotencyStore()
        calls = {"n": 0}

        @idempotent(store)
        def f(a, b):
            calls["n"] += 1

        f(a=1, b=2)
        f(b=2, a=1)
        self.assertEqual(calls["n"], 1)

    def test_ttl_expiry_reexecutes(self):
        clock = FakeClock()
        store = MemoryIdempotencyStore(clock=clock)
        calls = {"n": 0}

        @idempotent(store, ttl=60.0)
        def f(x):
            calls["n"] += 1
            return x

        f(1)
        f(1)
        self.assertEqual(calls["n"], 1)
        clock.advance(61.0)
        f(1)
        self.assertEqual(calls["n"], 2)

    def test_custom_key_function(self):
        store = MemoryIdempotencyStore()
        calls = {"n": 0}

        @idempotent(store, key=lambda order_id, **kw: kw["idem_key"])
        def charge(order_id, idem_key):
            calls["n"] += 1
            return "done"

        charge("o1", idem_key="k1")
        charge("o2", idem_key="k1")  # same key, different order -> replayed
        self.assertEqual(calls["n"], 1)

    def test_unhashable_arguments_need_explicit_key(self):
        store = MemoryIdempotencyStore()

        @idempotent(store)
        def f(items):
            return len(items)

        with self.assertRaises(TypeError):
            f([1, 2, 3])

    def test_exceptions_are_not_cached(self):
        store = MemoryIdempotencyStore()
        calls = {"n": 0}

        @idempotent(store)
        def f(x):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("transient")
            return "ok"

        with self.assertRaises(RuntimeError):
            f(1)
        self.assertEqual(f(1), "ok")
        self.assertEqual(calls["n"], 2)

    def test_len_purges_expired(self):
        clock = FakeClock()
        store = MemoryIdempotencyStore(clock=clock)
        store.set("a", 1, ttl=10.0)
        self.assertEqual(len(store), 1)
        clock.advance(11.0)
        self.assertEqual(len(store), 0)

    def test_rejects_non_positive_ttl(self):
        store = MemoryIdempotencyStore()
        with self.assertRaises(ValueError):
            store.set("k", "v", ttl=0)
        with self.assertRaises(ValueError):

            @idempotent(store, ttl=-1)
            def f():
                pass


if __name__ == "__main__":
    unittest.main()
