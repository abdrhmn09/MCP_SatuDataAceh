import pandas as pd
from io import StringIO
import asyncio
import httpx
import ipaddress
import logging
import os
import re
import time
from collections import deque
from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.parse import quote, urljoin, urlparse
from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel
from starlette.requests import Request
from starlette.responses import JSONResponse

logger = logging.getLogger(__name__)
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)

# Impor fungsi pengelola cache dari package maupun direct script.
try:
    from .cache import muat_katalog
except ImportError:
    from cache import muat_katalog

class SearchResult(BaseModel):
    id: str
    title: str
    url: str


class SearchOutput(BaseModel):
    results: list[SearchResult]


class FetchOutput(BaseModel):
    id: str
    title: str
    text: str
    url: str
    metadata: dict[str, object] | None = None


@dataclass
class CsvReadResult:
    status: str
    preview: str
    row_count: int
    column_count: int
    source_url: str
    message: str = ""


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


class _RateLimiter:
    def __init__(self, limit: int, window_seconds: int = 60):
        self.limit = max(1, limit)
        self.window_seconds = window_seconds
        self.requests = deque()
        self.lock = asyncio.Lock()

    async def allow(self) -> bool:
        now = time.monotonic()
        async with self.lock:
            while self.requests and now - self.requests[0] >= self.window_seconds:
                self.requests.popleft()
            if len(self.requests) >= self.limit:
                return False
            self.requests.append(now)
            return True


# Host hanya dibuka ke publik saat deployment remote memilih MCP_HOST=0.0.0.0.
mcp = FastMCP(
    "Satu Data Aceh Server",
    instructions="Mencari dataset publik Aceh dan membaca data CSV.",
    host=os.getenv("MCP_HOST", "127.0.0.1"),
    port=_env_int("MCP_PORT", _env_int("PORT", 8000)),
)
MAX_CSV_BYTES = 5 * 1024 * 1024
MAX_HTML_BYTES = 2 * 1024 * 1024
DEFAULT_DATA_YEAR = os.getenv("SATU_DATA_ACEH_DATA_YEAR", "2025")
BPS_API_KEY = os.getenv("BPS_API_KEY", "")
BPS_DOMAIN = os.getenv("BPS_DOMAIN", "1100")
RATE_LIMIT_PER_MINUTE = _env_int("MCP_RATE_LIMIT_PER_MINUTE", 60)
_rate_limiter = _RateLimiter(RATE_LIMIT_PER_MINUTE)


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
        return not (
            address.is_private
            or address.is_loopback
            or address.is_link_local
            or address.is_reserved
            or address.is_multicast
        )
    except (TypeError, ValueError):
        return False


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
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
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
    """Membentuk endpoint CSV resmi portal dari metadata DCAT dataset."""
    parsed = urlparse(halaman_dataset)
    if parsed.hostname != "satudata.acehprov.go.id":
        return None

    identifier = str(item.get("identifier", "")).strip()
    slug = identifier or parsed.path.rstrip("/").split("/")[-1]
    if not slug:
        return None

    metadata = " ".join(
        str(item.get(field, "")) for field in ("title", "description", "issued", "modified")
    )
    tahun = next(iter(re.findall(r"\b(20\d{2})\b", metadata)), DEFAULT_DATA_YEAR)
    return (
        f"https://satudata.acehprov.go.id/api/datasets/{quote(slug, safe='')}"
        f"/datasources/download?tahun={tahun}"
    )


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
    identifier = str(item.get("identifier", "")).strip()
    metadata = " ".join(
        str(item.get(field, "")) for field in ("title", "description", "keyword")
    ).lower()
    if "kemiskinan" not in metadata and "penduduk miskin" not in metadata and identifier != "621":
        return None
    return {
        "domain": BPS_DOMAIN,
        "variable": "621",
        "reference_url": _halaman_dataset(item),
    }


def _bps_url(source: dict[str, str]) -> str:
    return (
        "https://webapi.bps.go.id/v1/api/list/model/data/"
        f"domain/{quote(source['domain'], safe='')}/"
        f"var/{quote(source['variable'], safe='')}/"
        f"key/{quote(BPS_API_KEY, safe='')}"
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


async def _ambil_dari_bps(item: dict[str, object]) -> tuple[CsvReadResult, dict[str, str]] | None:
    source = _bps_source(item)
    if not source or not BPS_API_KEY:
        return None
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=10.0)) as client:
            response = await client.get(_bps_url(source))
            response.raise_for_status()
            teks_csv = _bps_payload_to_csv(response.json())
        return _analisis_csv(teks_csv, _bps_url(source), 50), source
    except (httpx.HTTPError, ValueError, TypeError) as error:
        logger.warning("Sumber BPS gagal diproses: %s", type(error).__name__)
        return None


def _cocokkan_dataset(katalog: list[dict[str, object]], query: str) -> list[dict[str, object]]:
    query = query.lower().strip()
    synonyms = {
        "kemiskinan": {"kemiskinan", "miskin", "garis kemiskinan", "penduduk miskin"},
        "miskin": {"kemiskinan", "miskin", "penduduk miskin"},
        "bps": {"bps", "badan pusat statistik", "susenas"},
    }
    terms = {query}
    for token in query.split():
        terms.update(synonyms.get(token, {token}))
    scored: list[tuple[int, dict[str, object]]] = []
    for item in katalog:
        publisher = item.get("publisher", {})
        nama_penerbit = publisher.get("name", "") if isinstance(publisher, dict) else ""
        title = str(item.get("title", "")).lower()
        metadata = " ".join(
            str(value)
            for value in (
                title,
                item.get("description", ""),
                item.get("keyword", []),
                nama_penerbit,
                item.get("identifier", ""),
            )
        ).lower()
        matched = [term for term in terms if term in metadata]
        if matched:
            score = len(matched) + sum(2 for term in matched if term in title)
            scored.append((score, item))
    scored.sort(key=lambda entry: entry[0], reverse=True)
    return [item for _, item in scored[:5]]


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
            "Sumber CSV hanya berisi header tanpa observasi.",
        )
    preview = df.head(baris_maksimal).to_markdown(index=False)
    return CsvReadResult("valid", preview, row_count, column_count, url)


async def _unduh_csv(url: str, baris_maksimal: int) -> CsvReadResult:
    timeout = httpx.Timeout(30.0, connect=10.0)
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
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
    return JSONResponse({"status": "ok", "service": "satu-data-aceh-mcp"})


@mcp.tool()
async def search(query: str) -> SearchOutput:
    """Mencari dataset Aceh dan mengembalikan hasil dengan URL yang dapat dikutip."""
    if not await _rate_limiter.allow():
        raise ValueError("Batas permintaan tercapai. Coba lagi beberapa saat.")
    query = query.strip() if isinstance(query, str) else ""
    if not query:
        return SearchOutput(results=[])
    katalog = await muat_katalog()
    results = []
    for item in _cocokkan_dataset(katalog, query):
        identifier = str(item.get("identifier", ""))
        results.append(
            SearchResult(
                id=identifier,
                title=str(item.get("title", "Dataset Aceh")),
                url=_halaman_dataset(item) or _url_csv_item(item),
            )
        )
    return SearchOutput(results=results)


@mcp.tool()
async def fetch(id: str) -> FetchOutput:
    """Mengambil isi ringkas CSV dataset berdasarkan identifier hasil search."""
    katalog = await muat_katalog()
    item = next((entry for entry in katalog if str(entry.get("identifier", "")) == id), None)
    if item is None:
        raise ValueError("Dataset tidak ditemukan untuk identifier tersebut.")
    csv_url = _url_csv_item(item)
    if not csv_url:
        raise ValueError("Dataset tidak memiliki URL CSV yang dapat diakses.")
    result = await _unduh_csv(csv_url, 50)
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
    return FetchOutput(
        id=id,
        title=str(item.get("title", "Dataset Aceh")),
        text=text,
        url=_halaman_dataset(item) or csv_url,
        metadata={
            "publisher": publisher,
            "csv_url": csv_url,
            "landing_url": _halaman_dataset(item),
            "source": source,
            "reference_source": reference_source,
            "period": item.get("modified") or item.get("issued") or "",
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
        judul = item.get("title", "")
        publisher = item.get("publisher", {})
        link_csv = _url_csv_item(item)
        if link_csv == _halaman_dataset(item):
            link_csv = await _cari_link_csv(link_csv) or link_csv
        penerbit = (
            publisher.get("name", "Instansi Tidak Diketahui")
            if isinstance(publisher, dict)
            else "Instansi Tidak Diketahui"
        )
        hasil_pencarian.append(
            f"- **Judul Dataset**: {judul}\n"
            f"  **Instansi**: {penerbit}\n"
            f"  **Tautan CSV**: {link_csv}"
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
        if result.status != "valid":
            return f"Data tidak tersedia ({result.status}): {result.message}"
        info_tambahan = (
            f"\n\n*(Catatan: Menampilkan {min(result.row_count, baris_maksimal)} "
            f"baris pertama dari total {result.row_count} baris data)*"
        )
        return result.preview + info_tambahan
            
    except httpx.HTTPError:
        return "Gagal mengunduh file CSV dari URL tersebut."
    except (pd.errors.ParserError, pd.errors.EmptyDataError, UnicodeDecodeError, ValueError):
        return "File yang diunduh bukan CSV yang valid atau encoding-nya tidak didukung."
    except ImportError:
        return "Format tabel belum tersedia karena dependency tabulate belum terpasang."

def main() -> None:
    """Menjalankan server lokal STDIO atau server remote SSE."""
    transport = os.getenv("MCP_TRANSPORT", "stdio").lower()
    if transport not in {"stdio", "sse", "streamable-http"}:
        raise ValueError("MCP_TRANSPORT harus berupa stdio, sse, atau streamable-http.")
    mcp.run(transport=transport)


if __name__ == "__main__":
    main()