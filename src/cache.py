import httpx
import time
import asyncio
import os
from typing import List, Dict, Any

# Konstanta
DATA_JSON_URL = os.getenv(
    "SATU_DATA_ACEH_CATALOG_URL",
    "https://satudata.acehprov.go.id/data.json",
)


def _cache_ttl() -> int:
    try:
        return max(60, int(os.getenv("SATU_DATA_ACEH_CACHE_TTL", "3600")))
    except ValueError:
        return 3600


CACHE_TTL = _cache_ttl()  # Waktu kedaluwarsa cache dalam detik (1 jam)

# State global
_katalog_cache: List[Dict[str, Any]] = []
_last_fetch_time: float = 0
_cache_loaded = False
_cache_lock = asyncio.Lock()

async def muat_katalog() -> List[Dict[str, Any]]:
    """
    Mengunduh data.json jika cache kosong atau sudah kedaluwarsa.
    Mengembalikan daftar dataset (katalog).
    """
    global _katalog_cache, _last_fetch_time, _cache_loaded
    
    if _cache_loaded and (time.time() - _last_fetch_time) < CACHE_TTL:
        return _katalog_cache

    async with _cache_lock:
        if _cache_loaded and (time.time() - _last_fetch_time) < CACHE_TTL:
            return _katalog_cache

        print("Mengunduh katalog data.json dari server...")
        try:
            async with httpx.AsyncClient(timeout=45.0) as client:
                response = await client.get(DATA_JSON_URL)
                response.raise_for_status()
                data = response.json()

            katalog = data.get("dataset") if isinstance(data, dict) else None
            if not isinstance(katalog, list) or not all(
                isinstance(item, dict) for item in katalog
            ):
                print("Format JSON tidak dikenali, 'dataset' harus berupa daftar.")
                return _katalog_cache

            _katalog_cache = katalog
            _last_fetch_time = time.time()
            _cache_loaded = True
            print(f"Berhasil memuat {len(_katalog_cache)} dataset ke dalam cache.")
        except httpx.RequestError as e:
            print(f"Gagal menghubungi server: {e}")
        except (ValueError, TypeError) as e:
            print(f"Format katalog tidak valid: {e}")
        except Exception as e:
            print(f"Terjadi kesalahan saat memproses data: {e}")

        return _katalog_cache