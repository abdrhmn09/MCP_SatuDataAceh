import unittest
from unittest.mock import AsyncMock, patch

from src.server import FetchOutput, SearchOutput, fetch, health, search


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
            "src.server.baca_isi_csv", new=AsyncMock(return_value="| nama | jumlah |")
        ):
            result = await fetch("dataset-1")

        self.assertIsInstance(result, FetchOutput)
        self.assertEqual(result.id, "dataset-1")
        self.assertEqual(result.text, "| nama | jumlah |")

    async def test_fetch_identifier_tidak_ditemukan(self):
        with patch("src.server.muat_katalog", new=AsyncMock(return_value=[])):
            with self.assertRaises(ValueError):
                await fetch("missing")


if __name__ == "__main__":
    unittest.main()
