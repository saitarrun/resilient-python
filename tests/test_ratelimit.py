import threading
import time
import unittest

from resilient import TokenBucket


class FakeClock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t

    def advance(self, seconds):
        self.t += seconds


class TokenBucketTests(unittest.TestCase):
    def test_burst_then_throttles(self):
        bucket = TokenBucket(rate=10.0, capacity=3.0, clock=FakeClock())
        self.assertTrue(bucket.try_acquire())
        self.assertTrue(bucket.try_acquire())
        self.assertTrue(bucket.try_acquire())
        self.assertFalse(bucket.try_acquire())

    def test_refills_over_time(self):
        clock = FakeClock()
        bucket = TokenBucket(rate=10.0, capacity=5.0, clock=clock)
        for _ in range(5):
            self.assertTrue(bucket.try_acquire())
        self.assertFalse(bucket.try_acquire())
        clock.advance(0.5)  # 5 tokens refill
        self.assertTrue(bucket.try_acquire())
        self.assertAlmostEqual(bucket.available, 4.0)

    def test_never_exceeds_capacity(self):
        clock = FakeClock()
        bucket = TokenBucket(rate=100.0, capacity=2.0, clock=clock)
        clock.advance(1000.0)
        self.assertAlmostEqual(bucket.available, 2.0)

    def test_multi_token_acquire(self):
        bucket = TokenBucket(rate=10.0, capacity=5.0, clock=FakeClock())
        self.assertTrue(bucket.try_acquire(5.0))
        self.assertFalse(bucket.try_acquire(1.0))

    def test_acquire_blocks_until_refill(self):
        bucket = TokenBucket(rate=200.0, capacity=1.0)  # real clock
        self.assertTrue(bucket.acquire())
        start = time.monotonic()
        self.assertTrue(bucket.acquire(timeout=2.0))  # waits ~5ms for 1 token
        self.assertLess(time.monotonic() - start, 2.0)

    def test_acquire_times_out(self):
        bucket = TokenBucket(rate=1.0, capacity=1.0)  # real clock
        self.assertTrue(bucket.acquire())
        # Refilling 1 token takes a full second; 10ms is not enough.
        self.assertFalse(bucket.acquire(timeout=0.01))

    def test_thread_safety_exact_accounting(self):
        clock = FakeClock()  # frozen: exactly 1000 tokens, no refills
        bucket = TokenBucket(rate=10000.0, capacity=1000.0, clock=clock)
        results = []

        def worker():
            results.append(sum(1 for _ in range(200) if bucket.try_acquire()))

        threads = [threading.Thread(target=worker) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(sum(results), 1000)
        self.assertFalse(bucket.try_acquire())

    def test_rejects_bad_config(self):
        with self.assertRaises(ValueError):
            TokenBucket(rate=0, capacity=1)
        with self.assertRaises(ValueError):
            TokenBucket(rate=1, capacity=0)
        bucket = TokenBucket(rate=1, capacity=1, clock=FakeClock())
        with self.assertRaises(ValueError):
            bucket.try_acquire(0)
        with self.assertRaises(ValueError):
            bucket.try_acquire(2.0)  # more than capacity can ever hold
        with self.assertRaises(ValueError):
            bucket.acquire(timeout=-1)


if __name__ == "__main__":
    unittest.main()
