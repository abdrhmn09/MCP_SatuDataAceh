import unittest
from unittest.mock import patch

import src.server as server


class BpsFallbackTests(unittest.IsolatedAsyncioTestCase):
    async def test_bps_fallback_tidak_aktif_tanpa_api_key(self):
        item = {
            "identifier": "621",
            "title": "Persentase Penduduk Miskin",
            "landingPage": "https://satudata.acehprov.go.id/datasets/621",
        }
        with patch.object(server, "BPS_API_KEY", ""):
            self.assertIsNone(await server._ambil_dari_bps(item))

    async def test_bps_mapping_kemiskinan(self):
        with patch.object(server, "BPS_DATASET_MAP", '{"dataset-aceh-1":"621"}'):
            source = server._bps_source(
                {"identifier": "dataset-aceh-1", "title": "Persentase Penduduk Miskin"}
            )
        self.assertEqual(source["variable"], "621")

    async def test_bps_mapping_tidak_menebak_uuid(self):
        source = server._bps_source(
            {"identifier": "uuid-tidak-dipetakan", "title": "Persentase Penduduk Miskin"}
        )
        self.assertIsNone(source)


if __name__ == "__main__":
    unittest.main()