/** Cloudflare is a stateless gateway to the canonical Python account vault. */
import { isPublicHttpsUrl } from './http';
export interface AccountEnv { ACCOUNTS_SERVICE_URL?: string; ACCOUNTS_SERVICE_SECRET?: string }
async function readLimited(body: ReadableStream<Uint8Array> | null, limit: number) {
  const reader=body?.getReader();
  if(!reader) return '';
  let size=0,text='';const decoder=new TextDecoder();
  try { while(true) { const chunk=await reader.read();if(chunk.done)break;size+=chunk.value.byteLength;if(size>limit)throw new Error('Body too large');text+=decoder.decode(chunk.value,{stream:true}); }return text+decoder.decode(); }
  finally {await reader.cancel().catch(()=>{});}
}
function service(env: AccountEnv) {
  const value=env.ACCOUNTS_SERVICE_URL || '';
  const url=new URL(value);
  if (!isPublicHttpsUrl(value) || url.pathname !== '/' || url.search || url.hash || !env.ACCOUNTS_SERVICE_SECRET || env.ACCOUNTS_SERVICE_SECRET.length < 32) throw new Error('Account service not configured');
  return url.origin;
}
export async function resolveAccount(request:Request,env:AccountEnv,kind:'mcp'|'session'='mcp') {
  const root=service(env);
  const headers=new Headers({'X-Account-Service-Secret':env.ACCOUNTS_SERVICE_SECRET!, 'X-Account-Kind':kind});
  if(kind==='session') {
    if(request.headers.get('origin')!==new URL(request.url).origin) throw new Error('Invalid origin');
    headers.set('Cookie',request.headers.get('cookie')||'');
    // The vault checks this session's CSRF value before disclosing credentials.
    headers.set('X-CSRF-Token',request.headers.get('X-CSRF-Token')||'');
  } else headers.set('Authorization',request.headers.get('Authorization')||'');
  const r=await fetch(root+'/internal/accounts/resolve',{method:'POST',headers,redirect:'error',signal:AbortSignal.timeout(10000)});
  if(!r.ok) return null;
  const text=await readLimited(r.body,4096);
  if(text.length>4096) throw new Error('Invalid account service response');
  const user=JSON.parse(text) as {id:string;bps:string;sdgs:string};
  if(typeof user.id!=='string'||typeof user.bps!=='string'||typeof user.sdgs!=='string') throw new Error('Invalid account service response');
  return user;
}
export async function proxyAccount(request:Request,env:AccountEnv) {
  const root=service(env), incoming=new URL(request.url);
  if(root===incoming.origin) throw new Error('Account service must point to the canonical Python origin');
  if(!/^\/api\/account\/(config|register|login|recover|resend|verify|me|logout|credentials|tokens|password)$/.test(incoming.pathname)) return new Response('Not found',{status:404});
  if(request.method!=='GET' && request.headers.get('origin')!==incoming.origin) return Response.json({error:'origin_rejected'},{status:403});
  const headers=new Headers({'X-Account-Service-Secret':env.ACCOUNTS_SERVICE_SECRET!, 'X-Account-Client-IP':request.headers.get('CF-Connecting-IP')||'worker'});
  for(const name of ['cookie','origin','content-type','x-csrf-token']) { const value=request.headers.get(name);if(value)headers.set(name,value); }
  // The canonical service must explicitly allow the Worker's public origin.
  const body=request.method==='GET'?undefined:await readLimited(request.body,8192);
  if(body && body.length>8192) return Response.json({error:'body_too_large'},{status:413});
  const response=await fetch(root+incoming.pathname,{method:request.method,headers,body,redirect:'error',signal:AbortSignal.timeout(15000)});
  return new Response(response.body,{status:response.status,headers:response.headers});
}
