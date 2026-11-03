"""OAuth interoperability, replay protection, isolation and account lifecycle regressions."""
import asyncio
import base64
import hashlib
import json
import secrets
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch, AsyncMock
from urllib.parse import parse_qs, urlsplit, urlencode

import httpx
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route

from src.accounts import Vault, digest
from src.accounts_http import install
from src.oauth import OAuthStore


class OAuthTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.key = base64.b64encode(secrets.token_bytes(32)).decode()
        self.vault = Vault(Path(self.temp.name) / 'vault.sqlite3', self.key)
        self.env = patch.dict('os.environ', {'ACCOUNTS_PUBLIC_ORIGIN': 'https://app.test', 'ACCOUNTS_DEV_HTTP': '0'})
        self.env.start()
        self.patches = [patch('src.accounts.get_vault', return_value=self.vault), patch('src.accounts_http.get_vault', return_value=self.vault), patch('src.oauth_http.get_vault', return_value=self.vault)]
        for p in self.patches: p.start()
        async def mcp(request):
            from src.accounts import principal
            return JSONResponse({'user': principal.get()['id']})
        self.app = install(Starlette(routes=[Route('/mcp', mcp, methods=['POST']), Route('/sse', mcp)]))
        self.http = httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app), base_url='https://app.test', follow_redirects=False)
        self.uid, self.recovery = self.vault.register('oauth@example.test', 'synthetic password for OAuth')
        self.vault.verify_email(self.vault.verification_token(self.uid))
        self.session = self.vault.login('oauth@example.test', 'synthetic password for OAuth')
        self.http.cookies.set('__Host-mcp_session', self.session)
        self.headers = {'Origin': 'https://app.test', 'X-CSRF-Token': self.vault.csrf(self.session)}
        self.store = OAuthStore(self.vault)
        self.client = await self.register()
        self.resource = 'https://app.test/mcp'
        self.verifier = secrets.token_urlsafe(48)
        self.challenge = base64.urlsafe_b64encode(hashlib.sha256(self.verifier.encode()).digest()).decode().rstrip('=')

    async def asyncTearDown(self):
        await self.http.aclose()
        for p in self.patches: p.stop()
        self.env.stop()
        self.temp.cleanup()

    async def register(self, **changes):
        r = await self.http.post('/register', json={'redirect_uris': ['https://client.test/callback'], 'client_name': 'Synthetic AI', 'token_endpoint_auth_method': 'none', **changes})
        self.assertEqual(r.status_code, 201, r.text)
        return r.json()

    def authorization(self, **changes):
        return {'client_id': self.client['client_id'], 'redirect_uri': 'https://client.test/callback', 'response_type': 'code', 'code_challenge': self.challenge, 'code_challenge_method': 'S256', 'scope': 'data:read', 'state': 'state-synthetic', 'resource': self.resource, **changes}

    async def pending(self, **changes):
        r = await self.http.get('/authorize', params=self.authorization(**changes))
        self.assertEqual(r.status_code, 302, r.text)
        self.assertNotIn('code=', r.headers['location'])
        return parse_qs(urlsplit(r.headers['location']).fragment)['oauth'][0]

    async def code(self, **changes):
        pending = await self.pending(**changes)
        details = await self.http.post('/api/oauth/consent', headers=self.headers, json={'request': pending})
        self.assertEqual(details.status_code, 200, details.text)
        r = await self.http.post('/api/oauth/consent', headers=self.headers, json={'request': pending, 'decision': 'approve'})
        self.assertEqual(r.status_code, 200, r.text)
        query = parse_qs(urlsplit(r.json()['redirect']).query)
        self.assertEqual(query['state'], ['state-synthetic'])
        self.assertEqual(query['iss'], ['https://app.test'])
        return query['code'][0]

    def exchange(self, code, **changes):
        return self.http.post('/token', data={'grant_type': 'authorization_code', 'client_id': self.client['client_id'], 'redirect_uri': 'https://client.test/callback', 'code': code, 'code_verifier': self.verifier, 'resource': self.resource, **changes})

    def refresh(self, token, **changes):
        return self.http.post('/token', data={'grant_type': 'refresh_token', 'client_id': self.client['client_id'], 'refresh_token': token, 'resource': self.resource, **changes})

    async def test_discovery_cors_and_unauthorized_challenge(self):
        r = await self.http.post('/mcp')
        self.assertEqual(r.status_code, 401)
        self.assertIn('resource_metadata="https://app.test/.well-known/oauth-protected-resource/mcp"', r.headers['www-authenticate'])
        for path in ['/.well-known/oauth-protected-resource', '/.well-known/oauth-protected-resource/mcp', '/.well-known/oauth-protected-resource/sse']:
            r = await self.http.get(path, headers={'Origin': 'https://arbitrary-client.test'})
            self.assertEqual(r.status_code, 200)
            self.assertEqual(r.headers['access-control-allow-origin'], '*')
            self.assertEqual(r.json()['authorization_servers'], ['https://app.test'])
        meta = (await self.http.get('/.well-known/oauth-authorization-server')).json()
        self.assertIn('S256', meta['code_challenge_methods_supported'])
        self.assertIn('none', meta['token_endpoint_auth_methods_supported'])
        self.assertTrue(meta['authorization_response_iss_parameter_supported'])
        r = await self.http.options('/token', headers={'Origin': 'https://client.test', 'Access-Control-Request-Method': 'POST', 'Access-Control-Request-Headers': 'authorization,content-type'})
        self.assertEqual(r.status_code, 200, r.text)

    async def test_complete_flow_hash_storage_restart_refresh_and_revoke(self):
        code = await self.code()
        r = await self.exchange(code)
        self.assertEqual(r.status_code, 200, r.text)
        tokens = r.json()
        access, refresh = tokens['access_token'], tokens['refresh_token']
        self.assertEqual(tokens['scope'], 'data:read')
        self.assertEqual((await self.http.post('/mcp', headers={'Authorization': 'Bearer ' + access})).json()['user'], self.uid)
        # OAuth credentials never authenticate dashboard/account APIs.
        self.http.cookies.clear()
        self.assertEqual((await self.http.get('/api/account/me', headers={'Authorization': 'Bearer ' + access})).status_code, 401)
        restarted = OAuthStore(Vault(self.vault.path, self.key))
        self.assertIsNotNone(restarted.identity(access, self.resource))
        for secret in [code, access, refresh, self.verifier]:
            self.assertNotIn(secret.encode(), Path(self.vault.path).read_bytes())
        r = await self.refresh(refresh)
        self.assertEqual(r.status_code, 200, r.text)
        rotated = r.json()
        self.assertNotEqual(rotated['refresh_token'], refresh)
        self.assertEqual((await self.http.post('/mcp', headers={'Authorization': 'Bearer ' + access})).status_code, 401)
        self.assertEqual((await self.http.post('/mcp', headers={'Authorization': 'Bearer ' + rotated['access_token']})).status_code, 200)
        r = await self.http.post('/revoke', data={'client_id': self.client['client_id'], 'token': rotated['refresh_token']})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual((await self.refresh(rotated['refresh_token'])).status_code, 400)
        self.assertEqual((await self.http.post('/mcp', headers={'Authorization': 'Bearer ' + rotated['access_token']})).status_code, 401)

    async def test_pkce_redirect_resource_client_and_code_replay(self):
        code = await self.code()
        for changes in [{'code_verifier': 'wrong'}, {'redirect_uri': 'https://evil.test/callback'}, {'resource': 'https://app.test/sse'}, {'client_id': (await self.register())['client_id']}]:
            r = await self.exchange(code, **changes)
            self.assertIn(r.status_code, [400, 401], r.text)
        r = await self.exchange(code)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual((await self.exchange(code)).status_code, 400)
        # An access token for /mcp cannot be used on the separate /sse resource.
        self.assertEqual((await self.http.get('/sse', headers={'Authorization': 'Bearer ' + r.json()['access_token']})).status_code, 401)

    async def test_refresh_replay_revokes_family_and_scope_escalation_fails(self):
        tokens = (await self.exchange(await self.code())).json()
        self.assertEqual((await self.refresh(tokens['refresh_token'], scope='admin')).status_code, 400)
        rotated = (await self.refresh(tokens['refresh_token'])).json()
        self.assertEqual((await self.refresh(tokens['refresh_token'])).status_code, 400)
        self.assertEqual((await self.refresh(rotated['refresh_token'])).status_code, 400)
        self.assertIsNone(self.store.identity(rotated['access_token'], self.resource))

    async def test_consent_requires_session_csrf_inspection_and_single_use(self):
        pending = await self.pending()
        body = {'request': pending, 'decision': 'approve'}
        self.assertEqual((await self.http.post('/api/oauth/consent', headers=self.headers, json=body)).status_code, 400)
        self.assertEqual((await self.http.post('/api/oauth/consent', json=body)).status_code, 403)
        self.assertEqual((await self.http.post('/api/oauth/consent', headers={**self.headers, 'Origin': 'https://evil.test'}, json=body)).status_code, 403)
        await self.http.post('/api/oauth/consent', headers=self.headers, json={'request': pending})
        r = await self.http.post('/api/oauth/consent', headers=self.headers, json={'request': pending, 'decision': 'deny'})
        self.assertEqual(r.status_code, 200)
        query = parse_qs(urlsplit(r.json()['redirect']).query)
        self.assertEqual(query['error'], ['access_denied'])
        self.assertEqual(query['iss'], ['https://app.test'])
        self.assertNotIn('code', query)
        self.assertEqual((await self.http.post('/api/oauth/consent', headers=self.headers, json=body)).status_code, 400)
        self.assertEqual(self.store.apps(self.uid), [])

    async def test_cross_account_and_session_binding(self):
        pending = await self.pending()
        await self.http.post('/api/oauth/consent', headers=self.headers, json={'request': pending})
        other, _ = self.vault.register('other@example.test', 'another synthetic password')
        self.vault.verify_email(self.vault.verification_token(other))
        other_session = self.vault.login('other@example.test', 'another synthetic password')
        self.http.cookies.set('__Host-mcp_session', other_session)
        r = await self.http.post('/api/oauth/consent', headers={**self.headers, 'X-CSRF-Token': self.vault.csrf(other_session)}, json={'request': pending, 'decision': 'approve'})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(self.store.apps(other), [])

    async def test_expiry_password_recovery_and_app_revocation(self):
        tokens = (await self.exchange(await self.code())).json()
        app = self.store.apps(self.uid)[0]
        self.store.revoke_app('someone-else', app['id'])
        self.assertIsNotNone(self.store.identity(tokens['access_token'], self.resource))
        r = await self.http.post('/api/account/apps', headers=self.headers, json={'revoke': app['id']})
        self.assertEqual(r.status_code, 200)
        self.assertIsNone(self.store.identity(tokens['access_token'], self.resource))
        tokens = (await self.exchange(await self.code())).json()
        self.vault.change_password(self.uid, 'synthetic password for OAuth', 'changed synthetic password')
        self.assertIsNone(self.store.identity(tokens['access_token'], self.resource))
        self.assertEqual((await self.refresh(tokens['refresh_token'])).status_code, 400)

    async def test_invalid_registration_and_authorization_no_unsafe_redirect(self):
        for uri in ['javascript:alert(1)', 'http://public.test/cb', 'https://client.test/cb#fragment', 'https://user:pass@client.test/cb']:
            r = await self.http.post('/register', json={'redirect_uris': [uri], 'token_endpoint_auth_method': 'none'})
            self.assertEqual(r.status_code, 400, r.text)
        for changes in [{'redirect_uri': 'https://evil.test/callback'}, {'resource': 'https://evil.test/mcp'}, {'code_challenge_method': 'plain'}]:
            r = await self.http.get('/authorize', params=self.authorization(**changes))
            self.assertEqual(r.status_code, 400, r.text)
            self.assertNotIn('location', r.headers)
        r = await self.http.get('/authorize', params=self.authorization(scope='admin'))
        self.assertEqual(r.status_code, 302)
        self.assertIn('iss=https%3A%2F%2Fapp.test', r.headers['location'])
        self.assertIn('error=invalid_scope', r.headers['location'])

    async def test_confidential_client_secret_encrypted_and_required(self):
        self.client = await self.register(token_endpoint_auth_method='client_secret_post')
        secret = self.client['client_secret']
        self.assertNotIn(secret.encode(), Path(self.vault.path).read_bytes())
        code = await self.code()
        self.assertEqual((await self.exchange(code)).status_code, 401)
        self.assertEqual((await self.exchange(code, client_secret=secret)).status_code, 200)

    async def test_basic_client_auth_without_redundant_form_identifier(self):
        self.client = await self.register(token_endpoint_auth_method='client_secret_basic')
        code = await self.code()
        auth = httpx.BasicAuth(self.client['client_id'], self.client['client_secret'])
        r = await self.http.post('/token', auth=auth, data={'grant_type': 'authorization_code', 'redirect_uri': 'https://client.test/callback', 'code': code, 'code_verifier': self.verifier, 'resource': self.resource})
        self.assertEqual(r.status_code, 200, r.text)
        r = await self.http.post('/revoke', auth=auth, data={'token': r.json()['access_token']})
        self.assertEqual(r.status_code, 200, r.text)

    async def test_cimd_allowlist_matching_identity_and_no_redirect_fetch(self):
        from src.oauth_http import AccountOAuthProvider
        provider = AccountOAuthProvider()
        with patch('src.oauth_http.httpx.AsyncClient') as network:
            self.assertIsNone(await provider.get_client('https://127.0.0.1/private'))
            self.assertIsNone(await provider.get_client('https://evil.test/client.json'))
            network.assert_not_called()
        real_client = httpx.AsyncClient
        def metadata(request):
            return httpx.Response(200, json={'client_id': str(request.url), 'client_name': 'CIMD synthetic', 'redirect_uris': ['https://chatgpt.com/test/callback'], 'token_endpoint_auth_methods_supported': ['none', 'private_key_jwt']})
        with patch('src.oauth_http.httpx.AsyncClient', side_effect=lambda **kwargs: real_client(transport=httpx.MockTransport(metadata), **kwargs)):
            client = await provider.get_client('https://chatgpt.com/oauth/test-client.json')
            self.assertEqual(client.client_id, 'https://chatgpt.com/oauth/test-client.json')
            self.assertEqual(client.token_endpoint_auth_method, 'none')
            self.assertIsNone(client.client_secret)

    async def test_expired_codes_tokens_pending_and_recovery(self):
        code = await self.code()
        with self.vault.db() as db: db.execute('UPDATE oauth_codes SET expires=0')
        self.assertEqual((await self.exchange(code)).status_code, 400)
        pending = await self.pending()
        with self.vault.db() as db: db.execute('UPDATE oauth_pending SET expires=0')
        self.assertEqual((await self.http.post('/api/oauth/consent', headers=self.headers, json={'request': pending})).status_code, 400)
        tokens = (await self.exchange(await self.code())).json()
        with self.vault.db() as db: db.execute('UPDATE oauth_access SET expires=0')
        self.assertIsNone(self.store.identity(tokens['access_token'], self.resource))
        self.vault.recover('oauth@example.test', self.recovery, 'recovered synthetic password')
        self.assertEqual((await self.refresh(tokens['refresh_token'])).status_code, 400)

    async def test_real_mcp_transport_uses_oauth_subject_and_redacts_bps_key(self):
        from src import server
        from mcp.server.transport_security import TransportSecuritySettings
        tokens = (await self.exchange(await self.code())).json()
        self.vault.save_key(self.uid, 'bps', 'synthetic-oauth-bps-key')
        app = install(server.mcp.streamable_http_app(stateless_http=True, json_response=True, host='app.test', transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=True, allowed_hosts=['app.test'], allowed_origins=['https://app.test'])))
        upstream = AsyncMock(return_value={'status': 'OK', 'data': [{'domain_id': '1100'}]})
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='https://app.test') as client:
                with patch.object(server, '_read_bps_payload', upstream):
                    r = await client.post('/mcp', headers={'Authorization': 'Bearer ' + tokens['access_token'], 'Accept': 'application/json, text/event-stream'}, json={'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call', 'params': {'name': 'bps_request', 'arguments': {'operation': 'listDomains', 'parameters': {'type': 'all'}}}})
                self.assertEqual(r.status_code, 200, r.text)
                self.assertTrue(upstream.called, r.text)
                self.assertIn('synthetic-oauth-bps-key', upstream.call_args.args[0])
                self.assertNotIn('synthetic-oauth-bps-key', r.text)
                self.assertIn('1100', r.text)

    async def test_rotation_preserves_encrypted_clients_and_oauth_grants(self):
        from scripts.rotate_account_key import main
        self.client = await self.register(token_endpoint_auth_method='client_secret_post')
        code = await self.code()
        tokens = (await self.exchange(code, client_secret=self.client['client_secret'])).json()
        new = base64.b64encode(secrets.token_bytes(32)).decode()
        with patch.dict('os.environ', {'ACCOUNTS_DB_PATH': self.vault.path, 'ACCOUNTS_ENCRYPTION_KEY': self.key, 'ACCOUNTS_NEW_ENCRYPTION_KEY': new}):
            main()
        store = OAuthStore(Vault(self.vault.path, new))
        self.assertEqual(store.client(self.client['client_id'])[0]['client_secret'], self.client['client_secret'])
        self.assertIsNotNone(store.identity(tokens['access_token'], self.resource))

    async def test_concurrent_code_exchange_only_one_succeeds(self):
        code = await self.code()
        results = await asyncio.gather(self.exchange(code), self.exchange(code))
        self.assertEqual(sorted(r.status_code for r in results), [200, 400])
