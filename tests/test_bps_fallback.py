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
        source = server._bps_source(
            {"identifier": "621", "title": "Persentase Penduduk Miskin"}
        )
        self.assertEqual(source["domain"], server.BPS_DOMAIN)
        self.assertEqual(source["variable"], "621")


if __name__ == "__main__":
    unittest.main()