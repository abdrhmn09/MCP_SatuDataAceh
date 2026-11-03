"""Persistent OAuth grants. Secrets are hashed; registered client secrets are encrypted."""
import json
import os
import re
import secrets
import time
from urllib.parse import urlsplit, parse_qs

from mcp.server.auth.provider import AuthorizationCode, RefreshToken, AccessToken, TokenError
from mcp.shared.auth import OAuthToken

from .accounts import digest

SCOPE = 'data:read'
ACCESS_TTL = 900
GRANT_TTL = 30 * 86400


def origin():
    value = os.getenv('ACCOUNTS_PUBLIC_ORIGIN', 'https://www.mcpsatudataaceh.web.id').rstrip('/')
    parsed = urlsplit(value)
    dev = os.getenv('ACCOUNTS_DEV_HTTP') == '1' and parsed.hostname in {'localhost', '127.0.0.1', '::1'}
    if (parsed.scheme != 'https' and not (dev and parsed.scheme == 'http')) or not parsed.hostname or parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment:
        raise ValueError('ACCOUNTS_PUBLIC_ORIGIN harus origin HTTPS tanpa path.')
    return value


def resources():
    return {origin() + '/mcp', origin() + '/sse'}


def init_schema(vault):
    with vault.db() as db:
        db.executescript('''
        CREATE TABLE IF NOT EXISTS oauth_clients(id TEXT PRIMARY KEY, value BLOB NOT NULL, updated INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS oauth_pending(hash TEXT PRIMARY KEY, value TEXT NOT NULL, user_id TEXT, session_hash TEXT, expires INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS oauth_grants(id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE, client_id TEXT NOT NULL, name TEXT NOT NULL, redirect_uri TEXT NOT NULL, resource TEXT NOT NULL, created INTEGER NOT NULL, expires INTEGER NOT NULL, revoked INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS oauth_codes(hash TEXT PRIMARY KEY, grant_id TEXT NOT NULL REFERENCES oauth_grants(id) ON DELETE CASCADE, value TEXT NOT NULL, expires INTEGER NOT NULL, used INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS oauth_access(hash TEXT PRIMARY KEY, grant_id TEXT NOT NULL REFERENCES oauth_grants(id) ON DELETE CASCADE, expires INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS oauth_refresh(hash TEXT PRIMARY KEY, grant_id TEXT NOT NULL REFERENCES oauth_grants(id) ON DELETE CASCADE, expires INTEGER NOT NULL, used INTEGER NOT NULL DEFAULT 0);
        CREATE INDEX IF NOT EXISTS oauth_grants_user ON oauth_grants(user_id);
        ''')


def revoke_user(db, uid):
    db.execute('UPDATE oauth_grants SET revoked=1 WHERE user_id=?', (uid,))
    db.execute('DELETE FROM oauth_pending WHERE user_id=?', (uid,))


def valid_redirect(value):
    parsed = urlsplit(value)
    if len(value) > 2048 or parsed.fragment or parsed.username or parsed.password or not parsed.hostname or re.search(r'[\x00-\x20\\]', value) or set(parse_qs(parsed.query)) & {'code', 'state', 'iss', 'error', 'error_description'}:
        return False
    return parsed.scheme == 'https' or (parsed.scheme == 'http' and parsed.hostname in {'127.0.0.1', 'localhost', '::1'})


class OAuthStore:
    def __init__(self, vault):
        self.vault = vault

    def put_client(self, client):
        nonce = secrets.token_bytes(12)
        blob = nonce + self.vault.cipher.encrypt(nonce, client.model_dump_json().encode(), ('oauth-client:' + client.client_id).encode())
        with self.vault.db() as db:
            db.execute('INSERT OR REPLACE INTO oauth_clients VALUES(?,?,?)', (client.client_id, blob, int(time.time())))

    def client(self, client_id):
        with self.vault.db() as db:
            row = db.execute('SELECT value,updated FROM oauth_clients WHERE id=?', (client_id,)).fetchone()
        if not row:
            return None
        blob = row['value']
        return json.loads(self.vault.cipher.decrypt(blob[:12], blob[12:], ('oauth-client:' + client_id).encode())), row['updated']

    def pending(self, client, params):
        if params.resource not in resources():
            from mcp.server.auth.provider import AuthorizeError
            raise AuthorizeError('invalid_target', 'Gunakan resource URL endpoint MCP yang dipublikasikan.')
        if params.scopes != [SCOPE] or not re.fullmatch(r'[A-Za-z0-9_-]{43}', params.code_challenge):
            from mcp.server.auth.provider import AuthorizeError
            raise AuthorizeError('invalid_request', 'Scope data:read dan PKCE S256 wajib digunakan.')
        value = {'client_id': client.client_id, 'name': (client.client_name or 'Aplikasi MCP')[:100], **params.model_dump(mode='json')}
        raw, now = secrets.token_urlsafe(32), int(time.time())
        with self.vault.db() as db:
            db.execute('DELETE FROM oauth_pending WHERE expires<=?', (now,))
            db.execute('DELETE FROM oauth_codes WHERE expires<?', (now - 86400,))
            db.execute('DELETE FROM oauth_access WHERE expires<=?', (now,))
            db.execute('DELETE FROM oauth_refresh WHERE expires<=?', (now,))
            db.execute('DELETE FROM oauth_grants WHERE expires<?', (now - 86400,))
            if db.execute('SELECT count(*) FROM oauth_pending').fetchone()[0] >= 2000:
                raise ValueError('Terlalu banyak permintaan OAuth. Coba lagi nanti.')
            db.execute('INSERT INTO oauth_pending VALUES(?,?,NULL,NULL,?)', (digest(raw), json.dumps(value), now + 900))
        return raw

    def consent(self, raw, uid, session, decision='inspect'):
        if not isinstance(raw, str) or len(raw) > 128 or decision not in {'inspect', 'approve', 'deny'}:
            raise ValueError('Permintaan OAuth tidak valid.')
        now, code = int(time.time()), None
        with self.vault.db() as db:
            db.execute('BEGIN IMMEDIATE')
            active = db.execute('SELECT 1 FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.hash=? AND s.user_id=? AND s.expires>? AND u.email_verified=1', (digest(session), uid, now)).fetchone()
            if not active:
                raise ValueError('Sesi akun berakhir. Masuk kembali sebelum memberi persetujuan.')
            row = db.execute('SELECT * FROM oauth_pending WHERE hash=? AND expires>?', (digest(raw), now)).fetchone()
            if not row or (row['user_id'] and (row['user_id'] != uid or row['session_hash'] != digest(session))):
                raise ValueError('Permintaan kedaluwarsa atau terikat pada sesi lain. Mulai koneksi kembali dari aplikasi AI.')
            value = json.loads(row['value'])
            if decision == 'inspect':
                db.execute('UPDATE oauth_pending SET user_id=?,session_hash=? WHERE hash=?', (uid, digest(session), digest(raw)))
            else:
                if row['user_id'] != uid or row['session_hash'] != digest(session):
                    raise ValueError('Tinjau halaman persetujuan terlebih dahulu.')
                if decision == 'approve':
                    if db.execute('SELECT count(*) FROM oauth_grants WHERE user_id=? AND revoked=0 AND expires>?', (uid, now)).fetchone()[0] >= 20:
                        raise ValueError('Maksimal 20 aplikasi terhubung. Cabut akses aplikasi lama.')
                    grant, code = secrets.token_hex(16), secrets.token_urlsafe(32)
                    db.execute('INSERT INTO oauth_grants VALUES(?,?,?,?,?,?,?,?,0)', (grant, uid, value['client_id'], value['name'], value['redirect_uri'], value['resource'], now, now + GRANT_TTL))
                    db.execute('INSERT INTO oauth_codes VALUES(?,?,?,?,0)', (digest(code), grant, json.dumps(value), now + 120))
                db.execute('DELETE FROM oauth_pending WHERE hash=?', (digest(raw),))
        return value, code

    def apps(self, uid):
        with self.vault.db() as db:
            return [dict(row) for row in db.execute('SELECT id,name,client_id,redirect_uri,resource,created,expires FROM oauth_grants WHERE user_id=? AND revoked=0 AND expires>? ORDER BY created DESC', (uid, int(time.time())))]

    def revoke_app(self, uid, grant):
        with self.vault.db() as db:
            db.execute('UPDATE oauth_grants SET revoked=1 WHERE id=? AND user_id=?', (grant, uid))

    def load_code(self, client, raw):
        with self.vault.db() as db:
            row = db.execute('SELECT c.*,g.client_id,g.user_id FROM oauth_codes c JOIN oauth_grants g ON g.id=c.grant_id JOIN users u ON u.id=g.user_id WHERE c.hash=? AND c.used=0 AND c.expires>? AND g.revoked=0 AND g.expires>? AND u.email_verified=1', (digest(raw), int(time.time()), int(time.time()))).fetchone()
        if not row or row['client_id'] != client.client_id:
            return None
        value = json.loads(row['value'])
        return AuthorizationCode(code=raw, client_id=client.client_id, scopes=[SCOPE], expires_at=row['expires'], subject=row['user_id'], **{k: value[k] for k in ['code_challenge', 'redirect_uri', 'redirect_uri_provided_explicitly', 'resource']})

    def _issue(self, db, grant):
        now = int(time.time())
        access, refresh = 'oat_' + secrets.token_urlsafe(32), 'ort_' + secrets.token_urlsafe(32)
        db.execute('DELETE FROM oauth_access WHERE grant_id=?', (grant['id'],))
        db.execute('INSERT INTO oauth_access VALUES(?,?,?)', (digest(access), grant['id'], min(now + ACCESS_TTL, grant['expires'])))
        db.execute('INSERT INTO oauth_refresh VALUES(?,?,?,0)', (digest(refresh), grant['id'], grant['expires']))
        return OAuthToken(access_token=access, token_type='Bearer', expires_in=min(ACCESS_TTL, grant['expires'] - now), refresh_token=refresh, scope=SCOPE)

    def exchange_code(self, client, code, resource):
        if resource != code.resource:
            raise TokenError('invalid_target', 'Resource berbeda dari permintaan otorisasi.')
        issued = None
        with self.vault.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT g.* FROM oauth_codes c JOIN oauth_grants g ON g.id=c.grant_id JOIN users u ON u.id=g.user_id WHERE c.hash=? AND c.used=0 AND c.expires>? AND g.revoked=0 AND g.expires>? AND g.client_id=? AND u.email_verified=1', (digest(code.code), int(time.time()), int(time.time()), client.client_id)).fetchone()
            if row:
                db.execute('UPDATE oauth_codes SET used=1 WHERE hash=?', (digest(code.code),))
                issued = self._issue(db, row)
        if not issued:
            raise TokenError('invalid_grant', 'Kode telah dipakai atau kedaluwarsa.')
        return issued

    def _lookup(self, raw, kind, client_id=None):
        if not isinstance(raw, str) or len(raw) > 256:
            return None
        table = 'oauth_access' if kind == 'access' else 'oauth_refresh'
        now = int(time.time())
        with self.vault.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute(f'SELECT t.*,g.id,g.user_id,g.client_id,g.resource,u.email FROM {table} t JOIN oauth_grants g ON g.id=t.grant_id JOIN users u ON u.id=g.user_id WHERE t.hash=? AND t.expires>? AND g.revoked=0 AND g.expires>? AND u.email_verified=1', (digest(raw), now, now)).fetchone()
            if not row or (client_id and row['client_id'] != client_id):
                return None
            if kind == 'refresh' and row['used']:
                db.execute('UPDATE oauth_grants SET revoked=1 WHERE id=?', (row['id'],))
                return None
            return dict(row)

    def load_access(self, raw):
        row = self._lookup(raw, 'access')
        return AccessToken(token=raw, client_id=row['client_id'], scopes=[SCOPE], expires_at=row['expires'], subject=row['user_id'], resource=row['resource'], claims={'iss': origin()}) if row else None

    def load_refresh(self, client, raw):
        row = self._lookup(raw, 'refresh', client.client_id)
        return RefreshToken(token=raw, client_id=row['client_id'], scopes=[SCOPE], expires_at=row['expires'], subject=row['user_id'], resource=row['resource']) if row else None

    def refresh(self, client, token, scopes, resource):
        if resource != token.resource:
            raise TokenError('invalid_target', 'Resource berbeda dari grant awal.')
        if scopes != [SCOPE]:
            raise TokenError('invalid_scope', 'Scope tidak dapat diperluas.')
        issued = None
        with self.vault.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT t.used,g.* FROM oauth_refresh t JOIN oauth_grants g ON g.id=t.grant_id JOIN users u ON u.id=g.user_id WHERE t.hash=? AND t.expires>? AND g.revoked=0 AND g.expires>? AND g.client_id=? AND u.email_verified=1', (digest(token.token), int(time.time()), int(time.time()), client.client_id)).fetchone()
            if row and row['used']:
                db.execute('UPDATE oauth_grants SET revoked=1 WHERE id=?', (row['id'],))
            elif row:
                db.execute('UPDATE oauth_refresh SET used=1 WHERE hash=?', (digest(token.token),))
                issued = self._issue(db, row)
        if not issued:
            raise TokenError('invalid_grant', 'Refresh token telah dipakai atau dicabut.')
        return issued

    def revoke(self, token):
        table = 'oauth_access' if isinstance(token, AccessToken) else 'oauth_refresh'
        with self.vault.db() as db:
            db.execute(f'UPDATE oauth_grants SET revoked=1 WHERE id IN (SELECT grant_id FROM {table} WHERE hash=?) AND client_id=?', (digest(token.token), token.client_id))

    def identity(self, raw, resource):
        row = self._lookup(raw, 'access')
        return {'id': row['user_id'], 'email': row['email'], 'oauth_client': row['client_id'], 'resource': row['resource']} if row and row['resource'] == resource else None
