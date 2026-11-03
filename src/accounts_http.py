"""Account HTTP surface, CSRF checks and per-request MCP identity enforcement."""
import asyncio
import hmac
import json
import logging
import os
import re
import time
from urllib.parse import parse_qs

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

try:
    from .accounts import digest, get_vault, principal
    from .mailer import send_verification, MailUnavailable
except ImportError:
    from accounts import digest, get_vault, principal
    from mailer import send_verification, MailUnavailable

logger = logging.getLogger(__name__)

_hash_slots = asyncio.Semaphore(2)
_mail_slots = asyncio.Semaphore(2)


def cookie_name():
    return 'mcp_dev_session' if os.getenv('ACCOUNTS_DEV_HTTP')=='1' else '__Host-mcp_session'


def origin_allowed(request):
    configured=os.getenv('ACCOUNTS_PUBLIC_ORIGIN','https://www.mcpsatudataaceh.web.id')
    allowed={configured,*filter(None,os.getenv('ACCOUNTS_ALLOWED_ORIGINS','').split(','))}
    origin=request.headers.get('origin')
    return bool(origin and origin in allowed)


def result(data,status=200):
    return JSONResponse(data,status_code=status,headers={'Cache-Control':'no-store','X-Content-Type-Options':'nosniff','Referrer-Policy':'no-referrer'})


async def read_body(request):
    raw=bytearray()
    async with asyncio.timeout(10):
        async for chunk in request.stream():
            raw.extend(chunk)
            if len(raw)>8192: raise ValueError('Permintaan terlalu besar.')
    body=json.loads(raw or b'{}')
    if not isinstance(body,dict): raise ValueError('Body harus objek JSON.')
    return body


async def dispatch_verification(vault, uid, email):
    if not vault.throttle('verify-cooldown:'+uid,1,60) or not vault.throttle('verify-user:'+uid,3,3600) or not vault.throttle('verify-daily',max(1,int(os.getenv('SMTP_DAILY_LIMIT','100'))),86400):
        return False
    token=vault.verification_token(uid)
    try:
        async with _mail_slots:
            await asyncio.to_thread(send_verification,email,token)
        return True
    except MailUnavailable:
        vault.discard_verification(token)
        return False


async def account_route(request):
    try:
        vault=get_vault()
        action=request.path_params['action']
        if request.method=='GET' and action=='config':
            from .oauth import origin
            return result({'mode':'accounts','registration':True,'email_verification':True,'oauth':True,'mcp_url':origin()+'/mcp','sse_url':origin()+'/sse'})
        if request.method=='POST' and not origin_allowed(request): return result({'error':'origin_rejected'},403)
        raw=request.cookies.get(cookie_name(),'')
        user=vault.identity(raw)
        if request.method=='GET' and action=='me':
            if not user: return result({'error':'login_required'},401)
            return result({**vault.profile(user['id']),'csrf':vault.csrf(raw)})
        if request.method!='POST': return result({'error':'not_found'},404)
        body=await read_body(request)
        peer=request.client.host if request.client else 'local'
        service_secret=os.getenv('ACCOUNTS_SERVICE_SECRET','')
        if len(service_secret)>=32 and hmac.compare_digest(request.headers.get('x-account-service-secret',''),service_secret):
            peer=request.headers.get('x-account-client-ip',peer)
        if action in {'register','login','recover','resend','verify'}:
            if not vault.throttle('auth-ip:'+peer,30) or not vault.throttle('auth-user:'+str(body.get('email','') or peer).strip().lower(),10):
                return result({'error':'Terlalu banyak percobaan. Coba lagi dalam 15 menit.'},429)
            if action=='verify':
                vault.verify_email(body.get('token'))
                return result({'ok':True,'message':'Email terverifikasi. Silakan login.'})
            if action=='resend':
                async with _hash_slots:
                    pending=await asyncio.to_thread(vault.pending_user,body.get('email'),body.get('password'))
                if pending:
                    await dispatch_verification(vault,pending['id'],pending['email'])
                return result({'ok':True,'message':'Jika data akun cocok dan belum terverifikasi, email akan dikirim. Periksa inbox/spam; kirim ulang dibatasi.'})
            if action=='register':
                async with _hash_slots:
                    uid,recovery=await asyncio.to_thread(vault.register,body.get('email'),body.get('password'))
                sent=await dispatch_verification(vault,uid,vault.email(body.get('email')))
                return result({'ok':True,'recovery_code':recovery,'verification_sent':sent,'message':'Simpan kode pemulihan ini. '+('Email verifikasi dikirim; periksa inbox/spam sebelum login.' if sent else 'Akun dibuat, tetapi email belum dapat dikirim. Tunggu satu menit lalu gunakan Kirim ulang verifikasi.')},201)
            async with _hash_slots:
                if action=='recover':
                    recovery=await asyncio.to_thread(vault.recover,body.get('email'),body.get('recovery_code'),body.get('password'))
                    return result({'ok':True,'recovery_code':recovery,'message':'Password diperbarui. Semua sesi/token dicabut. Simpan kode pemulihan baru.'})
                token=await asyncio.to_thread(vault.login,body.get('email'),body.get('password'))
            response=result({'ok':True})
            response.set_cookie(cookie_name(),token,max_age=43200,httponly=True,secure=os.getenv('ACCOUNTS_DEV_HTTP')!='1',samesite='lax',path='/')
            return response
        if not user: return result({'error':'login_required'},401)
        if not hmac.compare_digest(request.headers.get('x-csrf-token',''),vault.csrf(raw)): return result({'error':'csrf_rejected'},403)
        uid=user['id']
        if action=='logout':
            vault.logout(raw)
            response=result({'ok':True})
            response.delete_cookie(cookie_name(),path='/',secure=os.getenv('ACCOUNTS_DEV_HTTP')!='1',httponly=True,samesite='lax')
            return response
        if action=='credentials':
            service=body.get('service','bps')
            if body.get('delete') is True: vault.delete_key(uid,service)
            else:
                try: vault.save_key(uid,service,body.get('key'))
                except ValueError as error:
                    logger.info('Credential validation rejected user_ref=%s',digest(uid)[:12])
                    return result({'error':'invalid_api_key','message':str(error)},400)
            return result({'ok':True,'message':'Credential diperbarui.','credentials':vault.profile(uid)['credentials']})
        if action=='tokens':
            if body.get('revoke'):
                vault.revoke_token(uid,body['revoke'])
                return result({'ok':True})
            token=vault.create_token(uid,body.get('label'),body.get('days',30))
            return result({'ok':True,'token':token,'message':'Token hanya ditampilkan sekali. Simpan di pengaturan klien MCP.'},201)
        if action=='apps':
            from .oauth import OAuthStore
            store=OAuthStore(vault)
            if body.get('revoke'): store.revoke_app(uid,body['revoke'])
            return result({'apps':store.apps(uid)})
        if action=='password':
            async with _hash_slots: await asyncio.to_thread(vault.change_password,uid,body.get('old_password'),body.get('password'))
            return result({'ok':True,'message':'Password diganti; semua sesi dan token dicabut. Login kembali.'})
        return result({'error':'not_found'},404)
    except (ValueError,TypeError,TimeoutError) as error:
        return result({'error':str(error)},400)
    except Exception:
        return result({'error':'Layanan akun belum siap. Hubungi pengelola.'},503)


def resolve(vault, request, kind='mcp'):
    if kind=='session':
        raw=request.cookies.get(cookie_name(),'')
        user=vault.identity(raw)
    else:
        auth=request.headers.get('authorization','')
        raw=auth[7:] if auth.lower().startswith('bearer ') else ''
        user=vault.identity(raw,'mcp')
        if not user and raw.startswith('oat_') and request.url.path!='/internal/accounts/resolve':
            from .oauth import OAuthStore, origin
            resource=origin()+('/sse' if request.url.path=='/sse' or request.url.path.startswith('/messages') else '/mcp')
            user=OAuthStore(vault).identity(raw,resource)
    return {**user,'raw':raw,'kind':'oauth' if 'oauth_client' in user else kind} if user else None


async def resolve_internal(request):
    secret=os.getenv('ACCOUNTS_SERVICE_SECRET','')
    if len(secret)<32 or not hmac.compare_digest(request.headers.get('x-account-service-secret',''),secret): return result({'error':'unauthorized'},401)
    try:
        vault=get_vault()
        user=resolve(vault,request,'session' if request.headers.get('x-account-kind')=='session' else 'mcp')
        if not user: return result({'error':'unauthorized'},401)
        if user['kind']=='session' and not hmac.compare_digest(request.headers.get('x-csrf-token',''),vault.csrf(user['raw'])):
            return result({'error':'csrf_rejected'},403)
        return result({'id':user['id'],'bps':vault.get_key(user['id'],'bps'),'sdgs':vault.get_key(user['id'],'sdgs')})
    except Exception: return result({'error':'unavailable'},503)


class AccountMiddleware:
    def __init__(self,app): self.app=app
    async def __call__(self,scope,receive,send):
        if scope['type']!='http': return await self.app(scope,receive,send)
        path=scope['path']
        is_mcp=path=='/mcp' or path.startswith('/mcp/') or path=='/sse' or path.startswith('/messages')
        is_browser=path=='/api/bps'
        if not is_mcp and not is_browser: return await self.app(scope,receive,send)
        request=Request(scope,receive)
        if request.method=='OPTIONS': return await self.app(scope,receive,send)
        started=False
        try:
            vault=get_vault()
            user=resolve(vault,request,'session' if is_browser else 'mcp')
            if not user:
                response=result({'error':'unauthorized','message':'Login dan buat token MCP di dashboard.'},401)
                from .oauth import origin
                endpoint='sse' if path=='/sse' or path.startswith('/messages') else 'mcp'
                response.headers['WWW-Authenticate']='Bearer resource_metadata="'+origin()+'/.well-known/oauth-protected-resource/'+endpoint+'", scope="data:read"'
                return await response(scope,receive,send)
            if is_browser and (not origin_allowed(request) or not hmac.compare_digest(request.headers.get('x-csrf-token',''),vault.csrf(user['raw']))):
                return await result({'error':'csrf_rejected'},403)(scope,receive,send)
            if path.startswith('/messages'):
                sid=parse_qs(scope.get('query_string',b'').decode()).get('session_id',[''])[0]
                with vault.db() as db: owner=db.execute('SELECT user_id FROM sse_sessions WHERE hash=? AND expires>?',(digest(sid),int(time.time()))).fetchone()
                if not owner or owner[0]!=user['id']: return await result({'error':'session_owner_mismatch'},403)(scope,receive,send)
            if path.startswith('/mcp') and request.headers.get('mcp-session-id'):
                with vault.db() as db: owner=db.execute('SELECT user_id FROM sse_sessions WHERE hash=? AND expires>?',(digest('http:'+request.headers['mcp-session-id']),int(time.time()))).fetchone()
                if not owner or owner[0]!=user['id']: return await result({'error':'session_owner_mismatch'},403)(scope,receive,send)
            token=principal.set(user)
            async def checked_send(message):
                nonlocal started
                if message['type']=='http.response.start':
                    started=True
                    for name,value in message.get('headers',[]):
                        if name.lower()==b'mcp-session-id':
                            with vault.db() as db: db.execute('INSERT OR REPLACE INTO sse_sessions VALUES(?,?,?)',(digest('http:'+value.decode()),user['id'],int(time.time())+86400))
                if path=='/sse' and message['type']=='http.response.body':
                    for sid in re.findall(rb'session_id=([a-zA-Z0-9_-]+)',message.get('body',b'')):
                        with vault.db() as db:
                            db.execute('DELETE FROM sse_sessions WHERE expires<=?',(int(time.time()),))
                            db.execute('INSERT OR REPLACE INTO sse_sessions VALUES(?,?,?)',(digest(sid.decode()),user['id'],int(time.time())+86400))
                await send(message)
            try: await self.app(scope,receive,checked_send)
            finally: principal.reset(token)
        except Exception:
            if started: raise
            return await result({'error':'account_service_unavailable'},503)(scope,receive,send)


def install(app):
    from .oauth_http import oauth_routes
    app.routes[0:0]=oauth_routes()
    app.routes.insert(0,Route('/api/account/{action}',account_route,methods=['GET','POST']))
    app.routes.insert(0,Route('/internal/accounts/resolve',resolve_internal,methods=['POST']))
    app.add_middleware(AccountMiddleware)
    return app
