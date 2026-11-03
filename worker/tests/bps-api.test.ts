import { afterEach, expect, it, vi } from "vitest";
import { buildRequest, credential, executeBps, operations } from "../src/bps-api";
import worker, { type Env } from "../src/index";
afterEach(()=>vi.unstubAllGlobals());
it("builds all 59 documented operations on the official host",()=>{
  expect(Object.keys(operations)).toHaveLength(59);
  for(const [name, spec] of Object.entries(operations)) {
    const parameters: Record<string, unknown>={};
    for(const p of spec.parameters) if(p.required) parameters[p.name]=p.schema.enum?.[0]??(p.schema.type==='integer'?1:['parent','wilayah'].includes(p.name)?'1100000':p.name==='tahun'?'2024':p.name==='domain'?'1100':p.name==='lang'?'ind':'1');
    const r=buildRequest(name,parameters,'user-key-1234');
    expect(new URL(r.url).hostname).toBe('webapi.bps.go.id');
    expect(r.url).not.toContain('{'); expect(r.publicUrl).not.toContain('user-key-1234');
    expect(Object.keys(r.headers).length>0).toBe(spec.credential==='sdgs');
  }
});
it("prioritizes visitor credentials and does not fallback on invalid keys",()=>{
 expect(credential(new Headers({'Authorization':'Bearer visitor-key-1234'}),'operator-key')).toBe('visitor-key-1234');
 expect(()=>credential(new Headers({'X-BPS-API-Key':''}),'operator-key')).toThrow();
 expect(()=>credential(new Headers({'Authorization':'Basic invalid'}),'operator-key')).toThrow();
});
it("rejects unlisted operations, parameters and path injection",()=>{
 for(const [operation,parameters] of [['unknown',{}],['listDomains',{type:'all',key:'evil'}],['listVariables',{domain:'1100',page:0}],['listVariables',{domain:'../localhost'}],['listDomains',{type:'kabbyprov'}]] as [string,Record<string,unknown>][]) expect(()=>buildRequest(operation,parameters,'user-key-1234')).toThrow();
});
it("isolates keys and sanitizes upstream credential echoes",async()=>{
 const urls:string[]=[];
 vi.stubGlobal('fetch',vi.fn(async(url:string)=>{urls.push(url);return new Response(JSON.stringify({status:'OK',data:[{link:url}]}));}));
 for(const key of ['alice-key-1234','bob-key-567890']) {
  const result=await executeBps('listDomains',{type:'all'},new Headers({'X-BPS-API-Key':key}),'operator-key');
  expect(result.ok).toBe(true);expect(JSON.stringify(result)).not.toContain(key);
 }
 expect(urls[0]).toContain('alice-key-1234');expect(urls[1]).not.toContain('alice-key-1234');
});
it("passes SDGs Token in a header",async()=>{
 const upstream=vi.fn(async()=>new Response('{"data":{"attributes":{"status":"active"}}'));
 vi.stubGlobal('fetch',upstream);
 await executeBps('getSdgsHome',{},new Headers({'X-BPS-SDGS-Token':'sdgs-token-1234'}));
 expect((upstream.mock.calls as unknown as [string,RequestInit][])[0][1].headers).toMatchObject({Token:'sdgs-token-1234'});
});
it("browser API never borrows operator credentials",async()=>{
 const upstream=vi.fn();vi.stubGlobal('fetch',upstream);
 const env:Env={CATALOG_URL:'https://example.com',DATA_YEAR:'2025',CATALOG_TTL_SECONDS:'60',MAX_REQUESTS_PER_MINUTE:'60',BPS_API_KEY:'operator-key'};
 const result=await worker.fetch(new Request('https://example.com/api/bps',{method:'POST',body:JSON.stringify({operation:'listDomains',parameters:{type:'all'}})}),env);
 expect(result.status).toBe(400);expect(upstream).not.toHaveBeenCalled();
});

it("MCP HTTP uses each visitor's header without changing the operator environment", async()=>{
 const {Client}=await import('@modelcontextprotocol/sdk/client/index.js');
 const {StreamableHTTPClientTransport}=await import('@modelcontextprotocol/sdk/client/streamableHttp.js');
 const urls:string[]=[];
 vi.stubGlobal('fetch',vi.fn(async(url:string)=>{urls.push(url); return new Response('{"status":"OK","data":[{"domain_id":"1100"}]}');}));
 const env:Env={CATALOG_URL:'https://example.com',DATA_YEAR:'2025',CATALOG_TTL_SECONDS:'60',MAX_REQUESTS_PER_MINUTE:'60',BPS_API_KEY:'operator-key'};
 for(const key of ['visitor-one-key','visitor-two-key']) {
  const client=new Client({name:'credential-test',version:'1'});
  const transport=new StreamableHTTPClientTransport(new URL('https://example.com/mcp'),{
   requestInit:{headers:{Authorization:`Bearer ${key}`}},
   fetch:async(input,init)=>worker.fetch(new Request(input,init),env),
  });
  await client.connect(transport);
  try {
   const result=await client.callTool({name:'bps_request',arguments:{operation:'listDomains',parameters:{type:'all'}}});
   expect(result.isError).not.toBe(true);
   expect((result.structuredContent as {ok:boolean}).ok).toBe(true);
   expect(JSON.stringify(result)).not.toContain(key);
  } finally {await client.close();}
 }
 expect(urls[0]).toContain('visitor-one-key');expect(urls[1]).toContain('visitor-two-key');
 expect(env.BPS_API_KEY).toBe('operator-key');
});
