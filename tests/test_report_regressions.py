"""Reproduce the ChatGPT Web report with synthetic, semantically distinct observations."""
import json
import unittest
from unittest.mock import AsyncMock, patch

from src import bps_api, server
from src.bps import bps_payload_ke_csv
from src.bps_periods import discover_periods
from src.data_quality import audit_coverage

URL='https://example.com/data.csv'


class ReportTests(unittest.IsolatedAsyncioTestCase):
    async def test_unknown_operation_is_structured_even_through_sdk(self):
        with patch.object(server._rate_limiter,'allow',AsyncMock(return_value=True)):
            result=await server.mcp.call_tool('bps_endpoints',{'operation':'domain'})
            data=result.structured_content
            self.assertFalse(result.is_error)
            self.assertFalse(data['ok'])
            self.assertEqual(data['error'],'unknown_operation')
            self.assertIn('listDomains',data['valid_operations'])
            self.assertIn('listDomains',data['suggestions'])
            request=await server.bps_request('not-a-real-operation',{})
            self.assertEqual(request['error'],'unknown_operation')

    async def test_csv_row_limit_rejects_instead_of_silently_clamping(self):
        download=AsyncMock()
        with patch.object(server,'_unduh_csv',download):
            for limit in (0,60,-1,True):
                message=await server.baca_isi_csv(URL,limit)
                self.assertIn('antara 1 dan 50',message)
            download.assert_not_awaited()
        spec=next(tool for tool in await server.mcp.list_tools() if tool.name=='baca_isi_csv')
        self.assertEqual(spec.input_schema['properties']['baris_maksimal']['maximum'],50)

    async def test_missing_cells_are_null_and_not_selected_as_indicator(self):
        csv='tahun,bps_nama_kabupaten_kota,kode_kosong,inflasi,satuan\n2025,Banda Aceh,,2.5,Persen\n2026,Banda Aceh,,NaN,Persen\n2025,Sabang,,0,Persen\n'
        result=server._analisis_csv(csv,URL,2)
        self.assertEqual(result.kolom_indikator,'inflasi')
        self.assertNotIn('nan',result.preview.lower())
        self.assertEqual(result.data['rows'][1]['inflasi'],None)
        self.assertEqual(result.data['rows'][0]['kode_kosong'],None)
        self.assertEqual(result.quality['finite_value_count'],2)
        self.assertEqual(result.quality['latest_value_year'],'2025')
        self.assertEqual(result.quality['missing_value_count'],1)
        self.assertTrue(result.data['truncated'])
        json.dumps(result.data,allow_nan=False)

    async def test_fetch_contains_structured_rows_and_keeps_original_source(self):
        item={'identifier':'inflasi','title':'Inflasi Aceh','landingPage':URL}
        data=server._analisis_csv('tahun,nilai\n2025,1.2\n2026,\n',URL,50)
        with patch.object(server,'muat_katalog',AsyncMock(return_value=[item])),patch.object(server,'_unduh_csv',AsyncMock(return_value=data)):
            result=await server.fetch('inflasi')
        self.assertEqual(result.data['rows'][1]['nilai'],None)
        self.assertEqual(result.metadata['source'],'Satu Data Aceh')
        self.assertEqual(result.metadata['quality']['latest_value_year'],'2025')

    async def test_search_empty_metadata_filter_is_not_claim_of_absent_data(self):
        item={'identifier':'inflasi','title':'Inflasi Aceh'}
        with patch.object(server,'muat_katalog',AsyncMock(return_value=[item])):
            result=await server.search('inflasi',wilayah='Banda Aceh')
        self.assertEqual(result.total,0)
        self.assertEqual(result.filter_scope,'catalog_metadata')
        self.assertIn('bukan seluruh baris CSV',result.filter_note)

    async def test_observation_audit_rejects_region_period_and_year_mismatch(self):
        def csv(region='Banda Aceh',period='September',year='2025'):
            return server._analisis_csv(f'nama_wilayah,tahun,periode,nilai,satuan\n{region},{year},{period},2,Persen\n',URL,20)
        a=csv()
        for b in (csv(region='Sabang'),csv(period='Maret'),csv(year='2024')):
            self.assertFalse(audit_coverage(a,b)[0])
        self.assertTrue(audit_coverage(a,csv())[0])
        empty_value=server._analisis_csv('nama_wilayah,tahun,nilai\nBanda Aceh,2025,\n',URL,20)
        self.assertFalse(audit_coverage(a,empty_value)[0])

    async def test_single_month_and_category_are_not_discarded_from_bps(self):
        payload={'var':[{'val':1,'label':'Inflasi','unit':'Persen'}],'vervar':[{'val':1171,'label':'Banda Aceh'}],'tahun':[{'val':125,'label':'2025'}],'turvar':[{'val':2,'label':'Pangan'}],'turtahun':[{'val':9,'label':'September'}],'datacontent':{'1171121259':2}}
        csv=bps_payload_ke_csv(payload)
        self.assertIn('September',csv)
        self.assertIn('Pangan',csv)

    async def test_period_discovery_marks_partial_and_uses_ids_not_year_arithmetic(self):
        calls=[]
        async def read(url,headers):
            calls.append(url)
            page=int(url.rsplit('page=',1)[1])
            return {'status':'OK','data':[{'pages':8},[{'th_id':900+page,'th':str(2018+page)}]]}
        ids,report=await discover_periods(read,'1100','564','synthetic-key')
        self.assertEqual(ids[0],'908')
        self.assertEqual(report['pages_checked'],[1,8,7])
        self.assertFalse(report['metadata_complete'])
        self.assertEqual(report['status'],'partial_metadata')
        self.assertNotIn('synthetic-key',json.dumps(report))

    async def test_audit_never_elects_a_source_based_on_maximum_year(self):
        item={'identifier':'e8c8605b-5ce1-4637-be23-9108837e89c9','title':'Inflasi tahun ke tahun Aceh','landingPage':URL}
        sda=server._analisis_csv('nama_wilayah,tahun,nilai,satuan\nBanda Aceh,2025,2,Persen\n',URL,20)
        bps=server._analisis_csv('nama_wilayah,tahun,nilai,satuan\nSabang,2024,3,Persen\n',URL,20)
        bps.indikator_bps='Inflasi tahun ke tahun Aceh'
        with patch.object(server,'muat_katalog',AsyncMock(return_value=[item])),patch.object(server,'_unduh_csv',AsyncMock(return_value=sda)),patch.object(server,'_ambil_langsung_dari_bps',AsyncMock(return_value=(bps,URL))):
            result=await server.bandingkan_data('inflasi')
        self.assertIn('tidak ada sumber utama yang dipilih otomatis',result)
        self.assertNotIn('referensi utama',result)
        self.assertIn('Kesepadanan observasi belum dapat dipastikan',result)

    async def test_sdgs_does_not_inherit_bps_key_and_checks_only_one_operation(self):
        with self.assertRaises(ValueError):bps_api.credential({'x-bps-api-key':'bps-key-1234'},service='sdgs')
        with patch.object(server,'bps_request',AsyncMock(return_value={'ok':True})) as request:
            result=await server.bps_check_key('sdgs')
        self.assertEqual(request.call_args.args[0],'listSdgsGoals')
        self.assertEqual(result['verification_scope'],'single_endpoint')
