import unittest
from unittest.mock import AsyncMock, patch

import src.server as server
from src.bps import BPS_INDICATOR_MAP, BPS_KEYWORD_TO_VAR, bps_payload_ke_csv, cari_var_bps_dari_kata_kunci


class BpsFallbackTests(unittest.IsolatedAsyncioTestCase):
    async def test_bps_fallback_tidak_aktif_tanpa_api_key(self):
        item = {
            "identifier": "621",
            "title": "Persentase Penduduk Miskin",
            "landingPage": "https://satudata.acehprov.go.id/datasets/621",
        }
        with patch.object(server, "BPS_API_KEY", ""):
            self.assertIsNone(await server._ambil_dari_bps(item))

    async def test_bps_mapping_kemiskinan_via_env_override(self):
        """Env override BPS_DATASET_MAP tetap bekerja melalui _BPS_DATASET_MAP_ENV."""
        with patch.object(server, "_BPS_DATASET_MAP_ENV", '{"dataset-aceh-1":"621"}'):
            source = server._bps_source(
                {"identifier": "dataset-aceh-1", "title": "Persentase Penduduk Miskin"}
            )
        self.assertIsNotNone(source)
        self.assertEqual(source["variable"], "621")

    async def test_bps_mapping_dari_indicator_map_bawaan(self):
        """BPS_INDICATOR_MAP bawaan dapat ditemukan langsung dari identifier Satu Data Aceh."""
        # 0116d97b adalah identifier kemiskinan yang sudah dipetakan ke var 621
        source = server._bps_source(
            {
                "identifier": "0116d97b-1b4a-4c6a-a243-33833660fb85",
                "title": "Persentase Penduduk Miskin Aceh Menurut Kabupaten/Kota",
                "landingPage": "https://satudata.acehprov.go.id/datasets/0116d97b-1b4a-4c6a-a243-33833660fb85",
            }
        )
        self.assertIsNotNone(source)
        self.assertEqual(source["variable"], "621")
        self.assertEqual(source["domain"], "1100")

    async def test_bps_mapping_tidak_menebak_uuid(self):
        source = server._bps_source(
            {"identifier": "uuid-tidak-dipetakan", "title": "Persentase Penduduk Miskin"}
        )
        self.assertIsNone(source)

    async def test_bps_mapping_ipm_tersedia(self):
        """IPM terpetakan di BPS_INDICATOR_MAP."""
        source = server._bps_source(
            {
                "identifier": "78794e4b-2bbe-45ef-abd1-0a65c2e98702",
                "title": "Indeks Pembangunan Manusia",
                "landingPage": "https://satudata.acehprov.go.id/datasets/78794e4b",
            }
        )
        self.assertIsNotNone(source)
        self.assertEqual(source["variable"], "498")

    async def test_bps_mapping_pengangguran_tersedia(self):
        """TPT terpetakan di BPS_INDICATOR_MAP."""
        source = server._bps_source(
            {
                "identifier": "97e549de-0a20-452a-9948-455abe2532a8",
                "title": "Tingkat Pengangguran Terbuka",
                "landingPage": "https://satudata.acehprov.go.id/datasets/97e549de",
            }
        )
        self.assertIsNotNone(source)
        self.assertEqual(source["variable"], "529")


class BpsParserTests(unittest.TestCase):
    """Tes untuk parser datacontent Web API BPS."""

    def _buat_payload_bps(self) -> dict:
        """Membuat mock payload respons Web API BPS model/data."""
        return {
            "status": "OK",
            "data-availability": "available",
            "var": [{"val": 621, "label": "Persentase Penduduk Miskin", "unit": "Persen"}],
            "vervar": [
                {"val": 1171, "label": "Banda Aceh"},
                {"val": 1101, "label": "Simeulue"},
            ],
            "tahun": [
                {"val": 141, "label": "2023"},
                {"val": 142, "label": "2024"},
            ],
            "turvar": [{"val": 0, "label": ""}],
            "turtahun": [{"val": 0, "label": "Tahunan"}],
            "datacontent": {
                "1171621014100": 7.12,
                "1171621014200": 7.04,
                "1101621014100": 18.23,
                "1101621014200": 17.95,
            },
        }

    def test_parser_datacontent_menghasilkan_csv(self):
        payload = self._buat_payload_bps()
        csv = bps_payload_ke_csv(payload)
        self.assertIn("Banda Aceh", csv)
        self.assertIn("Simeulue", csv)
        self.assertIn("7.12", csv)
        self.assertIn("18.23", csv)

    def test_parser_datacontent_memiliki_kolom_yang_benar(self):
        payload = self._buat_payload_bps()
        csv = bps_payload_ke_csv(payload)
        baris = csv.splitlines()
        header = baris[0]
        self.assertIn("nama_wilayah", header)
        self.assertIn("tahun", header)
        self.assertIn("nilai", header)

    def test_parser_datacontent_jumlah_baris_sesuai(self):
        import io
        import pandas as pd
        payload = self._buat_payload_bps()
        csv = bps_payload_ke_csv(payload)
        df = pd.read_csv(io.StringIO(csv))
        # 2 wilayah x 2 tahun = 4 baris
        self.assertEqual(len(df), 4)

    def test_parser_payload_tidak_valid_mengembalikan_string_kosong(self):
        self.assertEqual(bps_payload_ke_csv(None), "")
        self.assertEqual(bps_payload_ke_csv("bukan dict"), "")
        self.assertEqual(bps_payload_ke_csv({}), "")

    def test_parser_datacontent_kosong_mengembalikan_string_kosong(self):
        payload = self._buat_payload_bps()
        payload["datacontent"] = {}
        result = bps_payload_ke_csv(payload)
        self.assertEqual(result, "")


class BpsKeywordTests(unittest.TestCase):
    """Tes untuk pencarian kata kunci ke variabel BPS."""

    def test_kata_kunci_ipm_ditemukan(self):
        result = cari_var_bps_dari_kata_kunci("ipm")
        self.assertIsNotNone(result)
        self.assertEqual(result["var"], "498")

    def test_kata_kunci_kemiskinan_ditemukan(self):
        result = cari_var_bps_dari_kata_kunci("kemiskinan")
        self.assertIsNotNone(result)
        self.assertEqual(result["var"], "621")

    def test_kata_kunci_pengangguran_ditemukan(self):
        result = cari_var_bps_dari_kata_kunci("pengangguran")
        self.assertIsNotNone(result)
        self.assertEqual(result["var"], "529")

    def test_kata_kunci_tidak_valid_mengembalikan_none(self):
        result = cari_var_bps_dari_kata_kunci("xyzabc-tidak-ada")
        self.assertIsNone(result)

    def test_indicator_map_mencakup_minimal_10_indikator(self):
        self.assertGreaterEqual(len(BPS_INDICATOR_MAP), 10)

    def test_keyword_map_mencakup_minimal_15_kata_kunci(self):
        self.assertGreaterEqual(len(BPS_KEYWORD_TO_VAR), 15)


class BandinganDataTests(unittest.IsolatedAsyncioTestCase):
    """Tes untuk tool bandingkan_data."""

    async def test_bandingkan_data_indikator_kosong(self):
        from src.server import bandingkan_data
        result = await bandingkan_data("  ")
        self.assertIn("tidak boleh kosong", result)

    async def test_bandingkan_data_tanpa_api_key_tetap_menampilkan_sda(self):
        from src.server import bandingkan_data
        katalog = [
            {
                "identifier": "0116d97b-1b4a-4c6a-a243-33833660fb85",
                "title": "Persentase Penduduk Miskin Aceh Menurut Kabupaten/Kota",
                "landingPage": "https://satudata.acehprov.go.id/datasets/0116d97b",
                "distribution": [],
            }
        ]
        with patch("src.server.muat_katalog", new=AsyncMock(return_value=katalog)), \
             patch("src.server.BPS_API_KEY", ""):
            result = await bandingkan_data("kemiskinan")
        self.assertIn("Sumber 1", result)
        self.assertIn("Sumber 2", result)
        self.assertIn("api_key_tidak_ada", result)

    async def test_bandingkan_data_rate_limit(self):
        from src.server import bandingkan_data
        with patch("src.server._rate_limiter.allow", new=AsyncMock(return_value=False)):
            result = await bandingkan_data("kemiskinan")
        self.assertIn("Batas permintaan", result)


if __name__ == "__main__":
    unittest.main()