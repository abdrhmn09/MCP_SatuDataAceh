"""Interactive OAuth/MCP smoke client. Tokens stay in memory; its grant is revoked.

Run: python3 scripts/smoke_oauth.py --base-url https://www.mcpsatudataaceh.web.id
Open the printed authorize URL, sign in, inspect the local callback, then consent.
This registers a public DCR test client, reads BPS via your account, and revokes it.
No passwords, API keys, authorization codes, or tokens are printed or written.
"""
import argparse
import base64
import hashlib
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import secrets
from urllib.parse import parse_qs, urlencode, urlsplit

import httpx


def rpc(client, url, token, method, params=None, identifier=1):
    body = {'jsonrpc': '2.0', 'method': method}
    if params is not None: body['params'] = params
    if identifier is not None: body['id'] = identifier
    response = client.post(url, headers={'Authorization': 'Bearer ' + token, 'Accept': 'application/json, text/event-stream'}, json=body)
    response.raise_for_status()
    if identifier is None: return None
    if 'text/event-stream' in response.headers.get('content-type', ''):
        lines = [line[5:].strip() for line in response.text.splitlines() if line.startswith('data:')]
        payload = json.loads(lines[-1])
    else:
        payload = response.json()
    if payload.get('error'): raise ValueError('Permintaan MCP gagal.')
    return payload['result']


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url', default='https://www.mcpsatudataaceh.web.id')
    parser.add_argument('--port', type=int, default=8766)
    args = parser.parse_args()
    root = args.base_url.rstrip('/')
    parsed = urlsplit(root)
    if (parsed.scheme != 'https' and not (parsed.scheme == 'http' and parsed.hostname in {'localhost', '127.0.0.1'})) or parsed.path or parsed.query or parsed.fragment or parsed.username:
        raise ValueError('Gunakan origin HTTPS, atau loopback untuk tes lokal.')
    verifier, state = secrets.token_urlsafe(48), secrets.token_urlsafe(32)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('=')
    callback = 'http://127.0.0.1:' + str(args.port) + '/callback'
    outcome = {'ok': False, 'message': 'Menunggu persetujuan.'}

    class Callback(BaseHTTPRequestHandler):
        def log_message(self, *args): pass

        def do_GET(self):
            path = urlsplit(self.path)
            if path.path != '/callback':
                self.send_error(404); return
            query = parse_qs(path.query)
            tokens = None
            try:
                if query.get('state') != [state] or query.get('iss') != [root]:
                    raise ValueError('State atau issuer tidak sesuai.')
                if query.get('error'):
                    raise ValueError('Persetujuan ditolak; tidak ada akses diberikan.')
                code = query.get('code', [''])[0]
                if not code: raise ValueError('Kode tidak tersedia.')
                exchanged = client.post(root + '/token', data={'grant_type': 'authorization_code', 'client_id': registration['client_id'], 'redirect_uri': callback, 'resource': root + '/mcp', 'code': code, 'code_verifier': verifier})
                exchanged.raise_for_status()
                tokens = exchanged.json()
                token = tokens['access_token']
                init = rpc(client, root + '/mcp', token, 'initialize', {'protocolVersion': '2025-11-25', 'capabilities': {}, 'clientInfo': {'name': 'oauth-smoke-test', 'version': '1.0'}})
                client.headers['MCP-Protocol-Version'] = init['protocolVersion']
                rpc(client, root + '/mcp', token, 'notifications/initialized', identifier=None)
                tools = rpc(client, root + '/mcp', token, 'tools/list', identifier=2)
                result = rpc(client, root + '/mcp', token, 'tools/call', {'name': 'bps_request', 'arguments': {'operation': 'listVariables', 'parameters': {'domain': '1100', 'lang': 'ind', 'page': 1}}}, 3)
                content = result.get('structuredContent')
                if content is None:
                    content = json.loads(next(item['text'] for item in result['content'] if item['type'] == 'text'))
                if result.get('isError') or not content.get('ok'):
                    raise ValueError('OAuth berhasil, tetapi permintaan BPS belum berhasil. Periksa key akun dan koneksi BPS.')
                rotated = client.post(root + '/token', data={'grant_type': 'refresh_token', 'client_id': registration['client_id'], 'refresh_token': tokens['refresh_token'], 'resource': root + '/mcp'})
                rotated.raise_for_status(); tokens = rotated.json()
                rpc(client, root + '/mcp', tokens['access_token'], 'tools/list', identifier=4)
                outcome.update(ok=True, message='Login dan persetujuan OAuth berhasil. MCP initialize, tools/list (' + str(len(tools['tools'])) + ' tools), pengambilan variabel BPS Aceh, dan refresh token berhasil.')
            except Exception:
                # No request/response objects: they could contain credentials.
                outcome.update(ok=False, message='Pengujian belum berhasil atau persetujuan ditolak. Periksa konfigurasi OAuth, key akun, dan ketersediaan BPS.')
            finally:
                if tokens:
                    try:
                        revoked = client.post(root + '/revoke', data={'client_id': registration['client_id'], 'token': tokens['refresh_token']})
                        check = client.post(root + '/mcp', headers={'Authorization': 'Bearer ' + tokens['access_token']}, json={})
                        revoked_ok = revoked.status_code == 200 and check.status_code == 401
                    except httpx.HTTPError:
                        revoked_ok = False
                    outcome['revoked'] = revoked_ok
                    outcome['ok'] = outcome['ok'] and revoked_ok
            text = outcome['message'] + (' Akses aplikasi pengujian telah dicabut.' if outcome.get('revoked') else '')
            html = ('<!doctype html><html lang="id"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>Hasil pengujian OAuth</title><script>history.replaceState(null,"","/callback")</script><body style="font:16px/1.7 system-ui;background:#f5f7f2;color:#19392e;max-width:650px;margin:80px auto;padding:24px"><h1>' + ('Pengujian berhasil' if outcome['ok'] else 'Periksa hasil pengujian') + '</h1><p>' + text + '</p><p>Credential tidak ditampilkan atau disimpan oleh aplikasi pengujian.</p><a href="' + root + '/#apps">Kembali ke aplikasi terhubung</a></body></html>').encode()
            self.send_response(200); self.send_header('Content-Type', 'text/html; charset=utf-8'); self.send_header('Cache-Control', 'no-store'); self.send_header('Referrer-Policy', 'no-referrer'); self.end_headers(); self.wfile.write(html)

    with HTTPServer(('127.0.0.1', args.port), Callback) as server, httpx.Client(timeout=40, follow_redirects=False) as client:
        registration_response = client.post(root + '/register', json={'client_name': 'Pengujian OAuth MCP (sementara)', 'redirect_uris': [callback], 'token_endpoint_auth_method': 'none', 'application_type': 'native', 'grant_types': ['authorization_code', 'refresh_token'], 'scope': 'data:read'})
        registration_response.raise_for_status(); registration = registration_response.json()
        url = root + '/authorize?' + urlencode({'response_type': 'code', 'client_id': registration['client_id'], 'redirect_uri': callback, 'scope': 'data:read', 'state': state, 'resource': root + '/mcp', 'code_challenge': challenge, 'code_challenge_method': 'S256'})
        print('AUTHORIZE_URL', url, flush=True)
        server.timeout = 900
        server.handle_request()
        print('RESULT', json.dumps(outcome, ensure_ascii=False), flush=True)
        if not outcome['ok']: raise SystemExit(1)


if __name__ == '__main__':
    main()
