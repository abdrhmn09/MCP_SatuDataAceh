"""Rotate the account vault key atomically. Stop all server/Worker traffic first.
Supply ACCOUNTS_ENCRYPTION_KEY (old), ACCOUNTS_NEW_ENCRYPTION_KEY and ACCOUNTS_DB_PATH
via environment, never command arguments. Back up database and both keys first.
"""
import base64
import os
import secrets
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).parents[1]))
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from src.accounts import Vault


def main():
    path=os.environ['ACCOUNTS_DB_PATH']
    if not Path(path).is_file(): raise ValueError('Database tidak ditemukan.')
    new=base64.b64decode(os.environ['ACCOUNTS_NEW_ENCRYPTION_KEY'],validate=True)
    if len(new)!=32: raise ValueError('Key baru harus 32 byte.')
    vault=Vault(path,os.environ['ACCOUNTS_ENCRYPTION_KEY'])
    cipher=AESGCM(new)
    with vault.db() as db:
        db.execute('BEGIN IMMEDIATE')
        for row in db.execute('SELECT user_id,service,ciphertext FROM credentials').fetchall():
            uid,service,old=row
            aad=f'{uid}:{service}'.encode()
            plaintext=vault.cipher.decrypt(old[:12],old[12:],aad)
            nonce=secrets.token_bytes(12)
            db.execute('UPDATE credentials SET ciphertext=? WHERE user_id=? AND service=?',(nonce+cipher.encrypt(nonce,plaintext,aad),uid,service))
        nonce=secrets.token_bytes(12)
        db.execute('UPDATE vault_meta SET check_value=? WHERE id=1',(nonce+cipher.encrypt(nonce,b'vault-v1',b'vault-check'),))
        # Existing browser CSRF tokens change under the new master key.
        db.execute('DELETE FROM sessions')
    print('Vault key rotated. Update server encryption secret before restarting; old browser sessions invalidated.')


if __name__=='__main__':main()
