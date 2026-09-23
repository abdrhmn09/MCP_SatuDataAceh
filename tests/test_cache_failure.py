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

    async def test_network_error_fallback_ke_katalog_lokal(self):
        cache._katalog_cache = []
        cache._last_fetch_time = 0
        cache._cache_loaded = False

        with patch.object(cache.httpx, "AsyncClient", FailingClient):
            result = await cache.muat_katalog()

        self.assertGreater(len(result), 0)
        self.assertIn("title", result[0])

    async def test_network_error_tanpa_katalog_lokal_mengembalikan_kosong(self):
        cache._katalog_cache = []
        cache._last_fetch_time = 0
        cache._cache_loaded = False

        with patch.object(cache, "LOCAL_CATALOG_PATH", "file_tidak_ada.json"):
            with patch.object(cache.httpx, "AsyncClient", FailingClient):
                result = await cache.muat_katalog()

        self.assertEqual(result, [])


if __name__ == "__main__":
    unittest.main()
