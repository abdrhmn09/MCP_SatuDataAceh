import asyncio
import unittest
from unittest.mock import patch

import src.cache as cache


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class FakeClient:
    calls = 0
    payload = {"dataset": [{"title": "Penduduk Aceh"}]}

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    async def get(self, url):
        type(self).calls += 1
        await asyncio.sleep(0)
        return FakeResponse(type(self).payload)


class CacheTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        cache._katalog_cache = []
        cache._last_fetch_time = 0
        cache._cache_loaded = False
        FakeClient.calls = 0
        FakeClient.payload = {"dataset": [{"title": "Penduduk Aceh"}]}

    async def test_memuat_katalog_valid(self):
        with patch.object(cache.httpx, "AsyncClient", FakeClient):
            result = await cache.muat_katalog()

        self.assertEqual(result[0]["title"], "Penduduk Aceh")
        self.assertEqual(FakeClient.calls, 1)

    async def test_payload_invalid_mempertahankan_cache_lama(self):
        cache._katalog_cache = [{"title": "Cache lama"}]
        cache._cache_loaded = True
        cache._last_fetch_time = 0
        FakeClient.payload = {"dataset": "bukan daftar"}

        with patch.object(cache.httpx, "AsyncClient", FakeClient):
            result = await cache.muat_katalog()

        self.assertEqual(result, [{"title": "Cache lama"}])

    async def test_cache_kosong_yang_valid_tidak_fetch_ulang(self):
        cache._katalog_cache = []
        cache._cache_loaded = True
        cache._last_fetch_time = 9999999999

        with patch.object(cache.httpx, "AsyncClient", FakeClient):
            first = await cache.muat_katalog()
            second = await cache.muat_katalog()

        self.assertEqual(first, [])
        self.assertEqual(second, [])
        self.assertEqual(FakeClient.calls, 0)

    async def test_request_paralel_hanya_fetch_sekali(self):
        with patch.object(cache.httpx, "AsyncClient", FakeClient):
            results = await asyncio.gather(
                cache.muat_katalog(), cache.muat_katalog(), cache.muat_katalog()
            )

        self.assertEqual(FakeClient.calls, 1)
        self.assertEqual(results[0], results[1])
        self.assertEqual(results[1], results[2])


if __name__ == "__main__":
    unittest.main()
