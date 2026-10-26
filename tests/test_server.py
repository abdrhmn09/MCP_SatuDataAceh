import unittest

from src.server import _url_aman, baca_isi_csv, cari_katalog_data


class ServerValidationTests(unittest.IsolatedAsyncioTestCase):
    def test_url_aman_menolak_url_tidak_aman(self):
        self.assertFalse(_url_aman("http://example.com/data.csv"))
        self.assertFalse(_url_aman("https://127.0.0.1/data.csv"))
        self.assertFalse(_url_aman("https://localhost/data.csv"))
        self.assertTrue(_url_aman("https://data.example.com/data.csv"))

    async def test_keyword_kosong(self):
        self.assertEqual(
            await cari_katalog_data("  "),
            "Kata kunci pencarian tidak boleh kosong.",
        )

    async def test_url_csv_ditolak_sebelum_request(self):
        result = await baca_isi_csv("http://example.com/data.csv", 20)
        self.assertIn("HTTPS", result)

    async def test_limit_baris_tidak_valid(self):
        result = await baca_isi_csv("https://example.com/data.csv", "20")
        self.assertIn("bilangan bulat", result)

    def test_entrypoint_main_tersedia(self):
        import src.main as src_main
        import src.__main__ as src_pkg_main
        from src.server import main as server_main

        self.assertIs(src_main.main, server_main)
        self.assertIs(src_pkg_main.main, server_main)


if __name__ == "__main__":
    unittest.main()
