import unittest
from unittest.mock import patch

import httpx

import src.cache as cache


class FailingClient:
    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    async def get(self, url):
        request = httpx.Request("GET", url)
        raise httpx.RequestError("offline", request=request)


class CacheFailureTests(unittest.IsolatedAsyncioTestCase):
    async def test_network_error_mempertahankan_cache_lama(self):
        cache._katalog_cache = [{"title": "Cache lama"}]
        cache._last_fetch_time = 0
        cache._cache_loaded = True

        with patch.object(cache.httpx, "AsyncClient", FailingClient):
            result = await cache.muat_katalog()

        self.assertEqual(result, [{"title": "Cache lama"}])


if __name__ == "__main__":
    unittest.main()
