import json
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch
from starlette.requests import Request
from src import bps_api, server


class BpsApiTests(unittest.TestCase):
    def test_all_documented_operations_build_only_official_urls(self):
        self.assertEqual(len(bps_api.OPERATIONS), 59)
        for name, spec in bps_api.OPERATIONS.items():
            values = {}
            for p in spec['parameters']:
                if not p.get('required'): continue
                schema = p['schema']
                values[p['name']] = schema.get('enum', [None])[0] or (1 if schema.get('type') == 'integer' else '1100000' if p['name'] in {'parent','wilayah'} else '2024' if p['name']=='tahun' else '1100' if p['name'] == 'domain' else 'ind' if p['name'] == 'lang' else '1')
            with self.subTest(operation=name):
                url, public, headers = bps_api.build_request(name, values, 'user-key-1234')
                self.assertTrue(url.startswith('https://webapi.bps.go.id/'))
                self.assertNotIn('{', url)
                self.assertNotIn('user-key-1234', public)
                self.assertEqual(bool(headers), spec['credential'] == 'sdgs')

    def test_key_precedence_and_validation(self):
        self.assertEqual(bps_api.credential({'x-bps-api-key': 'user-key-1234'}, 'operator-key'), 'user-key-1234')
        self.assertEqual(bps_api.credential({'authorization': 'Bearer bearer-key-1234'}), 'bearer-key-1234')
        self.assertEqual(bps_api.credential({'x-bps-api-key': 'user-key-1234', 'x-bps-sdgs-token': 'sdgs-token-1234'}, service='sdgs'), 'sdgs-token-1234')
        for headers in ({'x-bps-api-key': ''}, {'authorization': 'Basic password'}, {'x-bps-api-key': 'bad key'}):
            with self.assertRaises(ValueError): bps_api.credential(headers, 'operator-key')

    def test_rejects_unknown_parameters_and_path_injection(self):
        for operation, params in [('unknown', {}), ('listDomains', {'type': 'all', 'key': 'injected'}), ('listDomains', {'type': 'kabbyprov'}), ('listVariables', {'domain': '../localhost'}), ('getStaticTable', {'domain':'1100', 'id':'%2e%2e', 'lang':'ind'}), ('listVariables', {'domain':'1100', 'page':0})]:
            with self.subTest(operation=operation, params=params):
                with self.assertRaises(ValueError): bps_api.build_request(operation, params, 'user-key-1234')

    def test_landing_artifacts_identical(self):
        root = Path(__file__).parents[1]
        for name in ('index.html','app.js','styles.css','logo.svg','favicon.svg'):
            self.assertEqual((root/'public'/name).read_bytes(), (root/'src/static'/name).read_bytes())


class BpsIsolationTests(unittest.IsolatedAsyncioTestCase):
    async def test_keys_are_request_scoped_and_redacted(self):
        calls=[]
        async def upstream(url, headers):
            calls.append((url, headers))
            return {'status':'OK','data':[{'link':url}]}
        with patch.object(server, '_read_bps_payload', upstream), patch.object(server, 'BPS_API_KEY', 'operator-key'):
            for key in ['alice-key-1234','bob-key-567890']:
                result = await server._execute_bps('listDomains', {'type':'all'}, {'x-bps-api-key':key})
                self.assertTrue(result['ok'])
                self.assertNotIn(key,json.dumps(result))
        self.assertIn('alice-key-1234', calls[0][0])
        self.assertNotIn('alice-key-1234', calls[1][0])

    async def test_sdgs_token_is_sent_as_header(self):
        upstream=AsyncMock(return_value={'data':{'attributes':{'status':'active'}}})
        with patch.object(server, '_read_bps_payload', upstream):
            result=await server._execute_bps('getSdgsHome', {}, {'x-bps-sdgs-token':'sdgs-token-1234'})
        self.assertTrue(result['ok'])
        self.assertEqual(upstream.call_args.args[1], {'Token':'sdgs-token-1234'})

    async def test_legacy_fallback_honors_request_key(self):
        with patch.object(server, '_request_headers', return_value={'authorization':'Bearer user-key-1234'}), patch.object(server, 'BPS_API_KEY','operator-key'):
            url=server._bps_url({'domain':'1100','variable':'42'})
        self.assertIn('user-key-1234',url)
        self.assertNotIn('operator-key',url)

    async def test_browser_endpoint_never_uses_operator_key(self):
        body=json.dumps({'operation':'listDomains','parameters':{'type':'all'}}).encode()
        async def receive(): return {'type':'http.request','body':body,'more_body':False}
        request=Request({'type':'http','method':'POST','path':'/api/bps','headers':[], 'client':('test-browser',1)},receive)
        upstream=AsyncMock()
        with patch.object(server,'BPS_API_KEY','operator-key'),patch.object(server,'_read_bps_payload',upstream):
            result=await server.bps_browser_request(request)
        self.assertEqual(result.status_code,400)
        upstream.assert_not_awaited()
