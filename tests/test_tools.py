import unittest
from unittest.mock import AsyncMock, patch

import httpx

from src.server import _cari_link_csv, _url_api_csv, baca_isi_csv, cari_katalog_data


class CsvResponse:
    def __init__(self, content, text=None, error=None):
        self.content = content
        self.text = text if text is not None else content.decode("utf-8")
        self.error = error

    def raise_for_status(self):
        if self.error:
            raise self.error


class CsvClient:
    response = CsvResponse(b"nama,nilai\nAceh,10\nSumut,20\n")

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    def raise_for_status(self):
        type(self).response.raise_for_status()

    def stream(self, method, url):
        return self

    async def aiter_bytes(self):
        yield type(self).response.content


class ToolTests(unittest.IsolatedAsyncioTestCase):
    def test_url_api_csv_portal(self):
        result = _url_api_csv(
            {
                "identifier": "dataset-123",
                "description": "Data tahun 2024",
            },
            "https://satudata.acehprov.go.id/datasets/dataset-123",
        )

        self.assertEqual(
            result,
            "https://satudata.acehprov.go.id/api/datasets/dataset-123/datasources/download?tahun=2024",
        )

    def test_url_api_csv_tidak_dibentuk_untuk_host_lain(self):
        result = _url_api_csv(
            {"identifier": "dataset-123"},
            "https://data.example.com/datasets/dataset-123",
        )

        self.assertIsNone(result)

    async def test_mencari_link_csv_di_halaman_html(self):
        CsvClient.response = CsvResponse(
            b'<html><a href="/files/penduduk.csv">Unduh</a></html>'
        )
        try:
            with patch("src.server.httpx.AsyncClient", CsvClient):
                result = await _cari_link_csv(
                    "https://data.example.com/datasets/penduduk"
                )
        finally:
            CsvClient.response = CsvResponse(b"nama,nilai\nAceh,10\n")

        self.assertEqual(result, "https://data.example.com/files/penduduk.csv")

    async def test_halaman_html_tanpa_csv_mengembalikan_none(self):
        CsvClient.response = CsvResponse(b"<html><p>Tidak ada file</p></html>")
        try:
            with patch("src.server.httpx.AsyncClient", CsvClient):
                result = await _cari_link_csv(
                    "https://data.example.com/datasets/penduduk"
                )
        finally:
            CsvClient.response = CsvResponse(b"nama,nilai\nAceh,10\n")

        self.assertIsNone(result)

    async def test_csv_valid_dibatasi_jumlah_baris(self):
        with patch("src.server.httpx.AsyncClient", CsvClient):
            result = await baca_isi_csv("https://data.example.com/data.csv", 1)

        self.assertIn("Aceh", result)
        self.assertNotIn("Sumut", result)
        self.assertIn("Menampilkan 1 baris", result)

    async def test_csv_terlalu_besar_ditolak(self):
        CsvClient.response = CsvResponse(b"x" * (5 * 1024 * 1024 + 1))
        try:
            with patch("src.server.httpx.AsyncClient", CsvClient):
                result = await baca_isi_csv("https://data.example.com/data.csv")
        finally:
            CsvClient.response = CsvResponse(b"nama,nilai\nAceh,10\n")

        self.assertIn("terlalu besar", result)

    async def test_csv_http_error_tidak_membocorkan_detail(self):
        CsvClient.response = CsvResponse(
            b"", error=httpx.HTTPStatusError(
                "secret internal", request=None, response=None
            )
        )
        try:
            with patch("src.server.httpx.AsyncClient", CsvClient):
                result = await baca_isi_csv("https://data.example.com/data.csv")
        finally:
            CsvClient.response = CsvResponse(b"nama,nilai\nAceh,10\n")

        self.assertEqual(result, "Gagal mengunduh file CSV dari URL tersebut.")
        self.assertNotIn("secret internal", result)

    async def test_pencarian_tahan_field_katalog_yang_rusak(self):
        katalog = [
            {"title": "Data Penduduk", "description": None, "publisher": [], "distribution": "rusak"},
            {"title": "Data Penduduk 2", "description": "Penduduk", "publisher": {"name": "BPS"}, "distribution": []},
        ]
        with patch("src.server.muat_katalog", new=AsyncMock(return_value=katalog)):
            result = await cari_katalog_data("penduduk")

        self.assertIn("Data Penduduk", result)
        self.assertIn("Data Penduduk 2", result)
        self.assertIn("Instansi Tidak Diketahui", result)
        self.assertIn("BPS", result)

    async def test_pencarian_menggunakan_keyword_dan_fallback_halaman(self):
        katalog = [
            {
                "title": "Data Kualitas",
                "keyword": ["Laut", "Sampling"],
                "distribution": [
                    {"accessURL": "https://data.example.com/dataset", "format": "html"}
                ],
            }
        ]
        with patch("src.server.muat_katalog", new=AsyncMock(return_value=katalog)), patch(
            "src.server._cari_link_csv", new=AsyncMock(return_value=None)
        ):
            result = await cari_katalog_data("sampling")

        self.assertIn("https://data.example.com/dataset", result)


if __name__ == "__main__":
    unittest.main()
