import asyncio
from collections import Counter
import unittest
from unittest.mock import AsyncMock, Mock, patch

import httpx

from src import bps_api, bps_diagnostics, server


class DiagnosticSamplesTests(unittest.TestCase):
    def test_all_operations_have_valid_samples_and_correct_credential(self):
        operations = list(bps_diagnostics.ordered_operations())
        self.assertEqual(len(operations), 59)
        self.assertEqual(set(operations), set(bps_api.OPERATIONS))
        counts = Counter()
        for name in operations:
            with self.subTest(operation=name):
                for dependency in bps_diagnostics.DEPENDENCIES.get(name, ()):
                    self.assertLess(operations.index(dependency), operations.index(name))
                parameters = bps_diagnostics.sample_parameters(name, {})
                url, public_url, headers = bps_api.build_request(name, parameters, "fixture-secret")
                self.assertTrue(url.startswith("https://webapi.bps.go.id/"))
                self.assertNotIn("fixture-secret", public_url)
                service = bps_api.OPERATIONS[name]["credential"]
                counts[service] += 1
                self.assertEqual(headers, {"Token": "fixture-secret"} if service == "sdgs" else {})
        self.assertEqual(counts, {"bps": 51, "sdgs": 8})

    def test_detail_uses_ids_and_domain_from_the_list(self):
        previous = {
            "listPressReleases": ({"ok": True, "data": {"data": [{"page": 1}, [{"brs_id": "brs-42"}]]}},
                                  {"domain": "1100"}),
            "listPeriods": ({"ok": True, "data": {"data": [{"th_id": 125}]}},
                            {"domain": "1100", "var": 564}),
            "listGlossary": ({"ok": True, "data": {"data": [{"_source": {"id": "4406"}}]}}, {}),
            "listCsaTables": ({"ok": True, "data": {"data": [{"id": "sample-table", "latest_period": "2022"}]}},
                              {"domain": "1100"}),
        }
        self.assertEqual(bps_diagnostics.sample_parameters("getPressRelease", previous),
                         {"id": "brs-42", "lang": "ind", "domain": "1100"})
        self.assertEqual(bps_diagnostics.sample_parameters("getData", previous),
                         {"domain": "1100", "var": 564, "th": "125"})
        self.assertEqual(bps_diagnostics.sample_parameters("getGlossaryEntry", previous)["id"], 4406)
        self.assertEqual(bps_diagnostics.sample_parameters("getCsaTable", previous),
                         {"id": "sample-table", "lang": "ind", "domain": "1100", "year": 2022})
        self.assertEqual(bps_diagnostics.sample_parameters("getPressRelease", {})["domain"], "0000")

    def test_sdgs_pagination_and_literal_filter_names(self):
        params = {"filters[name]": "perguruan tinggi", "page[number]": 2, "page[size]": 10}
        url, _, headers = bps_api.build_request("listSdgsDatasets", params, "fixture-token")
        self.assertEqual(dict(httpx.URL(url).params), {key: str(value) for key, value in params.items()})
        self.assertEqual(headers, {"Token": "fixture-token"})
        with self.assertRaisesRegex(ValueError, "satu filter"):
            bps_api.build_request("listSdgsDatasets", {**params, "filters[goal_id]": "4"}, "fixture-token")
        with self.assertRaisesRegex(ValueError, "Token SDGs"):
            bps_api.credential({"authorization": "Bearer regular-bps-key"}, service="sdgs")

    def test_upstream_shapes_are_distinguished(self):
        for data, expected in [
            ({"status": "OK", "data-availability": "list-not-available"}, "data_unavailable"),
            ({"status": "list-not-available"}, "data_unavailable"),
            ({"data": [{"page": 1}, {"status": 200, "data": []}]}, "data_unavailable"),
            ({"data": {"sdgsDatasets": {"content": []}}}, "data_unavailable"),
            ({"data": {"sdgsGoals": []}}, "data_unavailable"),
            ({"status": "error", "errors": [{"status": "401"}]}, "credential_rejected"),
            ({"meta": {"status": {"code": 429}}, "data": []}, "upstream_rate_limited"),
            ({"status": "OK"}, "upstream_invalid_response"),
            ({"data": [{"page": 1}, [{"id": 7}]]}, None),
            ({"data": [{"page": 1}, {"status": 200, "data": [["Laki-laki", 97.8]]}]}, None),
            ({"datacontent": {"key": 0}}, None),
        ]:
            with self.subTest(data=data):
                self.assertEqual(bps_api.payload_error(data), expected)


def status_exception(status, retry_after=None):
    request = httpx.Request("GET", "https://webapi.bps.go.id/")
    headers = {"Retry-After": retry_after} if retry_after is not None else {}
    response = httpx.Response(status, request=request, headers=headers)
    return httpx.HTTPStatusError("test", request=request, response=response)


class DiagnosticRunnerTests(unittest.IsolatedAsyncioTestCase):
    async def test_retryable_timeout_and_status_respect_budget(self):
        cases = [
            ([httpx.ReadTimeout("test"), {"data": [{"id": 1}]}], "passed", 2),
            ([status_exception(503, "60")], "upstream_error", 1),
            ([status_exception(429, "10")], "upstream_rate_limited", 1),
            ([status_exception(403)], "credential_rejected", 1),
            ([ValueError("invalid JSON")], "upstream_invalid_response", 1),
        ]
        for side_effect, expected, count in cases:
            with self.subTest(expected=expected):
                upstream = AsyncMock(side_effect=side_effect)
                with patch.object(server.asyncio, "sleep", AsyncMock()):
                    result = await server._execute_bps("listDomains", {"type": "prov"},
                                                       {"x-bps-api-key": "fixture-key"}, read=upstream)
                self.assertEqual("passed" if result["ok"] else result["error"], expected)
                self.assertEqual(result["operation"], "listDomains")
                self.assertEqual(upstream.await_count, count)

    async def test_rate_limit_skips_only_affected_credential(self):
        vault = Mock()
        vault.get_key.side_effect = lambda _, service: "key-" + service
        user = {"id": "test-user", "raw": "session"}
        async def probe(name, parameters, headers, **kwargs):
            if name == "listDomains":
                return bps_api.failure(name, "upstream_rate_limited")
            return {"ok": True, "operation": name, "data": {"data": [{"id": 1}]}}
        with patch.object(server, "_execute_bps", side_effect=probe) as call:
            events = [event async for event in server._bps_diagnostic_events(user, vault)]
        results = [event for event in events if event["type"] == "operation"]
        self.assertEqual(len(results), 59)
        self.assertEqual(Counter(row["status"] for row in results), {"failed": 1, "not_tested": 50, "passed": 8})
        self.assertEqual(call.await_count, 9)
        self.assertNotIn("test-user", server._active_bps_diagnostics)

    async def test_cancellation_and_duplicate_run_release_slot(self):
        vault = Mock()
        user = {"id": "cancelled-user", "raw": "session"}
        generator = server._bps_diagnostic_events(user, vault)
        self.assertEqual((await anext(generator))["type"], "start")
        duplicate = [event async for event in server._bps_diagnostic_events(user, vault)]
        self.assertEqual(duplicate[0]["type"], "error")
        await generator.aclose()
        self.assertNotIn(user["id"], server._active_bps_diagnostics)

    async def test_missing_credentials_and_dependency_report_unexecuted(self):
        vault = Mock()
        vault.get_key.side_effect = lambda _, service: "fixture-bps" if service == "bps" else ""
        user = {"id": "missing-user", "raw": "session"}

        def samples(name, previous):
            return None if name == "getPressRelease" else bps_diagnostics.SAMPLES[name]

        with patch.object(server.bps_diagnostics, "sample_parameters", side_effect=samples), patch.object(
                server, "_execute_bps", AsyncMock(return_value={"ok": False, "error": "data_unavailable"})):
            events = [event async for event in server._bps_diagnostic_events(user, vault)]
        results = {event["operation"]: event for event in events if event["type"] == "operation"}
        self.assertEqual(results["getPressRelease"]["code"], "missing_sample")
        self.assertIn("listPressReleases", results["getPressRelease"]["message"])
        self.assertEqual(results["listSdgsGoals"]["code"], "missing_credential")
        self.assertEqual(results["listCsaTables"]["status"], "unavailable")
