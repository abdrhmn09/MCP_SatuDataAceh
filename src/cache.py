import asyncio
import json
import logging
import os
import time
from typing import Any, Dict, List

import httpx

logger = logging.getLogger(__name__)

# Konstanta
DATA_JSON_URL = os.getenv(
    "SATU_DATA_ACEH_CATALOG_URL",
    "https://satudata.acehprov.go.id/data.json",
)

DEFAULT_LOCAL_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data.json",
)
LOCAL_CATALOG_PATH = os.getenv("SATU_DATA_ACEH_LOCAL_PATH", DEFAULT_LOCAL_PATH)


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


def _muat_katalog_lokal() -> List[Dict[str, Any]]:
    """Membaca katalog dari file lokal data.json jika tersedia."""
    if not LOCAL_CATALOG_PATH or not os.path.isfile(LOCAL_CATALOG_PATH):
        return []
    try:
        logger.info("Memuat katalog lokal dari %s sebagai fallback...", LOCAL_CATALOG_PATH)
        with open(LOCAL_CATALOG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        katalog = data.get("dataset") if isinstance(data, dict) else None
        if isinstance(katalog, list):
            return [item for item in katalog if isinstance(item, dict)]
    except Exception as e:
        logger.warning("Gagal memuat katalog lokal dari %s: %s", LOCAL_CATALOG_PATH, e)
    return []


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

        logger.info("Mengunduh katalog data.json dari server...")
        try:
            async with httpx.AsyncClient(timeout=45.0) as client:
                response = await client.get(DATA_JSON_URL)
                response.raise_for_status()
                data = response.json()

            katalog = data.get("dataset") if isinstance(data, dict) else None
            if not isinstance(katalog, list) or not all(
                isinstance(item, dict) for item in katalog
            ):
                logger.warning("Format JSON tidak dikenali, 'dataset' harus berupa daftar.")
                if not _katalog_cache:
                    lokal = _muat_katalog_lokal()
                    if lokal:
                        _katalog_cache = lokal
                        _last_fetch_time = time.time()
                        _cache_loaded = True
                        logger.info("Berhasil memuat %d dataset dari file lokal.", len(_katalog_cache))
                return _katalog_cache

            _katalog_cache = katalog
            _last_fetch_time = time.time()
            _cache_loaded = True
            logger.info("Berhasil memuat %d dataset ke dalam cache.", len(_katalog_cache))
        except httpx.RequestError as e:
            logger.warning("Gagal menghubungi server: %s", e)
        except (ValueError, TypeError) as e:
            logger.warning("Format katalog tidak valid: %s", e)
        except Exception as e:
            logger.error("Terjadi kesalahan saat memproses data: %s", e)

        # Fallback ke katalog lokal jika cache kosong dan remote gagal
        if not _katalog_cache:
            lokal = _muat_katalog_lokal()
            if lokal:
                _katalog_cache = lokal
                _last_fetch_time = time.time()
                _cache_loaded = True
                logger.info("Berhasil memuat %d dataset dari file lokal sebagai fallback.", len(_katalog_cache))

        return _katalog_cache