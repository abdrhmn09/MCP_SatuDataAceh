"""Catalog cache with bounded downloads, local fallback, and refresh backoff."""

import asyncio
import json
import logging
import os
import time
from typing import Any

import httpx

logger = logging.getLogger(__name__)
DATA_JSON_URL = os.getenv("SATU_DATA_ACEH_CATALOG_URL", "https://satudata.acehprov.go.id/data.json")
DEFAULT_LOCAL_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data.json")
LOCAL_CATALOG_PATH = os.getenv("SATU_DATA_ACEH_LOCAL_PATH", DEFAULT_LOCAL_PATH)
MAX_CATALOG_BYTES = 32 * 1024 * 1024


def _cache_ttl() -> int:
    try:
        return max(60, int(os.getenv("SATU_DATA_ACEH_CACHE_TTL", "3600")))
    except ValueError:
        return 3600


CACHE_TTL = _cache_ttl()
_katalog_cache: list[dict[str, Any]] = []
_last_fetch_time: float = 0
_cache_loaded = False
_cache_lock = asyncio.Lock()
_cache_source = "unavailable"
_last_success_time: float = 0
_last_error = ""


def catalog_status() -> dict[str, Any]:
    return {
        "source": _cache_source,
        "loaded": _cache_loaded,
        "dataset_count": len(_katalog_cache),
        "stale": _cache_loaded and (_cache_source in {"local", "stale"} or time.time() - _last_fetch_time >= CACHE_TTL),
        "last_success_at": _last_success_time or None,
        "last_error": _last_error,
    }


def _validate_catalog(data: object) -> list[dict[str, Any]]:
    catalog = data.get("dataset") if isinstance(data, dict) else None
    if not isinstance(catalog, list) or not all(isinstance(item, dict) for item in catalog):
        raise ValueError("dataset harus berupa daftar objek")
    return catalog


def _muat_katalog_lokal() -> list[dict[str, Any]]:
    if not LOCAL_CATALOG_PATH or not os.path.isfile(LOCAL_CATALOG_PATH):
        return []
    try:
        with open(LOCAL_CATALOG_PATH, "rb") as catalog_file:
            raw = catalog_file.read(MAX_CATALOG_BYTES + 1)
        if len(raw) > MAX_CATALOG_BYTES:
            raise ValueError("katalog lokal terlalu besar")
        return _validate_catalog(json.loads(raw))
    except (OSError, ValueError, TypeError):
        logger.warning("Katalog lokal tidak dapat dibaca.")
        return []


async def muat_katalog() -> list[dict[str, Any]]:
    global _katalog_cache, _last_fetch_time, _cache_loaded
    global _cache_source, _last_success_time, _last_error
    if (_cache_loaded or _last_error) and time.time() - _last_fetch_time < CACHE_TTL:
        return _katalog_cache
    async with _cache_lock:
        if (_cache_loaded or _last_error) and time.time() - _last_fetch_time < CACHE_TTL:
            return _katalog_cache
        try:
            chunks = []
            size = 0
            async with asyncio.timeout(45):
                async with httpx.AsyncClient(timeout=30, follow_redirects=False) as client:
                    async with client.stream("GET", DATA_JSON_URL) as response:
                        response.raise_for_status()
                        async for chunk in response.aiter_bytes():
                            size += len(chunk)
                            if size > MAX_CATALOG_BYTES:
                                raise ValueError("katalog remote terlalu besar")
                            chunks.append(chunk)
            catalog = _validate_catalog(json.loads(b"".join(chunks)))
            _katalog_cache = catalog
            _last_fetch_time = _last_success_time = time.time()
            _cache_loaded = True
            _cache_source, _last_error = "remote", ""
        except (httpx.HTTPError, ValueError, TypeError, TimeoutError) as error:
            _last_error = type(error).__name__
            logger.warning("Pembaruan katalog gagal: %s", _last_error)
            if _cache_loaded:
                _cache_source = "stale"
            else:
                local = _muat_katalog_lokal()
                if local:
                    _katalog_cache, _cache_loaded, _cache_source = local, True, "local"
            # Retry after 30 seconds rather than once per waiting client.
            # This timestamp schedules refreshes; last_success_at remains actual.
            _last_fetch_time = time.time() - CACHE_TTL + 30
        return _katalog_cache
