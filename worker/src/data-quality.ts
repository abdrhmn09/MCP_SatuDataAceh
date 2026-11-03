const missing = new Set(['','nan','null','none','na','n/a','-','...','inf','-inf','+inf','infinity','-infinity']);
export const cleanCell = (value:string):string|null => missing.has(value.trim().toLowerCase()) ? null : value;
const numeric = (value:string|null):boolean => value !== null && /^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$/.test(value.trim()) && Number.isFinite(Number(value));
export interface Coverage { column:string|null; values:string[]; complete:boolean; missing_rows?:number }
export interface Quality { missing_by_column:Record<string,number>; missing_cells:number; value_column:string|null; finite_value_count:number; missing_value_count:number|null; non_numeric_value_count:number|null; latest_value_year:string|null }
export interface StructuredCsv { columns:string[]; rows:Record<string,string|number|null>[]; returned_rows:number; total_rows:number; truncated:boolean }

export function summarizeCsv(input:string[][],limit:number) {
  const columns=input[0], header=columns.map(s=>s.trim().toLowerCase()), rows=input.slice(1).map(row=>row.map(cleanCell));
  const ignored=new Set(['id','uuid','tahun','thn','year','th','periode','waktu','kode','bps_kode','kemendagri_kode','tingkat_penyajian','nama_wilayah','kode_wilayah','kategori','label','satuan','unit']);
  const candidates=header.flatMap((name,i)=>!ignored.has(name) && !/^(?:kode_|bps_kode_|kemendagri_kode_|nama_|bps_nama_|kemendagri_nama_)/.test(name) && rows.some(row=>row[i]!==null) && rows.every(row=>row[i]===null || numeric(row[i])) ? [i] : []);
  const preferred=header.flatMap((name,i)=>['nilai','value'].includes(name)?[i]:[]);
  const valueIndex=preferred.length===1?preferred[0]:candidates.length===1?candidates[0]:-1;
  const finite=rows.filter(row=>valueIndex>=0 && numeric(row[valueIndex]));
  const year=header.findIndex(s=>['tahun','thn','year','th','periode','waktu'].includes(s));
  const years=year<0?[]:finite.flatMap(row=>row[year]?.match(/\b(?:19|20)\d{2}\b/)?.[0] || []).sort();
  const counts=Object.fromEntries(columns.map((col,i)=>[col,rows.filter(row=>row[i]===null).length]));
  const quality:Quality={missing_by_column:counts,missing_cells:Object.values(counts).reduce((a,b)=>a+b,0),value_column:columns[valueIndex]||null,finite_value_count:finite.length,missing_value_count:valueIndex>=0?counts[columns[valueIndex]]:null,non_numeric_value_count:valueIndex>=0?rows.filter(row=>row[valueIndex]!==null && !numeric(row[valueIndex])).length:null,latest_value_year:years.at(-1)||null};
  const aliases:Record<string,string[]>={regions:['nama_wilayah','bps_nama_kabupaten_kota','kemendagri_nama_kabupaten_kota','nama_kabupaten_kota','kabupaten_kota','wilayah','bps_nama_provinsi','nama_provinsi'],periods:['periode','bulan','triwulan','semester'],categories:['kategori','jenis_kelamin','jenis kelamin']};
  const coverage:Record<string,Coverage>={};
  const uniqueYears=[...new Set(years)];
  coverage.years={column:columns[year]||null,values:uniqueYears.slice(0,100),complete:uniqueYears.length<=100};
  for(const [dimension,names] of Object.entries(aliases)) {
    const candidates=names.map(name=>header.indexOf(name)).filter(i=>i>=0);
    const col=candidates.find(i=>finite.some(row=>row[i]!==null))??candidates[0]??-1;
    const values=col<0?[]:[...new Set(finite.flatMap(row=>row[col]===null?[]:[row[col]!.trim().toLowerCase()]))].sort();
    const missingRows=col<0?0:finite.filter(row=>row[col]===null).length;
    coverage[dimension]={column:columns[col]||null,values:values.slice(0,100),complete:values.length<=100 && missingRows===0,missing_rows:missingRows};
  }
  const data:StructuredCsv={columns,rows:rows.slice(0,limit).map(row=>Object.fromEntries(columns.map((col,i)=>[col,i===valueIndex && numeric(row[i])?Number(row[i]):row[i]]))),returned_rows:Math.min(rows.length,limit),total_rows:rows.length,truncated:rows.length>limit};
  return {data,quality,coverage};
}

export function auditCoverage(a?:{quality?:Quality;coverage?:Record<string,Coverage>},b?:{quality?:Quality;coverage?:Record<string,Coverage>}) {
  if(!a?.quality?.finite_value_count || !b?.quality?.finite_value_count) return {ok:false,reason:'Metadata atau nilai indikator numerik belum cukup untuk menilai observasi.'};
  for(const dimension of ['regions','years','periods','categories']) {
    const left=a.coverage?.[dimension],right=b.coverage?.[dimension];
    if(!left?.complete || !right?.complete || ['regions','years'].includes(dimension) && (!left.values.length || !right.values.length)) return {ok:false,reason:'Cakupan wilayah atau dimensi observasi belum dapat dipastikan.'};
    if(JSON.stringify(left.values)!==JSON.stringify(right.values)) return {ok:false,reason:`Cakupan ${dimension} berbeda atau belum lengkap; angka tidak dibandingkan langsung.`};
  }
  return {ok:true,reason:'Pemeriksaan cakupan awal sesuai; kesamaan angka dan metodologi belum dibuktikan.'};
}
