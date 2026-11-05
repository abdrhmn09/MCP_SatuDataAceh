"""Persistent account vault. Never store raw passwords, session tokens or MCP tokens."""
import base64
from contextlib import contextmanager
from contextvars import ContextVar
from functools import lru_cache
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3
import time

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

principal = ContextVar('account_principal', default=None)


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def password_hash(password, salt=None):
    if not isinstance(password, str) or not 12 <= len(password) <= 256:
        raise ValueError('Sandi ini tidak dapat digunakan. Coba frasa sandi lain.')
    salt = salt or secrets.token_bytes(16)
    hashed = hashlib.scrypt(password.encode(), salt=salt, n=2**17, r=8, p=1, maxmem=256*1024*1024)
    return salt.hex() + ':' + hashed.hex()


def verify_password(password, stored):
    try:
        salt, _ = stored.split(':')
        return hmac.compare_digest(password_hash(password, bytes.fromhex(salt)), stored)
    except (ValueError, TypeError):
        return False


class Vault:
    def __init__(self, path, encryption_key):
        try:
            self.key = base64.b64decode(encryption_key, validate=True)
            if len(self.key) != 32: raise ValueError()
        except Exception:
            raise ValueError('ACCOUNTS_ENCRYPTION_KEY harus base64 dari 32 byte acak; tidak ada key default.')
        self.cipher = AESGCM(self.key)
        self.path = str(path)
        Path(path).parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        with self.db() as db:
            db.executescript('''
            CREATE TABLE IF NOT EXISTS users(id TEXT PRIMARY KEY,email TEXT UNIQUE NOT NULL,password TEXT NOT NULL,recovery TEXT NOT NULL,created INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS credentials(user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,service TEXT NOT NULL,ciphertext BLOB NOT NULL,updated INTEGER NOT NULL,PRIMARY KEY(user_id,service));
            CREATE TABLE IF NOT EXISTS sessions(hash TEXT PRIMARY KEY,user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,expires INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS tokens(id TEXT PRIMARY KEY,user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,hash TEXT UNIQUE NOT NULL,label TEXT NOT NULL,created INTEGER NOT NULL,expires INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS attempts(bucket TEXT PRIMARY KEY,count INTEGER NOT NULL,expires INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS sse_sessions(hash TEXT PRIMARY KEY,user_id TEXT NOT NULL,expires INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS email_verifications(hash TEXT PRIMARY KEY,user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,expires INTEGER NOT NULL);
            ''')
        os.chmod(self.path, 0o600)
        # Detect a wrong master key at startup, before accepting registrations.
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('CREATE TABLE IF NOT EXISTS vault_meta(id INTEGER PRIMARY KEY,check_value BLOB NOT NULL)')
            row = db.execute('SELECT check_value FROM vault_meta WHERE id=1').fetchone()
            if row:
                try: self.cipher.decrypt(row[0][:12], row[0][12:], b'vault-check')
                except Exception: raise ValueError('Kunci enkripsi tidak cocok dengan database akun.')
            else:
                nonce = secrets.token_bytes(12)
                db.execute('INSERT INTO vault_meta VALUES(1,?)', (nonce+self.cipher.encrypt(nonce,b'vault-v1',b'vault-check'),))
        # Upgrade older databases only after validating the master key.
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            if 'email_verified' not in {row[1] for row in db.execute('PRAGMA table_info(users)')}:
                db.execute('ALTER TABLE users ADD COLUMN email_verified INTEGER NOT NULL DEFAULT 0')
                db.execute('DELETE FROM sessions')
                db.execute('DELETE FROM tokens')
            db.execute("UPDATE users SET recovery='' WHERE recovery<>''")
            db.execute('''CREATE TABLE IF NOT EXISTS account_links(
                hash TEXT PRIMARY KEY,
                user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                purpose TEXT NOT NULL CHECK(purpose IN ('reset','delete')),
                expires INTEGER NOT NULL
            )''')
            db.execute('CREATE INDEX IF NOT EXISTS account_links_user ON account_links(user_id)')
        self.dummy_password = password_hash('dummy-password-never-used')
        from .oauth import init_schema
        init_schema(self)

    @contextmanager
    def db(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        db.execute('PRAGMA secure_delete=ON')
        try:
            with db: yield db
        finally: db.close()

    def throttle(self, bucket, limit=10, window=900):
        now = int(time.time())
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('DELETE FROM attempts WHERE expires <= ?', (now,))
            row = db.execute('SELECT count FROM attempts WHERE bucket=?',(digest(bucket),)).fetchone()
            if row and row[0] >= limit: return False
            db.execute('INSERT INTO attempts VALUES(?,1,?) ON CONFLICT(bucket) DO UPDATE SET count=count+1',(digest(bucket),now+window))
        return True

    @staticmethod
    def email(email):
        if not isinstance(email,str) or len(email)>254 or not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',email.strip()):
            raise ValueError('Alamat email tidak valid.')
        return email.strip().lower()

    def register(self, email, password):
        email = self.email(email)
        uid = secrets.token_hex(16)
        encoded = password_hash(password)
        try:
            with self.db() as db:
                db.execute('INSERT INTO users(id,email,password,recovery,created,email_verified) VALUES(?,?,?,?,?,0)',(uid,email,encoded,'',int(time.time())))
        except sqlite3.IntegrityError: raise ValueError('Pendaftaran tidak dapat diproses. Gunakan login atau pemulihan akun.')
        return uid

    def login(self, email, password):
        email = self.email(email)
        with self.db() as db: user = db.execute('SELECT * FROM users WHERE email=?',(email,)).fetchone()
        valid = verify_password(password, user['password'] if user else self.dummy_password)
        if not user or not valid: raise ValueError('Email atau sandi tidak cocok.')
        if not user['email_verified']: raise ValueError('Email belum diverifikasi. Periksa inbox/spam atau gunakan Kirim ulang verifikasi.')
        token = 'ses_' + secrets.token_urlsafe(32)
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            current=db.execute('SELECT password FROM users WHERE id=?',(user['id'],)).fetchone()
            if not current or not hmac.compare_digest(current[0],user['password']): raise ValueError('Email atau sandi tidak cocok.')
            db.execute('DELETE FROM sessions WHERE expires<=?',(int(time.time()),))
            db.execute('INSERT INTO sessions VALUES(?,?,?)',(digest(token),user['id'],int(time.time())+43200))
        return token

    def identity(self, raw, kind='session'):
        if not isinstance(raw,str) or len(raw)>256: return None
        table = 'sessions' if kind=='session' else 'tokens'
        with self.db() as db:
            row = db.execute(f'SELECT users.id,users.email FROM {table} JOIN users ON users.id={table}.user_id WHERE {table}.hash=? AND expires>? AND users.email_verified=1',(digest(raw),int(time.time()))).fetchone()
        return dict(row) if row else None

    def verification_token(self, uid):
        token = 'verify_' + secrets.token_urlsafe(32)
        now = int(time.time())
        with self.db() as db:
            db.execute('DELETE FROM email_verifications WHERE expires<=?', (now,))
            user = db.execute('SELECT email_verified FROM users WHERE id=?', (uid,)).fetchone()
            if not user or user[0]: raise ValueError('Akun tidak memerlukan verifikasi.')
            db.execute('INSERT INTO email_verifications VALUES(?,?,?)', (digest(token),uid,now+3600))
        return token

    def discard_verification(self, token):
        with self.db() as db: db.execute('DELETE FROM email_verifications WHERE hash=?', (digest(token),))

    def verify_email(self, token):
        if not isinstance(token, str) or not token.startswith('verify_') or len(token)>128:
            raise ValueError('Tautan verifikasi tidak valid atau sudah kedaluwarsa.')
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT user_id FROM email_verifications WHERE hash=? AND expires>?', (digest(token),int(time.time()))).fetchone()
            if not row: raise ValueError('Tautan verifikasi tidak valid atau sudah kedaluwarsa.')
            db.execute('UPDATE users SET email_verified=1 WHERE id=?', (row[0],))
            db.execute('DELETE FROM email_verifications WHERE user_id=?', (row[0],))

    def pending_user(self, email, password):
        email=self.email(email)
        with self.db() as db: user=db.execute('SELECT * FROM users WHERE email=?', (email,)).fetchone()
        valid=verify_password(password,user['password'] if user else self.dummy_password)
        return dict(user) if valid and user and not user['email_verified'] else None

    def csrf(self, raw):
        return hmac.new(self.key, ('csrf:'+raw).encode(),hashlib.sha256).hexdigest()

    def save_key(self, uid, service, value):
        if service not in {'bps','sdgs'}: raise ValueError('Layanan tidak dikenal.')
        if not isinstance(value,str): raise ValueError('API key harus berupa teks.')
        value=value.strip()
        if re.match(r'(?i)^(https?://|bearer\s|authorization\s*:)',value):
            raise ValueError('Tempel nilai API key saja, bukan URL atau header Authorization.')
        if re.search(r'\s',value):
            raise ValueError('Ada spasi atau baris baru di tengah key. Salin ulang nilai key dari akun BPS.')
        if service == 'sdgs' and not re.fullmatch(r'[!-~]{8,512}',value):
            raise ValueError('Format token SDGs belum sesuai. Salin hanya nilai token SDGs.')
        if service == 'bps' and not re.fullmatch(r'[A-Za-z0-9._~+/=-]{8,512}',value):
            raise ValueError('Format key belum sesuai. Gunakan 8–512 karakter token dan salin hanya nilai key.')
        nonce = secrets.token_bytes(12)
        ciphertext = nonce + self.cipher.encrypt(nonce,value.encode(),f'{uid}:{service}'.encode())
        with self.db() as db:
            db.execute('INSERT INTO credentials VALUES(?,?,?,?) ON CONFLICT(user_id,service) DO UPDATE SET ciphertext=excluded.ciphertext,updated=excluded.updated',(uid,service,ciphertext,int(time.time())))

    def get_key(self, uid, service='bps'):
        with self.db() as db: row=db.execute('SELECT ciphertext FROM credentials WHERE user_id=? AND service=?',(uid,service)).fetchone()
        if not row: return ''
        value=row[0]
        return self.cipher.decrypt(value[:12],value[12:],f'{uid}:{service}'.encode()).decode()

    def delete_key(self,uid,service):
        with self.db() as db: db.execute('DELETE FROM credentials WHERE user_id=? AND service=?',(uid,service))

    def profile(self,uid):
        with self.db() as db:
            user=db.execute('SELECT id,email,created,email_verified FROM users WHERE id=?',(uid,)).fetchone()
            keys=[dict(row) for row in db.execute('SELECT service,updated FROM credentials WHERE user_id=?',(uid,))]
            tokens=[dict(row) for row in db.execute('SELECT id,label,created,expires FROM tokens WHERE user_id=? AND expires>? ORDER BY created DESC',(uid,int(time.time())))]
        from .oauth import OAuthStore
        return {'user':dict(user),'credentials':keys,'tokens':tokens,'apps':OAuthStore(self).apps(uid)}

    def create_token(self,uid,label,days=30,*,session=None):
        if not isinstance(label,str) or not 1<=len(label.strip())<=80 or isinstance(days,bool) or not isinstance(days,int) or not 1<=days<=90: raise ValueError('Label wajib diisi; masa berlaku token 1–90 hari.')
        token='mcp_'+secrets.token_urlsafe(32)
        now=int(time.time())
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            user=db.execute('SELECT email_verified FROM users WHERE id=?',(uid,)).fetchone()
            if not user or not user[0]: raise ValueError('Verifikasi email sebelum membuat token MCP.')
            if session is not None and not self._active_session(db, uid, session):
                raise ValueError('Sesi telah berakhir. Silakan masuk kembali.')
            if db.execute('SELECT count(*) FROM tokens WHERE user_id=? AND expires>?',(uid,now)).fetchone()[0]>=20: raise ValueError('Maksimal 20 token aktif; cabut token lama.')
            db.execute('INSERT INTO tokens VALUES(?,?,?,?,?,?)',(secrets.token_hex(16),uid,digest(token),label.strip(),now,now+days*86400))
        return token

    def revoke_token(self,uid,token_id):
        with self.db() as db: db.execute('DELETE FROM tokens WHERE id=? AND user_id=?',(token_id,uid))

    def logout(self,raw):
        with self.db() as db: db.execute('DELETE FROM sessions WHERE hash=?',(digest(raw),))

    @staticmethod
    def _active_session(db, uid, raw):
        return db.execute('SELECT 1 FROM sessions WHERE user_id=? AND hash=? AND expires>?',
                          (uid,digest(raw),int(time.time()))).fetchone()

    def _session_id(self, stored_hash):
        return hmac.digest(self.key, ('session-id:' + stored_hash).encode(), 'sha256').hex()

    def sessions(self, uid, raw):
        current = digest(raw)
        with self.db() as db:
            rows = db.execute('SELECT hash,expires FROM sessions WHERE user_id=? AND expires>? ORDER BY expires DESC', (uid,int(time.time())))
            return [{'id':self._session_id(row['hash']), 'expires':row['expires'], 'current':row['hash']==current} for row in rows]

    def revoke_session(self, uid, raw, session_id):
        if session_id != 'others' and (not isinstance(session_id, str) or not re.fullmatch(r'[0-9a-f]{64}', session_id)):
            raise ValueError('Pilih sesi yang akan diakhiri.')
        current = digest(raw)
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            if not self._active_session(db, uid, raw):
                raise ValueError('Sesi telah berakhir. Silakan masuk kembali.')
            if session_id == 'others':
                db.execute('DELETE FROM sessions WHERE user_id=? AND hash<>?', (uid,current))
                return False
            for row in db.execute('SELECT hash FROM sessions WHERE user_id=? AND expires>?', (uid,int(time.time()))):
                stored = row['hash']
                if hmac.compare_digest(self._session_id(stored), session_id):
                    db.execute('DELETE FROM sessions WHERE user_id=? AND hash=?', (uid,stored))
                    return stored == current
        return False

    @staticmethod
    def _revoke_access(db, uid):
        from .oauth import revoke_user
        for table in ('sessions', 'tokens', 'sse_sessions', 'account_links'):
            db.execute(f'DELETE FROM {table} WHERE user_id=?', (uid,))
        revoke_user(db, uid)

    def change_password(self,uid,old,new,*,session=None):
        with self.db() as db: row=db.execute('SELECT password FROM users WHERE id=?',(uid,)).fetchone()
        if not row or not verify_password(old,row[0]): raise ValueError('Sandi saat ini tidak cocok.')
        encoded=password_hash(new)
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            if session is not None and not self._active_session(db, uid, session):
                raise ValueError('Sesi telah berakhir. Silakan masuk kembali.')
            changed=db.execute('UPDATE users SET password=? WHERE id=? AND password=?',(encoded,uid,row[0]))
            if changed.rowcount!=1: raise ValueError('Sandi berubah. Silakan masuk kembali.')
            self._revoke_access(db, uid)

    @staticmethod
    def _issue_link(db, uid, purpose):
        token = purpose + '_' + secrets.token_urlsafe(32)
        now = int(time.time())
        db.execute('DELETE FROM account_links WHERE expires<=?', (now,))
        db.execute('INSERT INTO account_links VALUES(?,?,?,?)', (digest(token),uid,purpose,now+1800))
        return token

    def reset_link(self, email):
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT id FROM users WHERE email=? AND email_verified=1', (email,)).fetchone()
            return self._issue_link(db, row['id'], 'reset') if row else None

    def delete_link(self, uid, raw, password):
        with self.db() as db:
            row = db.execute('SELECT email,password FROM users WHERE id=?', (uid,)).fetchone()
        if not row or not verify_password(password, row['password']):
            raise ValueError('Sandi saat ini tidak cocok.')
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            unchanged = db.execute('SELECT 1 FROM users WHERE id=? AND password=?', (uid,row['password'])).fetchone()
            if not unchanged or not self._active_session(db, uid, raw):
                raise ValueError('Sesi atau sandi telah berubah. Silakan masuk kembali.')
            return row['email'], self._issue_link(db, uid, 'delete')

    def discard_link(self, token):
        with self.db() as db:
            db.execute('DELETE FROM account_links WHERE hash=?', (digest(token),))

    @staticmethod
    def _link_user(db, token, purpose):
        if isinstance(token, str) and re.fullmatch(purpose + r'_[A-Za-z0-9_-]{43}', token):
            row = db.execute('SELECT user_id FROM account_links WHERE hash=? AND purpose=? AND expires>?',
                (digest(token),purpose,int(time.time()))).fetchone()
            if row:
                return row['user_id']
        raise ValueError('Tautan tidak valid atau sudah kedaluwarsa. Minta tautan baru.')

    def reset_password(self, token, password):
        with self.db() as db:
            self._link_user(db, token, 'reset')
        encoded = password_hash(password)
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            uid = self._link_user(db, token, 'reset')
            db.execute('UPDATE users SET password=? WHERE id=?', (encoded,uid))
            self._revoke_access(db, uid)
        return uid

    def delete_account(self, token):
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            uid = self._link_user(db, token, 'delete')
            self._revoke_access(db, uid)
            db.execute('DELETE FROM users WHERE id=?', (uid,))
        return uid


@lru_cache(maxsize=1)
def get_vault():
    return Vault(os.getenv('ACCOUNTS_DB_PATH','var/accounts.sqlite3'),os.getenv('ACCOUNTS_ENCRYPTION_KEY',''))
