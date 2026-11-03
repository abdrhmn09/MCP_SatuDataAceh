import pandas as pd
from io import StringIO
from importlib.resources import files
from pathlib import Path
from datetime import datetime, timezone
import asyncio
import httpx
import ipaddress
import json
import logging
import os
import re
import time
import socket
from collections import deque
from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.parse import quote, urljoin, urlparse
try:
    from mcp.server.fastmcp import FastMCP  # mcp<2
except ImportError:
    from mcp.server.mcpserver import MCPServer as FastMCP  # mcp>=2

from pydantic import BaseModel
from starlette.requests import Request
from starlette.responses import JSONResponse, FileResponse

def _redact_secret(value: str) -> str:
    value = re.sub(r"(/key/)[^/?#\s]+", r"\1***", value, flags=re.IGNORECASE)
    key = os.getenv("BPS_API_KEY", "")
    return value.replace(key, "***") if key else value


class _SecretFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = _redact_secret(record.getMessage())
        record.args = ()
        return True


def _load_env_file() -> None:
    for base in [os.getcwd(), os.path.dirname(os.path.abspath(__file__)), os.path.dirname(os.path.dirname(os.path.abspath(__file__)))]:
        env_path = os.path.join(base, ".env")
        if os.path.isfile(env_path):
            try:
                with open(env_path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith("#") and "=" in line:
                            k, v = line.split("=", 1)
                            k, v = k.strip(), v.strip()
                            if k and k not in os.environ:
                                os.environ[k] = v
                break
            except Exception:
                pass

_load_env_file()

logger = logging.getLogger(__name__)
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)

for _handler in logging.getLogger().handlers:
    _handler.addFilter(_SecretFilter())



# Impor fungsi pengelola cache dari package maupun direct script.
try:
    from .cache import muat_katalog, catalog_status
except ImportError:
    from cache import muat_katalog, catalog_status

try:
    from . import bps_api, accounts
except ImportError:
    import bps_api
    import accounts


def _request_headers():
    try:
        return mcp.get_context().request_context.request.headers
    except (LookupError, RuntimeError, AttributeError, ValueError):
        return {}


def _account_key(service='bps'):
    user = accounts.principal.get()
    if user:
        vault = accounts.get_vault()
        if not vault.identity(user['raw'],user['kind']):
            raise ValueError('Sesi atau token telah dicabut.')
        key = vault.get_key(user['id'],service)
        if service == 'sdgs' and not key:
            key = vault.get_key(user['id'],'bps')
        if not key:
            raise ValueError('Simpan API key BPS di dashboard akun terlebih dahulu.')
        return key
    return None


def _bps_api_key():
    stored = _account_key()
    if stored is not None:
        return stored
    headers = _request_headers()
    if any(name in headers for name in ("x-bps-api-key", "authorization")):
        return bps_api.credential(headers)
    return BPS_API_KEY


class SearchResult(BaseModel):
    id: str
    title: str
    url: str


class SearchOutput(BaseModel):
    results: list[SearchResult]
    message: str | None = None
    total: int = 0
    offset: int = 0
    next_offset: int | None = None


class FetchOutput(BaseModel):
    id: str
    title: str
    text: str
    url: str
    metadata: dict[str, object] | None = None
    error: str | None = None


@dataclass
class CsvReadResult:
    status: str
    preview: str
    row_count: int
    column_count: int
    source_url: str
    message: str = ""
    tahun_min: str = ""
    tahun_max: str = ""
    kolom_indikator: str = ""
    satuan: str = ""
    indikator_bps: str = ""


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


class _RateLimiter:
    def __init__(self, limit: int, window_seconds: int = 60):
        self.limit = max(1, limit)
        self.window_seconds = window_seconds
        self.clients: dict[str, deque[float]] = {}
        self.lock = asyncio.Lock()

    async def allow(self, client_key: str | None = None) -> bool:
        now = time.monotonic()
        key = client_key if client_key is not None else _request_client_key()
        async with self.lock:
            if key not in self.clients:
                for old_key in list(self.clients):
                    if not self.clients[old_key] or now - self.clients[old_key][-1] >= self.window_seconds:
                        del self.clients[old_key]
                if len(self.clients) >= 10_000:
                    return False
                self.clients[key] = deque()
            requests = self.clients[key]
            while requests and now - requests[0] >= self.window_seconds:
                requests.popleft()
            if len(requests) >= self.limit:
                return False
            requests.append(now)
            return True


def _request_client_key() -> str:
    """Use the transport peer; proxy headers require trust configured by the host."""
    if accounts.principal.get():
        return accounts.principal.get()["id"]
    try:
        request = mcp.get_context().request_context.request
        if request and request.client:
            return request.client.host
    except (LookupError, RuntimeError, AttributeError, ValueError):
        pass
    return "local"


# Host hanya dibuka ke publik saat deployment remote memilih MCP_HOST=0.0.0.0.
_MCP_HOST = os.getenv("MCP_HOST", "127.0.0.1")
_MCP_PORT = _env_int("MCP_PORT", _env_int("PORT", 8000))

try:
    from mcp.server.transport_security import TransportSecuritySettings
    _transport_security = TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=["localhost:*", "127.0.0.1:*", "[::1]:*", *[host.strip() for host in os.getenv("MCP_ALLOWED_HOSTS", "www.mcpsatudataaceh.web.id,mcpsatudataaceh.web.id").split(",") if host.strip()]],
        allowed_origins=[origin.strip() for origin in os.getenv("MCP_ALLOWED_ORIGINS", "https://www.mcpsatudataaceh.web.id,https://mcpsatudataaceh.web.id").split(",") if origin.strip()]
    )
except ImportError:
    _transport_security = None

try:
    _security_at_runtime = False
    mcp = FastMCP(
        "Satu Data Aceh Server",
        instructions="Mencari dataset publik Aceh dan membaca data CSV.",
        host=_MCP_HOST,
        port=_MCP_PORT,
        transport_security=_transport_security,
        stateless_http=True,
    )
except TypeError:
    # mcp>=2 MCPServer tidak menerima host/port di constructor
    _security_at_runtime = True
    mcp = FastMCP(
        name="Satu Data Aceh Server",
        instructions="Mencari dataset publik Aceh dan membaca data CSV.",
    )

MAX_CSV_BYTES = 5 * 1024 * 1024
MAX_HTML_BYTES = 2 * 1024 * 1024
DEFAULT_DATA_YEAR = os.getenv("SATU_DATA_ACEH_DATA_YEAR", "2025")
BPS_API_KEY = os.getenv("BPS_API_KEY", "")
BPS_DOMAIN = os.getenv("BPS_DOMAIN", "1100")
# BPS_DATASET_MAP: override via env, default kosong (gunakan BPS_INDICATOR_MAP dari bps.py)
_BPS_DATASET_MAP_ENV = os.getenv("BPS_DATASET_MAP", "{}")
RATE_LIMIT_PER_MINUTE = _env_int("MCP_RATE_LIMIT_PER_MINUTE", 60)
_rate_limiter = _RateLimiter(RATE_LIMIT_PER_MINUTE)

# Import modul BPS
try:
    from .bps import BPS_INDICATOR_MAP, BPS_KEYWORD_TO_VAR, bps_payload_ke_csv, cari_var_bps_dari_kata_kunci
except ImportError:
    from bps import BPS_INDICATOR_MAP, BPS_KEYWORD_TO_VAR, bps_payload_ke_csv, cari_var_bps_dari_kata_kunci


def _url_aman(url: str) -> bool:
    """Menolak URL non-HTTPS dan alamat lokal untuk mengurangi risiko SSRF."""
    try:
        parsed = urlparse(url)
        if parsed.scheme != "https" or not parsed.hostname:
            return False
        if parsed.username or parsed.password:
            return False
        hostname = parsed.hostname.lower().rstrip(".")
        if hostname in {"localhost", "localhost.localdomain"} or hostname.endswith(
            ".localhost"
        ):
            return False
        try:
            address = ipaddress.ip_address(hostname)
        except ValueError:
            return True
        return address.is_global and not address.is_multicast
    except (TypeError, ValueError):
        return False


async def _validate_request_target(request: httpx.Request) -> None:
    """Reject private addresses returned by DNS before outbound HTTP requests."""
    if not _url_aman(str(request.url)):
        raise httpx.RequestError("URL tujuan tidak diizinkan.", request=request)
    loop = asyncio.get_running_loop()
    try:
        addresses = await asyncio.wait_for(
            loop.getaddrinfo(request.url.host, request.url.port or 443, type=socket.SOCK_STREAM),
            timeout=5,
        )
    except (OSError, TimeoutError) as error:
        raise httpx.RequestError("DNS tujuan tidak dapat diperiksa.", request=request) from error
    if not addresses or any(not ipaddress.ip_address(entry[4][0]).is_global for entry in addresses):
        raise httpx.RequestError("DNS tujuan bukan alamat publik.", request=request)
    # Connect to the checked IP, preserving HTTP Host and TLS certificate/SNI
    # validation for the original hostname. This prevents a second DNS lookup
    # from changing the destination between validation and connection.
    address = next((entry[4][0] for entry in addresses if entry[0] == socket.AF_INET), addresses[0][4][0])
    hostname = request.url.host
    request.headers["Host"] = request.url.netloc.decode("ascii")
    request.extensions["sni_hostname"] = hostname
    request.url = request.url.copy_with(host=address)


class _CsvLinkParser(HTMLParser):
    def __init__(self, base_url: str):
        super().__init__()
        self.base_url = base_url
        self.csv_url = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self.csv_url or tag.lower() not in {"a", "link"}:
            return
        attributes = dict(attrs)
        href = attributes.get("href")
        if not href:
            return
        candidate = urljoin(self.base_url, href)
        path = urlparse(candidate).path.lower()
        media_type = attributes.get("type", "").lower()
        if (path.endswith(".csv") or "csv" in media_type) and _url_aman(candidate):
            self.csv_url = candidate


async def _cari_link_csv(url_halaman: str) -> str | None:
    """Mencari link CSV pada halaman dataset tanpa mengunduh data CSV-nya."""
    if not _url_aman(url_halaman):
        return None
    try:
        timeout = httpx.Timeout(20.0, connect=10.0)
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=False, event_hooks={"request": [_validate_request_target]}) as client:
            chunks = []
            total_bytes = 0
            async with client.stream("GET", url_halaman) as response:
                response.raise_for_status()
                async for chunk in response.aiter_bytes():
                    total_bytes += len(chunk)
                    if total_bytes > MAX_HTML_BYTES:
                        return None
                    chunks.append(chunk)
        parser = _CsvLinkParser(url_halaman)
        parser.feed(b"".join(chunks).decode("utf-8", errors="replace"))
        return parser.csv_url
    except (httpx.HTTPError, UnicodeError):
        return None


def _url_api_csv(item: dict[str, object], halaman_dataset: str) -> str | None:
    """Membentuk endpoint CSV resmi portal dari metadata DCAT dataset.
    
    Mengembalikan URL unduhan lengkap tanpa membatasi pada satu tahun saja,
    sehingga seluruh observasi multi-tahun dapat diunduh utuh.
    """
    parsed = urlparse(halaman_dataset)
    if parsed.hostname != "satudata.acehprov.go.id":
        return None

    identifier = str(item.get("identifier", "")).strip()
    slug = identifier or parsed.path.rstrip("/").split("/")[-1]
    if not slug:
        return None

    return f"https://satudata.acehprov.go.id/api/datasets/{quote(slug, safe='')}/datasources/download"


def _halaman_dataset(item: dict[str, object]) -> str:
    halaman = item.get("landingPage", "")
    distribusi = item.get("distribution", [])
    if isinstance(distribusi, list):
        for distro in distribusi:
            if isinstance(distro, dict) and not halaman:
                halaman = distro.get("accessURL", "")
    return str(halaman) if halaman else ""


def _url_csv_item(item: dict[str, object]) -> str:
    halaman = _halaman_dataset(item)
    distribusi = item.get("distribution", [])
    if isinstance(distribusi, list):
        for distro in distribusi:
            if not isinstance(distro, dict):
                continue
            media_type = str(distro.get("mediaType", "")).lower()
            format_tipe = str(distro.get("format", "")).lower()
            if "csv" in media_type or "csv" in format_tipe:
                return str(distro.get("downloadURL") or distro.get("accessURL") or "")
    return _url_api_csv(item, halaman) or halaman


def _bps_source(item: dict[str, object]) -> dict[str, str] | None:
    """Cari sumber BPS untuk item katalog.

    Lookup priority:
    1. Override dari env BPS_DATASET_MAP (JSON, untuk kustom tanpa deploy ulang)
    2. BPS_INDICATOR_MAP bawaan dari bps.py (komprehensif, terawat)
    """
    identifier = str(item.get("identifier", "")).strip()
    if not identifier:
        return None

    # 1. Coba env override
    try:
        env_mapping: dict[str, str] = json.loads(_BPS_DATASET_MAP_ENV)
        if isinstance(env_mapping, dict) and isinstance(env_mapping.get(identifier), str) and env_mapping[identifier]:
            return {
                "domain": BPS_DOMAIN,
                "variable": str(env_mapping[identifier]),
                "defaultTh": "124",
                "reference_url": "https://webapi.bps.go.id/",
            }
    except (TypeError, ValueError):
        pass

    # 2. Coba built-in indicator map
    if identifier in BPS_INDICATOR_MAP:
        entry = BPS_INDICATOR_MAP[identifier]
        return {
            "domain": BPS_DOMAIN,
            "variable": str(entry["var"]),
            "label": str(entry.get("label", "")),
            "defaultTh": str(entry.get("defaultTh", "124")),
            "reference_url": "https://webapi.bps.go.id/",
        }

    return None


def _bps_url(source: dict[str, str], th: str = "124") -> str:
    return (
        "https://webapi.bps.go.id/v1/api/list/model/data/"
        f"domain/{quote(source['domain'], safe='')}/"
        f"var/{quote(source['variable'], safe='')}/"
        + (f"th/{quote(th, safe='')}/" if th else "")
        + f"key/{quote(_bps_api_key(), safe='')}"
    )


def _bps_payload_to_csv(payload: object) -> str:
    if not isinstance(payload, dict):
        return ""
    rows = payload.get("data", [])
    if isinstance(rows, dict):
        rows = rows.get("data", [])
    if not isinstance(rows, list):
        return ""
    objects = [row for row in rows if isinstance(row, dict)]
    if not objects:
        return ""
    columns = list(dict.fromkeys(column for row in objects for column in row))
    frame = pd.DataFrame(objects, columns=columns)
    return frame.to_csv(index=False)


async def _read_bps_payload(url: str, headers: dict | None = None) -> object:
    chunks = []
    size = 0
    async with asyncio.timeout(30):
        async with httpx.AsyncClient(timeout=httpx.Timeout(20.0, connect=10.0), follow_redirects=False) as client:
            async with client.stream("GET", url, headers=headers) as response:
                response.raise_for_status()
                async for chunk in response.aiter_bytes():
                    size += len(chunk)
                    if size > MAX_CSV_BYTES:
                        raise ValueError("Respons BPS terlalu besar.")
                    chunks.append(chunk)
    return json.loads(b"".join(chunks))


async def _ambil_dari_bps(item: dict[str, object]) -> tuple[CsvReadResult, dict[str, str]] | None:
    """Ambil data dari BPS sebagai fallback untuk dataset Satu Data Aceh yang kosong."""
    source = _bps_source(item)
    if not source or not _bps_api_key():
        return None
    kandidat_th = ["", source.get("defaultTh"), "124", "123", "122"]
    sudah_dicoba: set[str] = set()
    for th in kandidat_th:
        if th is None or th in sudah_dicoba:
            continue
        sudah_dicoba.add(th)
        url = _bps_url(source, th=th)
        try:
            teks_csv = bps_payload_ke_csv(await _read_bps_payload(url))
            if not teks_csv:
                continue
            return _analisis_csv(teks_csv, url, 50), source
        except (
            httpx.HTTPError,
            TimeoutError,
            ValueError,
            TypeError,
            KeyError,
            AttributeError,
            IndexError,
        ) as error:
            logger.warning("Sumber BPS th=%s gagal: %s", th, type(error).__name__)
    return None


async def _ambil_langsung_dari_bps(
    var_id: str, domain: str = "1100", default_th: str | None = None
) -> tuple[CsvReadResult, str] | None:
    """Ambil data langsung dari BPS berdasarkan var_id (tanpa dataset Satu Data Aceh).

    Digunakan oleh tool bandingkan_data untuk mendapatkan angka resmi terbaru dari BPS.
    Mengembalikan (CsvReadResult, url_bps) atau None jika gagal / API key tidak ada.
    """
    if not _bps_api_key():
        return None
    th_candidates = ["", default_th, "124", "123", "122"]
    sudah_dicoba: set[str] = set()
    for th in th_candidates:
        if th is None or th in sudah_dicoba:
            continue
        sudah_dicoba.add(th)
        url = (
            f"https://webapi.bps.go.id/v1/api/list/model/data/"
            f"domain/{quote(domain, safe='')}/"
            f"var/{quote(var_id, safe='')}/"
            + (f"th/{quote(th, safe='')}/" if th else "")
            + f"key/{quote(_bps_api_key(), safe='')}"
        )
        try:
            teks_csv = bps_payload_ke_csv(await _read_bps_payload(url))
            if not teks_csv:
                continue
            return _analisis_csv(teks_csv, url, 50), url
        except (
            httpx.HTTPError,
            TimeoutError,
            ValueError,
            TypeError,
            KeyError,
            AttributeError,
            IndexError,
        ) as error:
            logger.warning("Pengambilan langsung BPS var=%s th=%s gagal: %s", var_id, th, type(error).__name__)
    return None


def _ekstrak_tahun_dari_df(df: pd.DataFrame) -> tuple[str, str]:
    """Mengekstrak tahun observasi minimum dan maksimum dari DataFrame."""
    tahun_col = None
    for col in df.columns:
        c_clean = str(col).lower().strip()
        if c_clean in {"tahun", "thn", "year", "th", "periode", "waktu"}:
            tahun_col = col
            break

    years: list[int] = []
    if tahun_col is not None:
        for val in df[tahun_col].dropna():
            match = re.search(r"\b(19\d{2}|20\d{2})\b", str(val))
            if match:
                years.append(int(match.group(1)))

    if years:
        return str(min(years)), str(max(years))
    return "", ""


def _deteksi_kolom_indikator(df: pd.DataFrame) -> tuple[str, str]:
    """Mendeteksi nama kolom indikator numerik utama dan satuan (jika ada)."""
    satuan = ""
    kolom_abaikan = {
        "id", "uuid", "tahun", "thn", "year", "periode", "waktu",
        "kode", "bps_kode", "kemendagri_kode", "tingkat_penyajian",
        "bps_kode_provinsi", "kemendagri_kode_provinsi", "bps_nama_provinsi", "kemendagri_nama_provinsi",
        "bps_kode_kabupaten_kota", "kemendagri_kode_kabupaten_kota", "bps_nama_kabupaten_kota", "kemendagri_nama_kabupaten_kota",
        "bps_kode_kecamatan", "kemendagri_kode_kecamatan", "bps_nama_kecamatan", "kemendagri_nama_kecamatan",
        "bps_kode_desa", "kemendagri_kode_desa", "bps_nama_desa", "kemendagri_nama_desa",
        "nama_wilayah", "kode_wilayah", "kategori", "label",
    }
    
    # Cari kolom satuan eksplisit
    for col in df.columns:
        if str(col).lower().strip() in {"satuan", "unit"}:
            vals = df[col].dropna().unique()
            if len(vals) == 1:
                satuan = str(vals[0])
            break

    # Cari kolom indikator/nilai numerik
    kandidat_indikator = []
    for col in df.columns:
        col_clean = str(col).lower().strip()
        if col_clean in kolom_abaikan or col_clean in {"satuan", "unit"}:
            continue
        # Cek apakah tipe data numerik
        if pd.api.types.is_numeric_dtype(df[col]):
            kandidat_indikator.append(str(col))
        elif df[col].dropna().apply(lambda x: str(x).replace(".", "", 1).replace(",", "", 1).isdigit()).all():
            kandidat_indikator.append(str(col))

    kolom_terpilih = kandidat_indikator[0] if kandidat_indikator else ""
    return kolom_terpilih, satuan


_package_files = files(__package__) if __package__ else Path(__file__).parent
_search_synonyms = json.loads(_package_files.joinpath("search_rules.json").read_text(encoding="utf-8"))


def _cocokkan_dataset(katalog: list[dict[str, object]], query: str, max_results: int = 5) -> list[dict[str, object]]:
    query_clean = query.lower().strip()
    if not query_clean:
        return []

    synonyms = _search_synonyms

    terms = {query_clean}
    query_tokens = [t for t in query_clean.split() if len(t) > 1]
    for token in query_tokens:
        terms.add(token)
        for syn in synonyms.get(token, []):
            terms.add(syn)

    scored: list[tuple[int, dict[str, object]]] = []
    for item in katalog:
        identifier = str(item.get("identifier", ""))
        title = str(item.get("title", "")).lower()
        desc = str(item.get("description", "")).lower()
        keywords = [str(k).lower() for k in (item.get("keyword") or []) if isinstance(k, str)]
        publisher = item.get("publisher", {})
        nama_penerbit = str(publisher.get("name", "")).lower() if isinstance(publisher, dict) else ""

        # Skor kecocokan query HARUS dihitung lebih dulu. Boost kurasi/wilayah
        # hanya boleh menjadi penentu urutan setelah dataset benar-benar cocok.
        match_score = 0
        if query_clean in title:
            match_score += 40
        for term in terms:
            if term in title:
                match_score += 12
            if any(term in k for k in keywords):
                match_score += 6
            if term in desc:
                match_score += 2
            if term in nama_penerbit:
                match_score += 2

        if match_score == 0:
            continue

        score = match_score

        # Prioritas dataset strategis yang terkurasi (hanya untuk hasil yang cocok)
        entri_kurasi = BPS_INDICATOR_MAP.get(identifier)
        if entri_kurasi:
            score += 10
            kategori_kurasi = str(entri_kurasi.get("category", "")).lower()
            if kategori_kurasi and kategori_kurasi in query_clean:
                score += 40

        # Prioritas produsen data statistik utama
        if any(prod in nama_penerbit for prod in ["bps", "badan pusat statistik", "bappeda"]):
            score += 5

        # Relevansi spasial wilayah Aceh (tingkatkan dataset lokal Aceh, turunkan agregat nasional)
        if "aceh" in title:
            score += 8
        if "kabupaten" in title or "kota" in title:
            score += 4
        if ("nasional" in title or "indonesia" in title) and ("nasional" not in query_clean and "indonesia" not in query_clean):
            score -= 20

        # Jangan biarkan dataset kemiskinan mendominasi query penduduk biasa.
        if "miskin" in title and "miskin" not in query_clean and "kemiskinan" not in query_clean:
            score -= 25
        # Query "penduduk" sebaiknya mengarah ke seri jumlah penduduk, bukan
        # ke dataset ketenagakerjaan yang kebetulan memuat kata "penduduk".
        if (
            "jumlah penduduk" in title
            and "penduduk" in query_clean
            and "miskin" not in query_clean
            and "kemiskinan" not in query_clean
            and not any(
                kata in title
                for kata in [
                    "berumur",
                    "bekerja",
                    "angkatan kerja",
                    "pekerjaan",
                    "status kawin",
                    "agama",
                    "golongan darah",
                    "disabilitas",
                    "jenjang pendidikan",
                ]
            )
        ):
            score += 35

        # Penalti untuk dokumen non-indikator statistik (kegiatan internal, sop, tata kelola belanja)
        for noise in ["paud", "sop", "aktivitas", "rutin", "penyelenggaraan", "tata kelola", "belanja", "barang jasa", "pengadaan"]:
            if noise in title and noise not in query_clean:
                score -= 30

        scored.append((score, item))

    scored.sort(key=lambda entry: entry[0], reverse=True)
    return [item for _, item in scored[:max_results]]


_comparison_rules = json.loads(_package_files.joinpath("comparison_rules.json").read_text(encoding="utf-8"))

_UNIT_FAMILIES = _comparison_rules["_UNIT_FAMILIES"]

_INDICATOR_FAMILIES = _comparison_rules["_INDICATOR_FAMILIES"]


def _keluarga_satuan(nilai: str) -> str:
    teks = (nilai or "").lower().strip()
    if not teks or teks in {"-", "tidak ada satuan", "none"}:
        return ""
    for keluarga, kata_kunci in _UNIT_FAMILIES.items():
        if any(kata in teks for kata in kata_kunci):
            return keluarga
    return ""


def _skala_satuan(nilai: str) -> str:
    teks = (nilai or "").lower()
    for skala in ("triliun", "miliar", "juta", "ribu"):
        if skala in teks:
            return skala
    return ""


def _satuan_massa(nilai: str) -> str:
    teks = (nilai or "").lower()
    if "ton" in teks:
        return "ton"
    if "kuintal" in teks or "kwintal" in teks:
        return "kuintal"
    if "kilogram" in teks or "kg" in teks:
        return "kilogram"
    if "gram" in teks:
        return "gram"
    return ""


def _keluarga_indikator(nilai: str) -> set[str]:
    teks = (nilai or "").lower()
    return {
        keluarga
        for keluarga, kata_kunci in _INDICATOR_FAMILIES.items()
        if any(kata in teks for kata in kata_kunci)
    }


def _jenis_ukuran(nilai: str) -> str:
    teks = (nilai or "").lower()
    if "kontribusi" in teks or "pangsa" in teks or "peranan" in teks or "share" in teks:
        return "kontribusi"
    if "laju pertumbuhan" in teks or "pertumbuhan" in teks or "growth" in teks:
        return "pertumbuhan"
    if "indeks" in teks or "ihk" in teks:
        return "indeks"
    if "persentase" in teks or "tingkat" in teks:
        return "persentase"
    return ""


def _cek_kesepadanan_indikator(
    judul_sda: str,
    label_bps: str,
    query: str,
    satuan_sda: str = "",
    satuan_bps: str = "",
) -> tuple[bool, str]:
    """Memeriksa apakah dataset Satu Data Aceh dan data BPS sepadan secara metodologis dan spasial.

    Mengembalikan (is_comparable, alasan_jika_tidak_sepadan).
    """
    judul_lower = judul_sda.lower()
    bps_lower = label_bps.lower()

    # 1. Cek tingkat wilayah (Nasional vs Daerah Aceh)
    if ("nasional" in judul_lower) != ("nasional" in bps_lower) or ("indonesia" in judul_lower) != ("indonesia" in bps_lower):
        return False, "Cakupan wilayah berbeda: Satu Data Aceh berisi data agregat Nasional, sedangkan BPS berisi data tingkat Provinsi Aceh / Kabupaten/Kota."

    # 2. Cek dimensi disagregasi (Jenis Kelamin vs Total/Agregat)
    if ("jenis kelamin" in judul_lower or "gender" in judul_lower) and ("jenis kelamin" not in bps_lower and "gender" not in bps_lower):
        return False, "Dimensi disagregasi berbeda: Satu Data Aceh terpilah menurut jenis kelamin (L/P), sedangkan data BPS adalah nilai total/komposit agregat."
    if ("jenis kelamin" in bps_lower or "gender" in bps_lower) and ("jenis kelamin" not in judul_lower and "gender" not in judul_lower):
        return False, "Dimensi disagregasi berbeda: Data BPS terpilah menurut jenis kelamin, sedangkan Satu Data Aceh adalah nilai total/komposit agregat."

    # 3. Cek indikator komponen vs komposit (misal RLS / HLS vs IPM)
    indikator_komponen = {
        "rata-rata lama sekolah": "RLS (Rata-rata Lama Sekolah)",
        "rata rata lama sekolah": "RLS (Rata-rata Lama Sekolah)",
        "harapan lama sekolah": "HLS (Harapan Lama Sekolah)",
        "umur harapan hidup": "UHH (Umur Harapan Hidup)",
        "pengeluaran per kapita": "Pengeluaran Per Kapita",
    }
    for komp_term, komp_label in indikator_komponen.items():
        if komp_term in judul_lower and ("indeks pembangunan manusia" in bps_lower or "ipm" in bps_lower) and komp_term not in bps_lower:
            return False, f"Konsep indikator tidak sepadan: Satu Data Aceh berisi komponen sektoral ({komp_label}), sedangkan BPS adalah Indeks Pembangunan Manusia (IPM) komposit."
        if komp_term in bps_lower and ("indeks pembangunan manusia" in judul_lower or "ipm" in judul_lower) and komp_term not in judul_lower:
            return False, f"Konsep indikator tidak sepadan: Data BPS berisi komponen sektoral ({komp_label}), sedangkan Satu Data Aceh adalah Indeks Pembangunan Manusia (IPM) komposit."

    # 4. Cek ketidakcocokan konsep administratif
    if ("paud" in judul_lower) != ("paud" in bps_lower):
        return False, "Konsep indikator tidak sepadan: Satu Data Aceh adalah data kegiatan/PAUD, bukan indikator statistik makro BPS."

    # 5. Cek satuan. Perbandingan angka hanya bermakna bila keluarga satuannya sama.
    keluarga_sda = _keluarga_satuan(satuan_sda)
    keluarga_bps = _keluarga_satuan(satuan_bps)
    if keluarga_sda and keluarga_bps and keluarga_sda != keluarga_bps:
        return (
            False,
            f"Satuan tidak sepadan: Satu Data Aceh memakai satuan '{satuan_sda}', "
            f"sedangkan BPS memakai '{satuan_bps}'.",
        )
    if keluarga_sda == keluarga_bps and keluarga_sda in {"rupiah", "jumlah"}:
        skala_sda = _skala_satuan(satuan_sda)
        skala_bps = _skala_satuan(satuan_bps)
        if skala_sda != skala_bps and (skala_sda or skala_bps):
            return (
                False,
                f"Skala satuan tidak sepadan: Satu Data Aceh memakai '{satuan_sda}', "
                f"sedangkan BPS memakai '{satuan_bps}'.",
            )
    if keluarga_sda == keluarga_bps == "massa":
        massa_sda = _satuan_massa(satuan_sda)
        massa_bps = _satuan_massa(satuan_bps)
        if massa_sda and massa_bps and massa_sda != massa_bps:
            return (
                False,
                f"Satuan massa tidak sepadan: Satu Data Aceh memakai '{satuan_sda}', "
                f"sedangkan BPS memakai '{satuan_bps}'.",
            )

    if keluarga_sda == keluarga_bps == "jumlah":
        def dimension(unit: str) -> str:
            unit = unit.lower()
            if any(x in unit for x in ("hektar", "hectare", "ha")): return "luas"
            if "rumah tangga" in unit: return "rumah tangga"
            if any(x in unit for x in ("orang", "jiwa")): return "orang"
            return "unit"
        if dimension(satuan_sda) != dimension(satuan_bps):
            return False, "Dimensi satuan tidak sepadan."

    # 6. Cek keluarga indikator. Jika kedua judul jelas-jelas membahas indikator
    #    yang berbeda (mis. stunting vs harapan lama sekolah), jangan paksakan
    #    perbandingan hanya karena query pengguna mengandung satu kata kunci.
    keluarga_judul = _keluarga_indikator(judul_sda)
    keluarga_bps_set = _keluarga_indikator(label_bps)
    if keluarga_judul and keluarga_bps_set and keluarga_judul.isdisjoint(keluarga_bps_set):
        return (
            False,
            "Indikator tidak sepadan: "
            f"Satu Data Aceh membahas {', '.join(sorted(keluarga_judul))}, "
            f"sedangkan BPS membahas {', '.join(sorted(keluarga_bps_set))}.",
        )

    if ("penduduk" in judul_lower and "penduduk" in bps_lower
            and bool(re.search(r"miskin|kemiskinan", judul_lower)) != bool(re.search(r"miskin|kemiskinan", bps_lower))):
        return False, "Indikator tidak sepadan: penduduk total berbeda dari penduduk miskin."
    if bool(re.search(r"per\s*kapita|percapita", judul_lower)) != bool(re.search(r"per\s*kapita|percapita", bps_lower)):
        return False, "Dimensi per kapita berbeda."
    def basis_harga(text: str) -> str:
        if "adhk" in text or "harga konstan" in text: return "konstan"
        if "adhb" in text or "harga berlaku" in text: return "berlaku"
        return ""
    if basis_harga(judul_lower) and basis_harga(bps_lower) and basis_harga(judul_lower) != basis_harga(bps_lower):
        return False, "Basis harga tidak sepadan (ADHB vs ADHK)."

    # 7. Cek jenis ukuran (kontribusi/pangsa vs laju pertumbuhan vs indeks).
    ukuran_sda = _jenis_ukuran(judul_sda)
    ukuran_bps = _jenis_ukuran(label_bps)
    if ukuran_sda and ukuran_bps and ukuran_sda != ukuran_bps:
        return (
            False,
            f"Jenis ukuran tidak sepadan: Satu Data Aceh mengukur '{ukuran_sda}', "
            f"sedangkan BPS mengukur '{ukuran_bps}'.",
        )

    if not keluarga_sda or not keluarga_bps or not keluarga_judul or not keluarga_bps_set:
        return False, "Kesepadanan belum dapat dipastikan: metadata indikator atau satuan belum cukup."
    return True, "Konsep dan satuan sepadan; cocokkan wilayah, kategori, dan periode sebelum membandingkan angka."


def _analisis_csv(teks_csv: str, url: str, baris_maksimal: int) -> CsvReadResult:
    teks_bersih = teks_csv.lstrip("\ufeff \r\n\t")
    if not teks_bersih:
        return CsvReadResult("empty", "", 0, 0, url, "File CSV tidak berisi data.")
    if teks_bersih.startswith("<") and "html" in teks_bersih[:500].lower():
        return CsvReadResult("html", "", 0, 0, url, "Sumber mengembalikan halaman HTML, bukan CSV.")

    try:
        df = pd.read_csv(StringIO(teks_csv))
    except pd.errors.EmptyDataError:
        return CsvReadResult("empty", "", 0, 0, url, "File CSV tidak berisi data.")
    except (pd.errors.ParserError, UnicodeDecodeError, ValueError):
        return CsvReadResult("invalid", "", 0, 0, url, "Format CSV tidak valid.")

    row_count = len(df)
    column_count = len(df.columns)
    if row_count == 0:
        return CsvReadResult(
            "header_only",
            "",
            0,
            column_count,
            url,
            "Sumber CSV hanya berisi header kolom tanpa baris observasi data.",
        )
    tahun_min, tahun_max = _ekstrak_tahun_dari_df(df)
    kolom_ind, satuan = _deteksi_kolom_indikator(df)
    indikator_bps = ""
    if "indikator" in df.columns and "kode_wilayah" in df.columns:
        nilai_indikator = df["indikator"].dropna().unique()
        if len(nilai_indikator) == 1:
            indikator_bps = str(nilai_indikator[0])
    preview = df.head(baris_maksimal).to_markdown(index=False)
    return CsvReadResult(
        "valid",
        preview,
        row_count,
        column_count,
        url,
        "",
        tahun_min,
        tahun_max,
        kolom_ind,
        satuan,
        indikator_bps,
    )


async def _unduh_csv(url: str, baris_maksimal: int) -> CsvReadResult:
    timeout = httpx.Timeout(30.0, connect=10.0)
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=False, event_hooks={"request": [_validate_request_target]}) as client:
        chunks = []
        total_bytes = 0
        async with client.stream("GET", url) as response:
            response.raise_for_status()
            async for chunk in response.aiter_bytes():
                total_bytes += len(chunk)
                if total_bytes > MAX_CSV_BYTES:
                    return CsvReadResult(
                        "too_large", "", 0, 0, url, "File CSV terlalu besar untuk diproses (maksimal 5 MB)."
                    )
                chunks.append(chunk)
    teks_csv = b"".join(chunks).decode("utf-8-sig")
    return _analisis_csv(teks_csv, url, baris_maksimal)


@mcp.custom_route("/health", methods=["GET"], include_in_schema=False)
async def health(_: Request) -> JSONResponse:
    return JSONResponse({"status": "ok", "service": "satu-data-aceh-mcp", "catalog": catalog_status()})


async def _execute_bps(operation: str, parameters: dict, headers) -> dict:
    if operation not in bps_api.OPERATIONS:
        raise ValueError("Operasi tidak dikenal; gunakan bps_endpoints.")
    key = _account_key(bps_api.OPERATIONS[operation]["credential"])
    if key is None:
        key = bps_api.credential(headers, BPS_API_KEY, bps_api.OPERATIONS[operation]["credential"])
    url, public_url, upstream_headers = bps_api.build_request(operation, parameters, key)
    try:
        payload = await _read_bps_payload(url, upstream_headers)
    except (httpx.HTTPError, TimeoutError, ValueError):
        return {"ok": False, "error": "upstream_error", "message": "BPS tidak dapat diakses atau respons melebihi batas; periksa key dan parameter."}
    payload = bps_api.sanitize(payload, [key])
    failed = not isinstance(payload, dict) or bool(payload.get("errors")) or str(payload.get("status", "")).lower() == "error" or not any(k in payload for k in ("data", "datacontent"))
    return {"ok": not failed, "operation": operation, "url": public_url, "data": payload}


@mcp.tool()
async def bps_endpoints(operation: str = "", query: str = "") -> dict:
    """Daftar 59 operasi resmi BPS: domain, data dinamis/statis, publikasi, sensus, perdagangan, SDGs. Isi operation untuk skema parameter lengkap. Tidak memerlukan key."""
    if not await _rate_limiter.allow():
        return {"error": "rate_limited"}
    return bps_api.catalog(operation, query)


@mcp.tool()
async def bps_request(operation: str, parameters: dict[str, str | int] | None = None) -> dict:
    """Jalankan operasi read-only BPS pada semua domain. Temukan operation dan parameter melalui bps_endpoints. Key berasal dari header koneksi, bukan argumen tool. Pertahankan pagination dan dimensi respons asli."""
    if not await _rate_limiter.allow():
        return {"error": "rate_limited"}
    try:
        return await _execute_bps(operation, parameters or {}, _request_headers())
    except ValueError as error:
        return {"ok": False, "error": "invalid_request", "message": str(error)}


@mcp.tool()
async def bps_check_key(service: str = "bps") -> dict:
    """Validasi credential koneksi ke BPS atau SDGs tanpa menampilkan key. Tidak menyimpan credential pengguna."""
    if service not in {"bps", "sdgs"}:
        return {"ok": False, "error": "service harus bps atau sdgs"}
    result = await bps_request("listDomains" if service == "bps" else "getSdgsHome", {"type": "all"} if service == "bps" else {})
    return {"ok": result.get("ok", False), "service": service, "message": "Credential diterima BPS." if result.get("ok") else "Credential belum dapat diverifikasi; periksa key atau koneksi BPS."}


@mcp.custom_route("/", methods=["GET"], include_in_schema=False)
async def landing_page(_: Request):
    return FileResponse(Path(__file__).parent / "static" / "index.html")


@mcp.custom_route("/api/bps/endpoints", methods=["GET"], include_in_schema=False)
async def bps_endpoint_catalog(request: Request):
    try:
        return JSONResponse(bps_api.catalog(request.query_params.get("operation", ""), request.query_params.get("query", "")), headers={"Cache-Control": "no-store"})
    except ValueError as error:
        return JSONResponse({"error": str(error)}, status_code=400)


@mcp.custom_route("/api/bps", methods=["POST"], include_in_schema=False)
async def bps_browser_request(request: Request):
    if not await _rate_limiter.allow(accounts.principal.get()["id"] if accounts.principal.get() else request.client.host if request.client else "local"):
        return JSONResponse({"error": "rate_limited"}, status_code=429)
    try:
        raw = bytearray()
        async for chunk in request.stream():
            raw.extend(chunk)
            if len(raw) > 16_384:
                return JSONResponse({"error": "body_too_large"}, status_code=413)
        body = json.loads(raw)
        if not isinstance(body, dict) or not isinstance(body.get("operation"), str):
            raise ValueError("operation wajib diisi.")
        # Browser requests must supply their own credentials; never use operator's key.
        if not accounts.principal.get():
            bps_api.credential(request.headers, service=bps_api.OPERATIONS.get(body["operation"], {}).get("credential", "bps"))
        result = await _execute_bps(body["operation"], body.get("parameters", {}), request.headers)
        return JSONResponse(result, headers={"Cache-Control": "no-store"})
    except (ValueError, TypeError) as error:
        return JSONResponse({"ok": False, "message": str(error)}, status_code=400, headers={"Cache-Control": "no-store"})


@mcp.tool()
async def search(query: str, wilayah: str = "", produsen: str = "", limit: int = 5, offset: int = 0) -> SearchOutput:
    """Mencari dataset Aceh dan mengembalikan hasil dengan URL yang dapat dikutip."""
    if not await _rate_limiter.allow():
        return SearchOutput(
            results=[],
            message="Batas permintaan tercapai. Coba lagi beberapa saat.",
        )
    query = query.strip() if isinstance(query, str) else ""
    if len(query) > 500 or len(wilayah) > 200 or len(produsen) > 200:
        return SearchOutput(results=[], message="Parameter pencarian terlalu panjang.")
    if not query:
        return SearchOutput(results=[])
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 50 or isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
        return SearchOutput(results=[], message="limit harus 1–50 dan offset harus bilangan bulat nonnegatif.")
    katalog = await muat_katalog()
    filtered = []
    for item in katalog:
        text = " ".join(str(item.get(key) or "") for key in ("title", "description", "keyword")).lower()
        publisher = item.get("publisher")
        name = str(publisher.get("name", "")) if isinstance(publisher, dict) else ""
        if wilayah.strip().lower() in text and produsen.strip().lower() in name.lower():
            filtered.append(item)
    matches = _cocokkan_dataset(filtered, query, max_results=len(filtered))
    results = []
    for item in matches[offset:offset + limit]:
        identifier = str(item.get("identifier", ""))
        results.append(
            SearchResult(
                id=identifier,
                title=str(item.get("title", "Dataset Aceh")),
                url=_halaman_dataset(item) or _url_csv_item(item),
            )
        )
    return SearchOutput(results=results, total=len(matches), offset=offset, next_offset=offset + limit if offset + limit < len(matches) else None)


@mcp.tool()
async def fetch(id: str) -> FetchOutput:
    """Mengambil isi ringkas CSV dataset berdasarkan identifier hasil search."""
    if not await _rate_limiter.allow():
        return FetchOutput(
            id=str(id or "").strip(),
            title="",
            text="Batas permintaan tercapai. Coba lagi beberapa saat.",
            url="",
            error="rate_limited",
        )

    clean_id = str(id).strip() if id else ""
    if not clean_id:
        return FetchOutput(
            id="",
            title="",
            text="Parameter identifier dataset tidak boleh kosong.",
            url="",
            error="invalid_argument",
        )

    katalog = await muat_katalog()
    item = next((entry for entry in katalog if str(entry.get("identifier", "")).strip() == clean_id), None)
    if item is None:
        return FetchOutput(
            id=clean_id,
            title="",
            text=(
                f"Dataset dengan ID '{clean_id}' tidak ditemukan di katalog Satu Data Aceh. "
                f"Gunakan tool 'search' atau 'cari_katalog_data' untuk menemukan identifier yang valid."
            ),
            url="",
            error="not_found",
        )

    csv_url = _url_csv_item(item)
    if not csv_url:
        return FetchOutput(
            id=clean_id,
            title=str(item.get("title", "Dataset Aceh")),
            text=(
                f"Dataset '{clean_id}' ({item.get('title', 'Dataset')}) tidak memiliki "
                f"tautan distribusi CSV yang valid."
            ),
            url=_halaman_dataset(item),
            error="no_csv",
        )

    try:
        result = await _unduh_csv(csv_url, 50)
    except httpx.TimeoutException:
        logger.warning("Timeout saat mengunduh CSV dataset %s (%s)", clean_id, csv_url)
        result = CsvReadResult(
            "timeout", "", 0, 0, csv_url, "Koneksi ke server portal Satu Data Aceh timeout saat mengunduh CSV."
        )
    except httpx.HTTPError as error:
        logger.warning("Gagal mengunduh CSV dataset %s (%s): %s", clean_id, csv_url, error)
        result = CsvReadResult(
            "failed", "", 0, 0, csv_url, f"Gagal mengunduh file CSV dari portal (HTTP {type(error).__name__})."
        )
    except (UnicodeDecodeError, ValueError) as error:
        logger.warning("Format CSV tidak valid untuk dataset %s: %s", clean_id, type(error).__name__)
        result = CsvReadResult("invalid", "", 0, 0, csv_url, "Format file bukan CSV valid atau encoding tidak didukung.")

    source = "Satu Data Aceh"
    reference_source = _halaman_dataset(item)
    if result.status != "valid":
        bps_result = await _ambil_dari_bps(item)
        if bps_result:
            result, bps_source = bps_result
            source = "BPS"
            reference_source = bps_source["reference_url"]
            csv_url = result.source_url

    text = result.preview if result.status == "valid" else result.message
    publisher = item.get("publisher", {})
    period_display = (
        f"{result.tahun_min}–{result.tahun_max}"
        if result.tahun_min and result.tahun_min != result.tahun_max
        else result.tahun_max
    )
    return FetchOutput(
        id=clean_id,
        title=str(item.get("title", "Dataset Aceh")),
        text=text,
        url=_halaman_dataset(item) or csv_url,
        metadata={
            "publisher": publisher,
            "catalog": catalog_status(),
            "csv_url": _redact_secret(csv_url),
            "landing_url": _halaman_dataset(item),
            "source": source,
            "reference_source": reference_source,
            "period": period_display,
            "published_at": item.get("issued", ""),
            "modified_at": item.get("modified", ""),
            "retrieved_at": datetime.now(timezone.utc).isoformat(),
            "observation_start": result.tahun_min,
            "observation_end": result.tahun_max,
            "kolom_indikator": result.kolom_indikator,
            "satuan": result.satuan,
            "indikator_bps": result.indikator_bps,
            "status": result.status,
            "row_count": result.row_count,
            "column_count": result.column_count,
            "message": result.message,
        },
    )

@mcp.tool()
async def cari_katalog_data(kata_kunci: str) -> str:
    """
    Mencari dataset publik di Portal Satu Data Aceh berdasarkan kata kunci.
    Gunakan alat ini setiap kali pengguna meminta informasi statistik atau data dari Aceh.
    
    Args:
        kata_kunci: Kata atau frasa pencarian (contoh: "kemiskinan", "penduduk", "sekolah").
    """
    
    if not await _rate_limiter.allow():
        return "Batas permintaan tercapai. Coba lagi beberapa saat."

    kata_kunci = kata_kunci.strip() if isinstance(kata_kunci, str) else ""
    if not kata_kunci:
        return "Kata kunci pencarian tidak boleh kosong."

    katalog = await muat_katalog()
    
    if not katalog:
        return "Sistem sedang tidak dapat mengakses katalog data.json dari portal."
        
    hasil_pencarian = []
    for item in _cocokkan_dataset(katalog, kata_kunci):
        ident = item.get("identifier", "-")
        judul = item.get("title", "Tanpa Judul")
        publisher = item.get("publisher", {})
        halaman = _halaman_dataset(item)
        link_csv = _url_csv_item(item)
        if link_csv == halaman:
            link_csv = await _cari_link_csv(link_csv) or link_csv
        penerbit = (
            publisher.get("name", "Instansi Tidak Diketahui")
            if isinstance(publisher, dict)
            else "Instansi Tidak Diketahui"
        )
        hasil_pencarian.append(
            f"### {judul}\n"
            f"- **ID Dataset**: `{ident}`\n"
            f"- **Instansi / Produsen Data**: {penerbit}\n"
            f"- **Halaman Portal**: {halaman or '-'}\n"
            f"- **Tautan Unduh Langsung CSV**: {link_csv or '-'}"
        )
                
    if not hasil_pencarian:
        return f"Tidak ditemukan dataset yang cocok dengan kata kunci: '{kata_kunci}'"
        
    return "Berikut adalah hasil pencarian teratas:\n\n" + "\n\n".join(hasil_pencarian)

@mcp.tool()
async def baca_isi_csv(url: str, baris_maksimal: int = 20) -> str:
    """
    Mengunduh dan membaca isi data numerik dari file CSV berdasarkan URL.
    Gunakan alat ini jika Anda (AI) sudah mendapatkan URL CSV dari alat pencarian, 
    dan pengguna meminta Anda menganalisis atau menampilkan angka-angkanya.
    
    Args:
        url: Tautan langsung ke file CSV (biasanya didapat dari hasil cari_katalog_data).
        baris_maksimal: Jumlah baris data yang ingin diambil (default 20, max 50).
    """
    if not await _rate_limiter.allow():
        return "Batas permintaan tercapai. Coba lagi beberapa saat."
    if not isinstance(url, str) or not _url_aman(url):
        return "URL CSV harus menggunakan HTTPS dan alamat publik yang valid."
    if isinstance(baris_maksimal, bool) or not isinstance(baris_maksimal, int):
        return "baris_maksimal harus berupa bilangan bulat antara 1 dan 50."
    baris_maksimal = max(1, min(baris_maksimal, 50))

    try:
        result = await _unduh_csv(url, baris_maksimal)
        if result.status == "header_only":
            return (
                f"⚠️ **File CSV Hanya Berisi Header (0 Baris Observasi Data)**\n\n"
                f"File CSV pada tautan tersebut memiliki struktur kolom ({result.column_count} kolom) "
                f"tetapi belum memiliki baris data/observasi sama sekali.\n"
                f"- URL: {url}\n"
                f"- Silakan gunakan dataset alternatif di portal atau gunakan tool `bandingkan_data` "
                f"untuk menarik data resmi dari BPS."
            )
        if result.status != "valid":
            return f"Data tidak tersedia ({result.status}): {result.message}"
        info_indikator = f", kolom nilai: '{result.kolom_indikator}'" if result.kolom_indikator else ""
        info_satuan = f" ({result.satuan})" if result.satuan else ""
        info_tambahan = (
            f"\n\n*(Catatan: Menampilkan {min(result.row_count, baris_maksimal)} "
            f"baris pertama dari total {result.row_count} baris data"
            f"{f', rentang observasi: {result.tahun_min}–{result.tahun_max}' if result.tahun_min else ''}"
            f"{info_indikator}{info_satuan})*"
        )
        return result.preview + info_tambahan
            
    except httpx.HTTPError:
        return "Gagal mengunduh file CSV dari URL tersebut."
    except (pd.errors.ParserError, pd.errors.EmptyDataError, UnicodeDecodeError, ValueError):
        return "File yang diunduh bukan CSV yang valid atau encoding-nya tidak didukung."
    except ImportError:
        return "Format tabel belum tersedia karena dependency tabulate belum terpasang."


@mcp.tool()
async def bandingkan_data(indikator: str) -> str:
    """
    Mengambil data dari DUA sumber (Satu Data Aceh dan BPS) sekaligus dan
    membandingkan mana yang lebih valid dan terbaru.

    Gunakan alat ini ketika pengguna meminta data statistik resmi Aceh dan Anda
    ingin memastikan angka yang paling akurat dan mutakhir.

    Args:
        indikator: Nama indikator statistik (contoh: "kemiskinan", "IPM", "pengangguran",
                   "inflasi", "PDRB", "gini", "padi", "sayur").
    """
    if not await _rate_limiter.allow():
        return "Batas permintaan tercapai. Coba lagi beberapa saat."

    indikator = indikator.strip() if isinstance(indikator, str) else ""
    if not indikator:
        return "Nama indikator tidak boleh kosong."

    katalog = await muat_katalog()
    bagian: list[str] = []

    # ── Cari di Satu Data Aceh ──────────────────────────────────────────────
    hasil_sda = _cocokkan_dataset(katalog, indikator)
    # Prioritaskan dataset yang sudah diverifikasi punya pasangan BPS.
    hasil_sda.sort(key=lambda item: 0 if _bps_source(item) else 1)

    # Jika tidak ada satu pun kandidat teratas yang punya pasangan BPS, cari
    # dataset terpetakan yang masih cocok dengan query. Ini mencegah tool
    # memilih "Garis Kemiskinan" hanya karena judulnya memuat kata
    # "kemiskinan", lalu membandingkannya dengan persentase penduduk miskin.
    if not any(_bps_source(item) for item in hasil_sda):
        for item in katalog:
            if str(item.get("identifier", "")) not in BPS_INDICATOR_MAP:
                continue
            if _cocokkan_dataset([item], indikator):
                hasil_sda.insert(0, item)
                break
    sda_status = "tidak_ditemukan"
    sda_periode = "-"
    sda_baris = 0
    sda_teks = ""
    sda_judul = "-"
    sda_url = "-"
    selected_sda_item: dict[str, object] | None = None
    result_sda: CsvReadResult | None = None

    if hasil_sda:
        # Cek kandidat teratas (utamakan yang memiliki observasi riil jika kandidat pertama header-only)
        for item in hasil_sda[:3]:
            csv_url = _url_csv_item(item)
            if not csv_url:
                continue
            try:
                res = await _unduh_csv(csv_url, 20)
                if res.status == "valid":
                    selected_sda_item, result_sda = item, res
                    break
                if selected_sda_item is None:
                    selected_sda_item = item
                    result_sda = res
                elif res.status == "valid" and result_sda and result_sda.status != "valid":
                    selected_sda_item = item
                    result_sda = res
                    break
            except (httpx.HTTPError, UnicodeDecodeError, ValueError, TimeoutError, OSError):
                if selected_sda_item is None:
                    selected_sda_item = item
                    result_sda = CsvReadResult("failed", "", 0, 0, csv_url, "Gagal mengunduh file CSV.")

        if selected_sda_item and result_sda:
            sda_judul = str(selected_sda_item.get("title", ""))
            sda_url = _halaman_dataset(selected_sda_item) or _url_csv_item(selected_sda_item)
            sda_status = result_sda.status
            sda_baris = result_sda.row_count
            if result_sda.status == "valid":
                sda_periode = (
                    f"{result_sda.tahun_min}–{result_sda.tahun_max}"
                    if result_sda.tahun_min and result_sda.tahun_min != result_sda.tahun_max
                    else (result_sda.tahun_max or "-")
                )
                sda_teks = result_sda.preview
            elif result_sda.status == "header_only":
                sda_periode = "Tidak ada observasi (0 baris data)"
                sda_teks = "⚠️ File CSV hanya memiliki header tanpa baris data observasi."
            else:
                sda_periode = "-"
                sda_teks = result_sda.message or "Data tidak tersedia."

    bagian.append(
        f"## Sumber 1: Portal Satu Data Aceh\n"
        f"- **Status Data**: `{sda_status}` | **Baris Observasi**: {sda_baris} | **Rentang Tahun Observasi**: {sda_periode}\n"
        f"- **Dataset**: {sda_judul}\n"
        f"- **URL**: {sda_url}\n\n"
        f"{sda_teks if sda_teks else '_Data tidak tersedia._'}"
    )

    # ── Cari di BPS langsung ────────────────────────────────────────────────
    bps_status = "tidak_ditemukan"
    bps_periode = "-"
    bps_baris = 0
    bps_teks = ""
    bps_url_tampil = "-"
    result_bps: CsvReadResult | None = None

    # Tentukan pemetaan variabel BPS
    var_info = None
    if selected_sda_item:
        bps_source_katalog = _bps_source(selected_sda_item)
        if bps_source_katalog:
            var_info = {
                "var": bps_source_katalog["variable"],
                "label": bps_source_katalog.get("label", ""),
                "defaultTh": bps_source_katalog.get("defaultTh", "124"),
            }
    if not var_info:
        var_info = cari_var_bps_dari_kata_kunci(indikator)

    # Label BPS harus berasal dari BPS, bukan dari judul Satu Data Aceh.
    label_bps = (str(var_info.get("label", "")) if var_info else "") or "-"

    if var_info:
        bps_url_tampil = (
            f"https://webapi.bps.go.id/v1/api/list/model/data/"
            f"domain/{BPS_DOMAIN}/var/{var_info['var']}/key/***"
        )
        bps_result_tuple = await _ambil_langsung_dari_bps(
            var_info["var"], BPS_DOMAIN, var_info.get("defaultTh")
        )
        if bps_result_tuple:
            result_bps, bps_url_actual = bps_result_tuple
            if result_bps.indikator_bps:
                label_bps = result_bps.indikator_bps
            bps_status = result_bps.status
            bps_baris = result_bps.row_count
            if result_bps.status == "valid":
                bps_periode = (
                    f"{result_bps.tahun_min}–{result_bps.tahun_max}"
                    if result_bps.tahun_min and result_bps.tahun_min != result_bps.tahun_max
                    else (result_bps.tahun_max or "-")
                )
                bps_teks = result_bps.preview
            else:
                bps_teks = result_bps.message
        elif not _bps_api_key():
            bps_status = "api_key_tidak_ada"
            bps_teks = "BPS API key belum dikonfigurasi. Hubungi pengelola server."
        else:
            bps_status = "failed"
            bps_teks = "Gagal mengambil data dari BPS API."
    else:
        bps_teks = (
            f"Tidak ditemukan variabel BPS yang dipetakan untuk indikator: '{indikator}'.\n"
            f"Daftar indikator yang didukung: kemiskinan, IPM, pengangguran, inflasi, PDRB, "
            f"PDRB per kapita, gini, padi, sayur, dan lainnya."
        )

    bagian.append(
        f"## Sumber 2: BPS Web API (Domain {BPS_DOMAIN} – Provinsi Aceh)\n"
        f"- **Status Data**: `{bps_status}` | **Baris Observasi**: {bps_baris} | **Rentang Tahun Observasi**: {bps_periode}\n"
        f"- **Indikator BPS**: {label_bps} (var: {var_info['var'] if var_info else '-'})\n"
        f"- **Endpoint**: `{bps_url_tampil}`\n\n"
        f"{bps_teks if bps_teks else '_Data tidak tersedia._'}"
    )

    # ── Kesimpulan & Validasi Kesepadanan ─────────────────────────────────────
    rekomendasi = ""
    is_sepadan, alasan_kesepadanan = _cek_kesepadanan_indikator(
        sda_judul,
        label_bps,
        indikator,
        result_sda.satuan if result_sda else "",
        result_bps.satuan if result_bps else "",
    )

    if not is_sepadan and alasan_kesepadanan.startswith("Kesepadanan belum") and sda_status == "valid" and bps_status == "valid":
        rekomendasi = f"⚠️ **Kesepadanan Belum Dapat Dipastikan**: {alasan_kesepadanan}"
    elif not is_sepadan and sda_status == "valid" and bps_status == "valid":
        rekomendasi = (
            f"⚠️ **Incomparable (Tidak Sepadan Secara Langsung)**\n"
            f"- **Catatan Metodologi**: {alasan_kesepadanan}\n"
            f"- Data Satu Data Aceh ('{sda_judul}') dan data BPS ('{label_bps}') tidak mengukur unit/cakupan yang sama, "
            f"sehingga perbandingan angka absolut tidak dapat dilakukan secara langsung.\n"
            f"- **Rekomendasi**: Gunakan BPS Web API untuk data agregat/komposit wilayah Provinsi Aceh, "
            f"atau gunakan Satu Data Aceh jika Anda secara khusus membutuhkan dimensi disagregasi/sektoral tersebut."
        )
    elif sda_status == "valid" and bps_status == "valid":
        max_sda = int(result_sda.tahun_max) if result_sda and result_sda.tahun_max.isdigit() else 0
        max_bps = int(result_bps.tahun_max) if result_bps and result_bps.tahun_max.isdigit() else 0

        if not max_sda or not max_bps:
            rekomendasi = "Tahun observasi belum cukup untuk menentukan sumber terbaru."
        elif max_bps > max_sda and max_bps > 0:
            rekomendasi = (
                f"✅ **BPS** menyediakan data observasi terbaru (tahun **{max_bps}**), "
                f"sedangkan **Satu Data Aceh** menyediakan data hingga tahun **{max_sda}** "
                f"({result_sda.row_count} baris observasi, rentang {sda_periode}).\n"
                f"- **Rekomendasi**: Gunakan **BPS** untuk angka rilis termutakhir dan **Satu Data Aceh** untuk analisis deret waktu historis."
            )
        elif max_sda > max_bps and max_sda > 0:
            rekomendasi = (
                f"✅ **Satu Data Aceh** menyediakan data observasi hingga tahun **{max_sda}** "
                f"(lebih baru dibanding BPS tahun **{max_bps}**).\n"
                f"- **Rekomendasi**: Gunakan data portal Satu Data Aceh sebagai referensi utama."
            )
        else:
            rekomendasi = (
                f"✅ Kedua sumber menyediakan data yang sepadan dengan tahun observasi setara (**{max_bps or max_sda or 'tidak diketahui'}**).\n"
                f"- **Rekomendasi**: Angka BPS dan Satu Data Aceh dapat saling melengkapi."
            )
    elif bps_status == "valid":
        alasan_sda = "hanya berisi header tanpa baris data" if sda_status == "header_only" else "tidak tersedia"
        rekomendasi = (
            f"✅ **BPS Web API** merupakan satu-satunya sumber dengan data valid untuk indikator ini "
            f"(tahun observasi {bps_periode}).\n"
            f"- Dataset di Portal Satu Data Aceh {alasan_sda}."
        )
    elif sda_status == "valid":
        rekomendasi = (
            f"✅ Hanya **Satu Data Aceh** yang memiliki data valid untuk indikator ini (tahun observasi {sda_periode}).\n"
            f"- Gunakan data portal Satu Data Aceh."
        )
    else:
        rekomendasi = "⚠️ Kedua sumber tidak memiliki data yang valid untuk indikator ini. Periksa ketersediaan dataset di portal atau verifikasi BPS API Key Anda."

    kesimpulan = f"---\n## Kesimpulan Perbandingan\n{rekomendasi}"
    return "\n\n---\n\n".join(bagian) + "\n\n" + kesimpulan


def main() -> None:
    """Menjalankan server lokal STDIO atau server remote SSE."""
    transport = os.getenv("MCP_TRANSPORT", "stdio").lower()
    if transport not in {"stdio", "sse", "streamable-http"}:
        raise ValueError("MCP_TRANSPORT harus berupa stdio, sse, atau streamable-http.")
    if transport == "stdio":
        mcp.run(transport=transport)
    else:
        # Accounts are enforced at the ASGI boundary, including SSE message POSTs.
        import uvicorn
        try:
            from .accounts_http import install
        except ImportError:
            from accounts_http import install
        accounts.get_vault()  # Fail closed before binding if the master key is absent/wrong.
        if os.getenv('ACCOUNTS_DEV_HTTP') == '1' and _MCP_HOST not in {'127.0.0.1','localhost','::1'}:
            raise ValueError('ACCOUNTS_DEV_HTTP hanya boleh digunakan pada loopback.')
        if _security_at_runtime:
            app = (mcp.sse_app if transport == 'sse' else mcp.streamable_http_app)(host=_MCP_HOST, transport_security=_transport_security, **({'stateless_http': True} if transport != 'sse' else {}))
        else:
            app = (mcp.sse_app if transport == 'sse' else mcp.streamable_http_app)()
        uvicorn.run(install(app),host=_MCP_HOST,port=_MCP_PORT)


if __name__ == "__main__":
    main()
