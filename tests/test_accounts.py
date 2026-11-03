import asyncio
import base64
import json
from pathlib import Path
import secrets
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

import httpx
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route

from src import accounts, server
from src.accounts_http import install


class AccountTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.key=base64.b64encode(secrets.token_bytes(32)).decode()
        self.vault=accounts.Vault(Path(self.temp.name)/'accounts.sqlite3',self.key)
        self.patch=patch('src.accounts.get_vault',return_value=self.vault);self.patch.start()
        self.patch2=patch('src.accounts_http.get_vault',return_value=self.vault);self.patch2.start()
        self.mail_patch=patch('src.accounts_http.send_verification');self.mail=self.mail_patch.start()
        self.env=patch.dict('os.environ',{'ACCOUNTS_PUBLIC_ORIGIN':'https://app.test','ACCOUNTS_DEV_HTTP':'0'});self.env.start()
        async def mcp(request):
            key=server._account_key()
            return JSONResponse({'user':accounts.principal.get()['id'],'has_key':bool(key)})
        async def bps(request): return JSONResponse({'ok':bool(server._account_key())})
        self.app=install(Starlette(routes=[Route('/mcp',mcp,methods=['POST']),Route('/api/bps',bps,methods=['POST']),Route('/messages/',mcp,methods=['POST'])]))
        self.client=httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app),base_url='https://app.test',headers={'Origin':'https://app.test'})

    async def asyncTearDown(self):
        await self.client.aclose();self.env.stop();self.mail_patch.stop();self.patch2.stop();self.patch.stop();self.temp.cleanup()

    async def register_login(self,email='alice@example.test'):
        response=await self.client.post('/api/account/register',json={'email':email,'password':'correct horse battery staple'})
        self.assertEqual(response.status_code,201,response.text)
        recovery=response.json()['recovery_code']
        self.vault.verify_email(self.mail.call_args.args[1])
        response=await self.client.post('/api/account/login',json={'email':email,'password':'correct horse battery staple'})
        self.assertEqual(response.status_code,200,response.text)
        cookie=response.headers['set-cookie']
        for marker in ['HttpOnly','Secure','SameSite=lax','Path=/']:self.assertIn(marker,cookie)
        profile=(await self.client.get('/api/account/me')).json()
        self.client.headers['X-CSRF-Token']=profile['csrf']
        return recovery,profile

    async def test_complete_lifecycle_and_encrypted_storage(self):
        recovery,profile=await self.register_login()
        key='personal-bps-key-1234'
        response=await self.client.post('/api/account/credentials',json={'service':'bps','key':key})
        self.assertEqual(response.status_code,200)
        created=await self.client.post('/api/account/tokens',json={'label':'Laptop','days':1})
        token=created.json()['token']
        self.assertTrue(token.startswith('mcp_'))
        profile=(await self.client.get('/api/account/me')).json()
        encoded=json.dumps(profile)
        for secret in [key,token,recovery,'correct horse battery staple']:self.assertNotIn(secret,encoded)
        raw=Path(self.vault.path).read_bytes()
        for secret in [key,token,recovery,'correct horse battery staple']:self.assertNotIn(secret.encode(),raw)
        self.assertEqual(self.vault.get_key(profile['user']['id']),key)
        self.assertEqual((await self.client.post('/mcp',json={},headers={'Authorization':'Bearer '+token})).status_code,200)
        # Session cookies cannot authenticate an MCP client.
        self.assertEqual((await self.client.post('/mcp',json={})).status_code,401)
        revoked=await self.client.post('/api/account/tokens',json={'revoke':profile['tokens'][0]['id']})
        self.assertEqual(revoked.status_code,200)
        self.assertEqual((await self.client.post('/mcp',json={},headers={'Authorization':'Bearer '+token})).status_code,401)
        self.assertEqual((await self.client.post('/api/account/logout',json={})).status_code,200)
        self.assertEqual((await self.client.get('/api/account/me')).status_code,401)

    async def test_csrf_and_cross_origin_rejected(self):
        await self.register_login()
        for headers in [{'X-CSRF-Token':'wrong'},{'Origin':'https://evil.test'}]:
            r=await self.client.post('/api/account/tokens',json={'label':'evil'},headers=headers)
            self.assertEqual(r.status_code,403)
            r=await self.client.post('/api/bps',json={},headers=headers)
            self.assertEqual(r.status_code,403)
        self.assertEqual((await self.client.post('/api/account/login',json={},headers={'Origin':'https://evil.test'})).status_code,403)

    async def test_recovery_rotates_code_and_revokes_everything(self):
        recovery,profile=await self.register_login()
        token=self.vault.create_token(profile['user']['id'],'old')
        r=await self.client.post('/api/account/recover',json={'email':'alice@example.test','recovery_code':recovery,'password':'a completely new password'})
        self.assertEqual(r.status_code,200,r.text)
        self.assertNotEqual(r.json()['recovery_code'],recovery)
        self.assertIsNone(self.vault.identity(token,'mcp'))
        self.assertEqual((await self.client.get('/api/account/me')).status_code,401)
        with self.assertRaises(ValueError):self.vault.recover('alice@example.test',recovery,'another different password')

    async def test_cross_user_keys_and_tokens_are_isolated(self):
        _,a=await self.register_login()
        uid_a=a['user']['id'];self.vault.save_key(uid_a,'bps','alice-key-1234')
        token_a=self.vault.create_token(uid_a,'Alice')
        uid_b,_=self.vault.register('bob@example.test','password for bob long enough')
        self.vault.verify_email(self.vault.verification_token(uid_b))
        self.vault.save_key(uid_b,'bps','bob-key-567890')
        token_b=self.vault.create_token(uid_b,'Bob')
        token_id=self.vault.profile(uid_a)['tokens'][0]['id']
        self.vault.revoke_token(uid_b,token_id)
        self.assertIsNotNone(self.vault.identity(token_a,'mcp'))
        for uid,token,key in [(uid_a,token_a,'alice-key-1234'),(uid_b,token_b,'bob-key-567890')]:
            context=accounts.principal.set({'id':uid,'raw':token,'kind':'mcp'})
            try:self.assertEqual(server._account_key(),key)
            finally:accounts.principal.reset(context)
        with self.vault.db() as db:
            cipher=db.execute('SELECT ciphertext FROM credentials WHERE user_id=?',(uid_a,)).fetchone()[0]
            db.execute('UPDATE credentials SET ciphertext=? WHERE user_id=?',(cipher,uid_b))
        with self.assertRaises(Exception):self.vault.get_key(uid_b)

    async def test_expired_token_and_wrong_master_key_fail_closed(self):
        _,profile=await self.register_login()
        token=self.vault.create_token(profile['user']['id'],'expire')
        with self.vault.db() as db:db.execute('UPDATE tokens SET expires=0')
        self.assertIsNone(self.vault.identity(token,'mcp'))
        with self.assertRaises(ValueError):accounts.Vault(self.vault.path,base64.b64encode(secrets.token_bytes(32)).decode())
        with self.assertRaises(ValueError):accounts.Vault(self.vault.path,'')

    async def test_password_change_revokes_sessions_and_mcp_tokens(self):
        _,profile=await self.register_login()
        token=self.vault.create_token(profile['user']['id'],'expire')
        r=await self.client.post('/api/account/password',json={'old_password':'correct horse battery staple','password':'new secure password abcdef'})
        self.assertEqual(r.status_code,200)
        self.assertIsNone(self.vault.identity(token,'mcp'))
        self.assertEqual((await self.client.get('/api/account/me')).status_code,401)

    async def test_failed_authentication_is_rate_limited(self):
        for _ in range(10):
            r=await self.client.post('/api/account/login',json={'email':'missing@example.test','password':'wrong but long enough'})
            self.assertEqual(r.status_code,400)
        r=await self.client.post('/api/account/login',json={'email':'missing@example.test','password':'wrong but long enough'})
        self.assertEqual(r.status_code,429)

    async def test_sse_messages_require_session_ownership(self):
        _,profile=await self.register_login()
        token=self.vault.create_token(profile['user']['id'],'sse')
        r=await self.client.post('/messages/?session_id=foreign',headers={'Authorization':'Bearer '+token})
        self.assertEqual(r.status_code,403)

    async def test_real_mcp_transport_uses_saved_key_and_enforces_revocation(self):
        if not server._security_at_runtime:
            self.skipTest('MCP 2 integration path; other SDKs covered by boundary tests')
        from mcp.server.transport_security import TransportSecuritySettings
        _,profile=await self.register_login()
        uid=profile['user']['id']
        self.vault.save_key(uid,'bps','real-transport-user-key')
        token=self.vault.create_token(uid,'transport')
        app=install(server.mcp.streamable_http_app(stateless_http=True,json_response=True,host='app.test',transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=True,allowed_hosts=['app.test'],allowed_origins=['https://app.test'])))
        upstream=AsyncMock(return_value={'status':'OK','data':[{'domain_id':'1100'}]})
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='https://app.test') as client:
                with patch.object(server,'_read_bps_payload',upstream):
                    response=await client.post('/mcp',headers={'Authorization':'Bearer '+token,'Accept':'application/json, text/event-stream','Origin':'https://app.test'},json={'jsonrpc':'2.0','id':1,'method':'tools/call','params':{'name':'bps_request','arguments':{'operation':'listDomains','parameters':{'type':'all'}}}})
                self.assertEqual(response.status_code,200,response.text)
                self.assertIn('real-transport-user-key',upstream.call_args.args[0])
                self.assertNotIn('real-transport-user-key',response.text)
                self.vault.revoke_token(uid,self.vault.profile(uid)['tokens'][0]['id'])
                response=await client.post('/mcp',headers={'Authorization':'Bearer '+token},json={})
                self.assertEqual(response.status_code,401)

    async def test_master_key_rotation_preserves_credentials_and_revokes_sessions(self):
        from scripts.rotate_account_key import main
        _,profile=await self.register_login()
        uid=profile['user']['id'];self.vault.save_key(uid,'bps','rotated-user-key-1234')
        token=self.vault.create_token(uid,'keep-token')
        new=base64.b64encode(secrets.token_bytes(32)).decode()
        with patch.dict('os.environ',{'ACCOUNTS_DB_PATH':self.vault.path,'ACCOUNTS_ENCRYPTION_KEY':self.key,'ACCOUNTS_NEW_ENCRYPTION_KEY':new}):main()
        rotated=accounts.Vault(self.vault.path,new)
        self.assertEqual(rotated.get_key(uid),'rotated-user-key-1234')
        self.assertIsNotNone(rotated.identity(token,'mcp'))
        self.assertEqual((await self.client.get('/api/account/me')).status_code,401)
        with self.assertRaises(ValueError):accounts.Vault(self.vault.path,self.key)

    async def test_email_verification_required_and_link_is_one_time(self):
        r=await self.client.post('/api/account/register',json={'email':'verify@example.test','password':'verification password abcdef'})
        self.assertEqual(r.status_code,201,r.text)
        self.assertTrue(r.json()['verification_sent'])
        token=self.mail.call_args.args[1]
        self.assertNotIn(token,r.text)
        self.assertNotIn(token.encode(),Path(self.vault.path).read_bytes())
        r=await self.client.post('/api/account/login',json={'email':'verify@example.test','password':'verification password abcdef'})
        self.assertEqual(r.status_code,400)
        self.assertIn('belum diverifikasi',r.json()['error'])
        r=await self.client.post('/api/account/verify',json={'token':token})
        self.assertEqual(r.status_code,200)
        self.assertEqual((await self.client.post('/api/account/verify',json={'token':token})).status_code,400)
        self.assertEqual((await self.client.post('/api/account/login',json={'email':'verify@example.test','password':'verification password abcdef'})).status_code,200)

    async def test_expired_verification_and_sibling_tokens(self):
        uid,_=self.vault.register('expiry@example.test','verification password abcdef')
        expired=self.vault.verification_token(uid)
        with self.vault.db() as db:db.execute('UPDATE email_verifications SET expires=0')
        with self.assertRaises(ValueError):self.vault.verify_email(expired)
        a=self.vault.verification_token(uid);b=self.vault.verification_token(uid)
        self.vault.verify_email(a)
        with self.assertRaises(ValueError):self.vault.verify_email(b)

    async def test_smtp_failure_preserves_pending_account_and_allows_resend(self):
        from src.mailer import MailUnavailable
        self.mail.side_effect=MailUnavailable('unavailable')
        r=await self.client.post('/api/account/register',json={'email':'retry@example.test','password':'verification password abcdef'})
        self.assertEqual(r.status_code,201)
        self.assertFalse(r.json()['verification_sent'])
        self.assertIn('recovery_code',r.json())
        with self.vault.db() as db:self.assertEqual(db.execute('SELECT count(*) FROM email_verifications').fetchone()[0],0)
        self.mail.side_effect=None
        import time
        with patch('src.accounts.time.time',return_value=time.time()+61):
            r=await self.client.post('/api/account/resend',json={'email':'retry@example.test','password':'verification password abcdef'})
        self.assertEqual(r.status_code,200)
        self.assertEqual(self.mail.call_count,2)

    async def test_resend_does_not_email_wrong_credentials(self):
        await self.client.post('/api/account/register',json={'email':'quiet@example.test','password':'verification password abcdef'})
        count=self.mail.call_count
        r=await self.client.post('/api/account/resend',json={'email':'quiet@example.test','password':'wrong verification password'})
        self.assertEqual(r.status_code,200)
        self.assertEqual(self.mail.call_count,count)

    async def test_old_accounts_require_verification_after_schema_migration(self):
        _,profile=await self.register_login()
        old_token=self.vault.create_token(profile['user']['id'],'old-version')
        with self.vault.db() as db:db.execute('ALTER TABLE users DROP COLUMN email_verified')
        with self.assertRaises(ValueError):accounts.Vault(self.vault.path,base64.b64encode(secrets.token_bytes(32)).decode())
        with self.vault.db() as db:self.assertNotIn('email_verified',{r[1] for r in db.execute('PRAGMA table_info(users)')})
        upgraded=accounts.Vault(self.vault.path,self.key)
        self.assertIsNone(upgraded.identity(old_token,'mcp'))
        with self.assertRaises(ValueError):upgraded.login('alice@example.test','correct horse battery staple')

    async def test_key_paste_normalization_and_rejected_input_does_not_overwrite(self):
        _,profile=await self.register_login()
        valid='synthetic+base64/key=1234'
        r=await self.client.post('/api/account/credentials',json={'service':'bps','key':' \n'+valid+'\t '})
        self.assertEqual(r.status_code,200,r.text)
        self.assertEqual(self.vault.get_key(profile['user']['id']),valid)
        self.assertEqual(r.json()['credentials'][0]['service'],'bps')
        self.assertNotIn(valid,r.text)
        for value in ['https://example.com/key','Bearer copied-key-value','key with whitespace','short']:
            r=await self.client.post('/api/account/credentials',json={'service':'bps','key':value})
            self.assertEqual(r.status_code,400)
            self.assertEqual(r.json()['error'],'invalid_api_key')
            self.assertTrue(r.json()['message'])
            self.assertEqual(self.vault.get_key(profile['user']['id']),valid)
