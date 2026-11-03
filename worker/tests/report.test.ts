import {afterEach,expect,it,vi} from 'vitest';
import {Client} from '@modelcontextprotocol/sdk/client/index.js';
import {InMemoryTransport} from '@modelcontextprotocol/sdk/inMemory.js';
import {analyzeCsvText,createServer,searchCatalog,type Env} from '../src/index';
import {auditCoverage} from '../src/data-quality';
import {credential,endpointCatalog} from '../src/bps-api';

afterEach(()=>vi.unstubAllGlobals());

it('preserves nulls, hides empty admin columns and excludes missing latest values',()=>{
 const result=analyzeCsvText('tahun,bps_nama_kabupaten_kota,admin,nilai,satuan\n2025,Banda Aceh,,2.5,Persen\n2026,Banda Aceh,,NaN,Persen\n2025,Sabang,,0,Persen\n',2);
 expect(result.data?.rows[1].nilai).toBeNull();
 expect(result.data?.rows[0].admin).toBeNull();
 expect(result.data?.truncated).toBe(true);
 expect(result.quality?.finite_value_count).toBe(2);
 expect(result.quality?.latest_value_year).toBe('2025');
 expect(result.preview).not.toMatch(/nan|admin/i);
 expect(JSON.stringify(result.data)).not.toContain('NaN');
});

it('does not assume region or subperiod equivalence',()=>{
 const csv=(region='Banda Aceh',month='September',year=2025)=>analyzeCsvText(`nama_wilayah,tahun,periode,nilai,satuan\n${region},${year},${month},2,Persen\n`,20);
 for(const other of [csv('Sabang'),csv('Banda Aceh','Maret'),csv('Banda Aceh','September',2024)]) expect(auditCoverage(csv(),other).ok).toBe(false);
 expect(auditCoverage(csv(),csv()).ok).toBe(true);
});

it('explains catalog-only geographic filters and isolates SDGs credentials',()=>{
 const result=searchCatalog([{identifier:'inflasi',title:'Inflasi Aceh'}],'inflasi','Banda Aceh');
 expect(result.total).toBe(0);
 expect(result.filter_scope).toBe('catalog_metadata');
 expect(result.filter_note).toContain('bukan seluruh baris CSV');
 expect(()=>credential(new Headers({'X-BPS-API-Key':'personal-bps-key'}),'','sdgs')).toThrow();
 expect(endpointCatalog('domain')).toMatchObject({ok:false,error:'unknown_operation',suggestions:['listDomains']});
});

it('returns structured unknown operations and enforces the advertised CSV row limit through MCP',async()=>{
 const env:Env={CATALOG_URL:'https://example.com/report-catalog.json',DATA_YEAR:'2025',CATALOG_TTL_SECONDS:'60',MAX_REQUESTS_PER_MINUTE:'100'};
 const upstream=vi.fn();vi.stubGlobal('fetch',upstream);
 const server=createServer(env,'report-client'),client=new Client({name:'report-test',version:'1'});
 const [a,b]=InMemoryTransport.createLinkedPair();await server.connect(b);await client.connect(a);
 try {
  const unknown=await client.callTool({name:'bps_endpoints',arguments:{operation:'domain'}});
  expect(unknown.isError).not.toBe(true);
  expect(unknown.structuredContent).toMatchObject({ok:false,error:'unknown_operation'});
  const invalid=await client.callTool({name:'baca_isi_csv',arguments:{url:'https://example.com/data.csv',baris_maksimal:60}});
  expect(invalid.isError).toBe(true);
  expect(upstream).not.toHaveBeenCalled();
 } finally {await client.close();await server.close();}
});
