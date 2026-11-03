import {afterEach,expect,it,vi} from 'vitest';
import {proxyAccount,resolveAccount} from '../src/accounts';
const env={ACCOUNTS_SERVICE_URL:'https://accounts.example.com',ACCOUNTS_SERVICE_SECRET:'test-service-secret-of-at-least-32-chars'};
afterEach(()=>vi.unstubAllGlobals());
it('fails closed without a trusted account service',async()=>{
 await expect(resolveAccount(new Request('https://worker.test/mcp'),{})).rejects.toThrow();
 await expect(resolveAccount(new Request('https://worker.test/mcp'),{...env,ACCOUNTS_SERVICE_URL:'http://localhost/'})).rejects.toThrow();
});
it('does not treat a raw BPS key as a valid account token',async()=>{
 vi.stubGlobal('fetch',vi.fn(async()=>new Response('',{status:401})));
 expect(await resolveAccount(new Request('https://worker.test/mcp',{headers:{Authorization:'Bearer old-bps-key'}}),env)).toBeNull();
});
it('resolves cookies only with same-origin and a forwarded CSRF token',async()=>{
 const upstream=vi.fn(async(_url:string,_init:RequestInit)=>Response.json({id:'user-id',bps:'saved-key-value',sdgs:''}));vi.stubGlobal('fetch',upstream);
 await expect(resolveAccount(new Request('https://worker.test/api/bps',{headers:{Origin:'https://evil.test'}}),env,'session')).rejects.toThrow();
 const user=await resolveAccount(new Request('https://worker.test/api/bps',{headers:{Origin:'https://worker.test',Cookie:'__Host-mcp_session=test-session', 'X-CSRF-Token':'csrf-test'}}),env,'session');
 expect(user?.id).toBe('user-id');
 const headers=new Headers(upstream.mock.calls[0]?.[1]?.headers);
 expect(headers.get('X-CSRF-Token')).toBe('csrf-test');
 expect(headers.get('X-Account-Service-Secret')).toBe(env.ACCOUNTS_SERVICE_SECRET);
});
it('rejects cross-origin account changes and self-recursive service config',async()=>{
 expect((await proxyAccount(new Request('https://worker.test/api/account/login',{method:'POST',headers:{Origin:'https://evil.test'}}),env)).status).toBe(403);
 await expect(proxyAccount(new Request('https://accounts.example.com/api/account/me'),env)).rejects.toThrow();
});
