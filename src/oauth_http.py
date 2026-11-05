"""MCP SDK OAuth handlers with account consent and resource-bound persistent tokens."""
from contextvars import ContextVar
import asyncio
import base64
import hmac
import json
import os
import time
from urllib.parse import parse_qs, urlsplit, urlencode, unquote

import httpx
from mcp.server.auth.handlers.authorize import AuthorizationHandler
from mcp.server.auth.handlers.register import RegistrationHandler
from mcp.server.auth.handlers.revoke import RevocationHandler
from mcp.server.auth.handlers.token import TokenHandler
from mcp.server.auth.middleware.client_auth import ClientAuthenticator
from mcp.server.auth.provider import construct_redirect_uri, RegistrationError
from mcp.server.auth.settings import ClientRegistrationOptions
from mcp.shared.auth import OAuthClientInformationFull
from pydantic import AnyUrl
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route, request_response

from .accounts import get_vault
from .oauth import OAuthStore, SCOPE, origin, resources, valid_redirect

_resource = ContextVar('oauth_token_resource', default=None)


class MetadataOAuthClient(OAuthClientInformationFull):
    native_loopback: bool = False

    def validate_redirect_uri(self, redirect_uri: AnyUrl | None) -> AnyUrl:
        if self.native_loopback and redirect_uri and valid_redirect(str(redirect_uri)):
            requested = urlsplit(str(redirect_uri))
            if requested.scheme == 'http' and requested.hostname in {'127.0.0.1', '::1'}:
                for registered_uri in self.redirect_uris or []:
                    registered = urlsplit(str(registered_uri))
                    # RFC 8252: only the port may differ for native loopback redirects.
                    if (registered.scheme, registered.hostname, registered.path, registered.query) == (
                        requested.scheme, requested.hostname, requested.path, requested.query
                    ):
                        return redirect_uri
        return super().validate_redirect_uri(redirect_uri)


class AccountOAuthProvider:
    @property
    def store(self):
        return OAuthStore(get_vault())

    async def get_client(self, client_id):
        if not isinstance(client_id, str) or len(client_id) > 2048:
            return None
        existing = self.store.client(client_id)
        is_url = client_id.startswith('https://')
        if existing and not is_url:
            return OAuthClientInformationFull.model_validate(existing[0])
        # CIMD fetching is restricted to administrator-approved origins, with no redirects.
        # Other clients can use DCR without any server-side URL fetching.
        hosts = {host.strip().lower() for host in os.getenv('OAUTH_CIMD_HOSTS', 'chatgpt.com,claude.ai,opencode.ai').split(',')}
        try:
            parsed = urlsplit(client_id)
            if not is_url or parsed.hostname not in hosts or parsed.port not in {None, 443} or parsed.username or parsed.password or parsed.query or parsed.fragment or not parsed.path.strip('/'):
                return None
        except ValueError:
            return None
        if existing and existing[1] > time.time() - 3600:
            return MetadataOAuthClient.model_validate(existing[0])
        if not get_vault().throttle('oauth-cimd-global', 100, 60):
            return None
        try:
            async with httpx.AsyncClient(timeout=8, follow_redirects=False, trust_env=False) as client:
                async with client.stream('GET', client_id, headers={'Accept': 'application/json'}) as response:
                    if response.status_code != 200:
                        return None
                    raw = bytearray()
                    async for chunk in response.aiter_bytes():
                        raw.extend(chunk)
                        if len(raw) > 16384:
                            return None
            data = json.loads(raw)
            if not isinstance(data, dict) or data.get('client_id') != client_id:
                return None
            methods = data.get('token_endpoint_auth_methods_supported', [data.get('token_endpoint_auth_method', 'none')])
            if not isinstance(methods, list) or 'none' not in methods:
                return None
            info = MetadataOAuthClient.model_validate({
                **data,
                'client_id': client_id,
                'client_secret': None,
                'client_secret_expires_at': None,
                'token_endpoint_auth_method': 'none',
                'scope': SCOPE,
                'native_loopback': data.get('application_type') == 'native',
            })
            self.validate_client(info)
            self.store.put_client(info)
            return info
        except (httpx.HTTPError, ValueError, TypeError, RegistrationError):
            return None

    def validate_client(self, client):
        if not client.redirect_uris or len(client.redirect_uris) > 10 or any(not valid_redirect(str(uri)) for uri in client.redirect_uris):
            raise RegistrationError('invalid_redirect_uri', 'Callback harus HTTPS atau HTTP loopback, tanpa fragment atau userinfo.')
        if client.response_types != ['code'] or not set(client.grant_types) <= {'authorization_code', 'refresh_token'} or 'authorization_code' not in client.grant_types:
            raise RegistrationError('invalid_client_metadata', 'Hanya authorization_code dan refresh_token didukung.')
        if client.scope != SCOPE or len(client.client_name or '') > 100:
            raise RegistrationError('invalid_client_metadata', 'Scope yang didukung adalah data:read; nama maksimal 100 karakter.')

    async def register_client(self, client_info):
        self.validate_client(client_info)
        with get_vault().db() as db:
            if db.execute('SELECT count(*) FROM oauth_clients').fetchone()[0] >= 5000:
                raise RegistrationError('invalid_client_metadata', 'Batas registrasi klien tercapai. Hubungi pengelola.')
        self.store.put_client(client_info)

    async def authorize(self, client, params):
        nonce = self.store.pending(client, params)
        return origin() + '/#oauth=' + nonce

    async def load_authorization_code(self, client, authorization_code):
        return self.store.load_code(client, authorization_code)

    async def exchange_authorization_code(self, client, authorization_code):
        return self.store.exchange_code(client, authorization_code, _resource.get())

    async def load_refresh_token(self, client, refresh_token):
        return self.store.load_refresh(client, refresh_token)

    async def exchange_refresh_token(self, client, refresh_token, scopes):
        return self.store.refresh(client, refresh_token, scopes, _resource.get())

    async def load_access_token(self, token):
        return self.store.load_access(token)

    async def revoke_token(self, token):
        self.store.revoke(token)


def response(data, status=200):
    return JSONResponse(data, status_code=status, headers={'Cache-Control': 'no-store', 'Pragma': 'no-cache', 'Referrer-Policy': 'no-referrer', 'X-Content-Type-Options': 'nosniff'})


async def metadata(request):
    root = origin()
    if 'oauth-protected-resource' in request.url.path:
        suffix = request.path_params.get('endpoint', 'mcp')
        if suffix not in {'mcp', 'sse'}:
            return response({'error': 'not_found'}, 404)
        return response({'resource': root + '/' + suffix, 'authorization_servers': [root], 'scopes_supported': [SCOPE], 'bearer_methods_supported': ['header'], 'resource_name': 'MCP Satu Data Aceh'})
    return response({'issuer': root, 'authorization_endpoint': root + '/authorize', 'token_endpoint': root + '/token', 'registration_endpoint': root + '/register', 'revocation_endpoint': root + '/revoke', 'response_types_supported': ['code'], 'grant_types_supported': ['authorization_code', 'refresh_token'], 'scopes_supported': [SCOPE], 'code_challenge_methods_supported': ['S256'], 'token_endpoint_auth_methods_supported': ['none', 'client_secret_post', 'client_secret_basic'], 'revocation_endpoint_auth_methods_supported': ['none', 'client_secret_post', 'client_secret_basic'], 'client_id_metadata_document_supported': True, 'authorization_response_iss_parameter_supported': True})


async def oauth_consent(request):
    from .accounts_http import cookie_name, origin_allowed, read_body
    if not origin_allowed(request):
        return response({'error': 'origin_rejected'}, 403)
    vault = get_vault()
    raw = request.cookies.get(cookie_name(), '')
    user = vault.identity(raw)
    if not user:
        return response({'error': 'login_required'}, 401)
    if not hmac.compare_digest(request.headers.get('x-csrf-token', ''), vault.csrf(raw)):
        return response({'error': 'csrf_rejected'}, 403)
    try:
        body = await read_body(request)
        decision = body.get('decision', 'inspect')
        value, code = OAuthStore(vault).consent(body.get('request'), user['id'], raw, decision)
        if decision == 'inspect':
            return response({'name': value['name'], 'client_id': value['client_id'], 'redirect_uri': value['redirect_uri'], 'resource': value['resource'], 'scope': SCOPE})
        return response({'redirect': construct_redirect_uri(value['redirect_uri'], state=value['state'], iss=origin(), **({'code': code} if code else {'error': 'access_denied'}))})
    except (ValueError, TypeError, TimeoutError):
        return response({'error': 'invalid_oauth_request', 'message': 'Permintaan kedaluwarsa, sudah digunakan, atau berasal dari sesi lain. Mulai kembali koneksi dari aplikasi AI.'}, 400)


def oauth_routes():
    provider = AccountOAuthProvider()
    authenticator = ClientAuthenticator(provider)
    handlers = {'authorize': AuthorizationHandler(provider), 'token': TokenHandler(provider, authenticator), 'register': RegistrationHandler(provider, ClientRegistrationOptions(enabled=True, valid_scopes=[SCOPE], default_scopes=[SCOPE])), 'revoke': RevocationHandler(provider, authenticator)}

    async def endpoint(request: Request):
        name = request.url.path.lstrip('/')
        if name not in handlers:
            return response({'error': 'not_found'}, 404)
        if request.method != ('GET' if name == 'authorize' else 'POST'):
            return response({'error': 'invalid_request'}, 405)
        vault = get_vault()
        peer = request.client.host if request.client else 'local'
        # Read the forwarding address only behind the loopback reverse proxy.
        if peer in {'127.0.0.1', '::1'}:
            peer = request.headers.get('x-real-ip', peer)
        if not vault.throttle('oauth-' + name + ':' + peer, 100 if name == 'token' else 30, 60):
            return response({'error': 'temporarily_unavailable'}, 429)
        try:
            if len(request.scope.get('query_string', b'')) > 8192:
                return response({'error': 'invalid_request'}, 400)
            if request.method == 'POST':
                raw = bytearray()
                async with asyncio.timeout(10):
                    async for chunk in request.stream():
                        raw.extend(chunk)
                        if len(raw) > 16384:
                            return response({'error': 'invalid_request'}, 413)
                # SDK handlers reuse the validated, bounded body.
                request = Request(request.scope, receive=_receive(bytes(raw)))
                if name == 'register':
                    if request.headers.get('content-type', '').split(';')[0] != 'application/json':
                        return response({'error': 'invalid_client_metadata'}, 400)
                    params = {}
                else:
                    if request.headers.get('content-type', '').split(';')[0] != 'application/x-www-form-urlencoded':
                        return response({'error': 'invalid_request'}, 400)
                    params = parse_qs(raw.decode(), keep_blank_values=True)
                    auth = request.headers.get('authorization', '')
                    if auth.startswith('Basic ') and 'client_id' not in params:
                        # RFC 6749 permits client_id solely in HTTP Basic; the SDK expects
                        # it in the form too. Normalize before delegating authentication.
                        identifier = base64.b64decode(auth[6:], validate=True).decode().split(':', 1)[0]
                        params['client_id'] = [unquote(identifier)]
                        request = Request(request.scope, receive=_receive(urlencode(params, doseq=True).encode()))
                    if name == 'revoke' and 'client_secret' not in params:
                        # SDK RevocationRequest currently requires this form field even
                        # for public / Basic clients. Authentication still runs normally.
                        params['client_secret'] = ['']
                        request = Request(request.scope, receive=_receive(urlencode(params, doseq=True).encode()))
            else:
                params = parse_qs(request.scope.get('query_string', b'').decode(), keep_blank_values=True)
            if any(len(values) != 1 for values in params.values()):
                return response({'error': 'invalid_request'}, 400)
            if name in {'authorize', 'token'} and params.get('resource', [''])[0] not in resources():
                return response({'error': 'invalid_target', 'error_description': 'resource wajib berupa URL endpoint MCP yang dipublikasikan.'}, 400)
            if name == 'authorize' and (params.get('code_challenge_method') != ['S256'] or not params.get('redirect_uri')):
                return response({'error': 'invalid_request', 'error_description': 'PKCE S256 dan redirect_uri wajib disertakan.'}, 400)
            marker = _resource.set(params.get('resource', [None])[0])
            try:
                result = await handlers[name].handle(request)
            finally:
                _resource.reset(marker)
            # Issuer identification is required on successful AND error callbacks.
            target = result.headers.get('location', '')
            if name == 'authorize' and target and not target.startswith(origin() + '/#oauth='):
                result.headers['location'] = construct_redirect_uri(target, iss=origin())
            result.headers.update({'Cache-Control': 'no-store', 'Referrer-Policy': 'no-referrer'})
            return result
        except (ValueError, TypeError, TimeoutError):
            return response({'error': 'invalid_request'}, 400)

    def cors(handler, methods):
        return CORSMiddleware(request_response(handler), allow_origins=['*'], allow_methods=methods, allow_headers=['Content-Type', 'Authorization', 'MCP-Protocol-Version'])

    return [
        Route('/.well-known/oauth-protected-resource', cors(metadata, ['GET', 'OPTIONS']), methods=['GET', 'OPTIONS']),
        Route('/.well-known/oauth-protected-resource/{endpoint}', cors(metadata, ['GET', 'OPTIONS']), methods=['GET', 'OPTIONS']),
        Route('/.well-known/oauth-authorization-server', cors(metadata, ['GET', 'OPTIONS']), methods=['GET', 'OPTIONS']),
        Route('/api/oauth/consent', oauth_consent, methods=['POST']),
    ] + [Route('/' + name, cors(endpoint, ['GET', 'POST', 'OPTIONS']), methods=['GET', 'POST', 'OPTIONS']) for name in handlers]


def _receive(body):
    async def receive():
        return {'type': 'http.request', 'body': body, 'more_body': False}
    return receive
