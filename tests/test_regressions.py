import asyncio
import json
import logging
import socket
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx

from src import server
from src.bps import bps_payload_ke_csv


class StatisticalRegressionTests(unittest.TestCase):
    def test_shared_comparability_cases(self):
        cases = json.loads((Path(__file__).parent / "fixtures/comparability.json").read_text())
        for case in cases:
            with self.subTest(case=case):
                ok, reason = server._cek_kesepadanan_indikator(
                    case["title"], case["label"], "", case["unit_a"], case["unit_b"]
                )
                status = "comparable" if ok else "unknown" if reason.startswith("Kesepadanan belum") else "incomparable"
                self.assertEqual(status, case["status"])

    def test_year_is_not_inferred_from_values_or_codes(self):
        result = server._analisis_csv("kode,nilai\n2024,2025\n", "https://example.com/data.csv", 20)
        self.assertEqual((result.tahun_min, result.tahun_max), ("", ""))

    def test_bps_preserves_year_category_and_subperiod(self):
        payload = {
            "var": [{"val": 42, "label": "Kemiskinan", "unit": "Persen"}],
            "vervar": [{"val": 1101, "label": "Simeulue"}],
            "tahun": [{"val": 124, "label": "2024"}, {"val": 125, "label": "2025"}],
            "turvar": [{"val": 1, "label": "Kota"}, {"val": 2, "label": "Desa"}],
            "turtahun": [{"val": 1, "label": "Maret"}, {"val": 2, "label": "September"}],
            "datacontent": {"11014211241": 12, "11014221252": 15},
        }
        result = server._analisis_csv(bps_payload_ke_csv(payload), "https://example.com/bps", 20)
        self.assertEqual((result.tahun_min, result.tahun_max), ("2024", "2025"))
        for value in ("Kota", "Desa", "Maret", "September"):
            self.assertIn(value, result.preview)
        payload["datacontent"]["unknown-key"] = 999
        self.assertEqual(bps_payload_ke_csv(payload), "")

    def test_log_redacts_bps_key(self):
        record = logging.LogRecord("httpx", logging.INFO, "", 0, "GET %s", ("https://webapi.bps.go.id/key/test-secret/",), None)
        server._SecretFilter().filter(record)
        self.assertNotIn("test-secret", record.getMessage())


class SecurityRegressionTests(unittest.IsolatedAsyncioTestCase):
    async def test_pins_public_dns_result_and_preserves_tls_hostname(self):
        loop = asyncio.get_running_loop()
        answer = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443))]
        request = httpx.Request("GET", "https://public.example.com/data.csv")
        with patch.object(loop, "getaddrinfo", AsyncMock(return_value=answer)):
            await server._validate_request_target(request)
        self.assertEqual(request.url.host, "8.8.8.8")
        self.assertEqual(request.headers["Host"], "public.example.com")
        self.assertEqual(request.extensions["sni_hostname"], "public.example.com")

    async def test_rate_limit_separates_clients(self):
        limiter = server._RateLimiter(limit=1)
        self.assertTrue(await limiter.allow("client-a"))
        self.assertFalse(await limiter.allow("client-a"))
        self.assertTrue(await limiter.allow("client-b"))

    async def test_search_filters_before_ranking_and_paginates(self):
        catalog = [{"identifier": str(i), "title": "Jumlah Penduduk Aceh", "publisher": {"name": "BPS"}} for i in range(8)]
        catalog.append({"identifier": "other", "title": "Jumlah Penduduk Medan", "publisher": {"name": "BPS"}})
        with patch.object(server, "muat_katalog", AsyncMock(return_value=catalog)):
            result = await server.search("penduduk", wilayah="Aceh", produsen="BPS", limit=3, offset=3)
        self.assertEqual([r.id for r in result.results], ["3", "4", "5"])
        self.assertEqual(result.total, 8)
        self.assertEqual(result.next_offset, 6)

    async def test_fetch_does_not_return_bps_key(self):
        item = {"identifier": "dataset", "title": "IPM", "landingPage": "https://example.com/dataset", "distribution":[{"format":"csv","downloadURL":"https://webapi.bps.go.id/key/test-secret/"}]}
        result = server.CsvReadResult("valid", "table", 1, 2, "https://webapi.bps.go.id/key/test-secret/")
        with patch.object(server, "muat_katalog", AsyncMock(return_value=[item])), \
             patch.object(server, "_unduh_csv", AsyncMock(return_value=server.CsvReadResult("empty", "", 0, 0, ""))), \
             patch.object(server, "_ambil_langsung_dari_bps", AsyncMock(return_value=(result, {"reference_url": "https://webapi.bps.go.id/"}))), \
             patch.object(server._rate_limiter, "allow", AsyncMock(return_value=True)):
            output = await server.fetch("dataset")
        self.assertNotIn("test-secret", output.model_dump_json())
        self.assertIn("***", output.metadata["csv_url"])

    async def test_private_dns_answer_is_rejected(self):
        loop = asyncio.get_running_loop()
        answer = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.1", 443))]
        with patch.object(loop, "getaddrinfo", AsyncMock(return_value=answer)):
            with self.assertRaises(httpx.RequestError):
                await server._validate_request_target(httpx.Request("GET", "https://public.example.com/data.csv"))

    async def test_bps_period_metadata_is_used_instead_of_fixed_years(self):
        requests = []
        def handler(request):
            requests.append(request)
            return httpx.Response(200,json={'status':'OK','data':[{'pages':1},[{'th_id':126,'th':'2026'}]]} if '/model/th/' in request.url.path else {'data':[{'tahun':2026,'nilai':10}]})
        real_client=httpx.AsyncClient
        with patch.object(server, 'BPS_API_KEY', 'test-secret'), patch.object(server.httpx,'AsyncClient',side_effect=lambda **kwargs:real_client(transport=httpx.MockTransport(handler),**kwargs)):
            result=await server._ambil_langsung_dari_bps('42')
        self.assertIsNotNone(result)
        self.assertIn('/model/th/',str(requests[0].url))
        self.assertIn('/th/126/',str(requests[1].url))
        self.assertTrue(result[0].freshness['metadata_complete'])
