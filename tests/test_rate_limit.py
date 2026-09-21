import unittest

from src.server import _RateLimiter


class RateLimitTests(unittest.IsolatedAsyncioTestCase):
    async def test_menolak_request_setelah_limit(self):
        limiter = _RateLimiter(limit=2, window_seconds=60)

        self.assertTrue(await limiter.allow())
        self.assertTrue(await limiter.allow())
        self.assertFalse(await limiter.allow())


if __name__ == "__main__":
    unittest.main()
