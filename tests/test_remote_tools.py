import unittest
from unittest.mock import AsyncMock, patch

from src.server import CsvReadResult, FetchOutput, SearchOutput, fetch, health, search


class RemoteToolTests(unittest.IsolatedAsyncioTestCase):
    async def test_search_menghasilkan_output_terstruktur(self):
        katalog = [
            {
                "identifier": "dataset-1",
                "title": "Data Penduduk Aceh",
                "description": "Jumlah penduduk",
                "landingPage": "https://satudata.acehprov.go.id/datasets/dataset-1",
                "distribution": [],
            }
        ]
        with patch("src.server.muat_katalog", new=AsyncMock(return_value=katalog)):
            result = await search("penduduk")

        self.assertIsInstance(result, SearchOutput)
        self.assertEqual(result.results[0].id, "dataset-1")
        self.assertEqual(result.results[0].url, katalog[0]["landingPage"])

    async def test_fetch_menghasilkan_output_terstruktur(self):
        katalog = [
            {
                "identifier": "dataset-1",
                "title": "Data Penduduk Aceh",
                "landingPage": "https://satudata.acehprov.go.id/datasets/dataset-1",
                "distribution": [],
            }
        ]
        with patch("src.server.muat_katalog", new=AsyncMock(return_value=katalog)), patch(
            "src.server._unduh_csv",
            new=AsyncMock(
                return_value=CsvReadResult("valid", "| nama | jumlah |", 1, 2, "https://example.com/data.csv")
            ),
        ):
            result = await fetch("dataset-1")

        self.assertIsInstance(result, FetchOutput)
        self.assertEqual(result.id, "dataset-1")
        self.assertEqual(result.text, "| nama | jumlah |")

    async def test_fetch_identifier_tidak_ditemukan(self):
        with patch("src.server.muat_katalog", new=AsyncMock(return_value=[])):
            with self.assertRaises(ValueError):
                await fetch("missing")

    async def test_fetch_rate_limit_terlampaui(self):
        with patch("src.server._rate_limiter.allow", new=AsyncMock(return_value=False)):
            with self.assertRaises(ValueError) as ctx:
                await fetch("dataset-1")
            self.assertIn("Batas permintaan tercapai", str(ctx.exception))

    async def test_fetch_gagal_unduh_csv_tidak_crash(self):
        import httpx
        katalog = [
            {
                "identifier": "dataset-1",
                "title": "Data Penduduk Aceh",
                "landingPage": "https://satudata.acehprov.go.id/datasets/dataset-1",
                "distribution": [],
            }
        ]
        with patch("src.server.muat_katalog", new=AsyncMock(return_value=katalog)), patch(
            "src.server._unduh_csv",
            new=AsyncMock(side_effect=httpx.HTTPError("Portal offline")),
        ), patch(
            "src.server._ambil_dari_bps",
            new=AsyncMock(return_value=None),
        ):
            result = await fetch("dataset-1")

        self.assertIsInstance(result, FetchOutput)
        self.assertEqual(result.id, "dataset-1")
        self.assertEqual(result.metadata["status"], "failed")
        self.assertIn("Gagal mengunduh", result.text)

    async def test_fetch_gagal_unduh_csv_menggunakan_fallback_bps(self):
        import httpx
        katalog = [
            {
                "identifier": "dataset-1",
                "title": "Data Kemiskinan Aceh",
                "landingPage": "https://satudata.acehprov.go.id/datasets/dataset-1",
                "distribution": [],
            }
        ]
        bps_mock_source = {
            "domain": "1100",
            "variable": "621",
            "reference_url": "https://satudata.acehprov.go.id/datasets/dataset-1",
        }
        bps_mock_result = CsvReadResult("valid", "| kab | miskin |", 1, 2, "https://bps.go.id/data.csv")
        with patch("src.server.muat_katalog", new=AsyncMock(return_value=katalog)), patch(
            "src.server._unduh_csv",
            new=AsyncMock(side_effect=httpx.HTTPStatusError("404 Not Found", request=None, response=None)),
        ), patch(
            "src.server._ambil_dari_bps",
            new=AsyncMock(return_value=(bps_mock_result, bps_mock_source)),
        ):
            result = await fetch("dataset-1")

        self.assertIsInstance(result, FetchOutput)
        self.assertEqual(result.metadata["source"], "BPS")
        self.assertEqual(result.text, "| kab | miskin |")


if __name__ == "__main__":
    unittest.main()
