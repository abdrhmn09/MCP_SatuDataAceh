import rules from "../../src/comparison_rules.json";

export interface Comparability {
  status: "comparable" | "incomparable" | "unknown";
  reason: string;
}

export function compareIndicators(title: string, label: string, unitA = "", unitB = ""): Comparability {
  const a = title.toLowerCase(), b = label.toLowerCase();
  const reject = (reason: string): Comparability => ({ status: "incomparable", reason });
  const period=(s:string)=>/y-on-y|yoy|tahun ke tahun/.test(s)?'yoy':/m-to-m|mtm|bulan ke bulan|\bbulanan\b/.test(s)?'mom':/y-to-d|ytd|tahun kalender/.test(s)?'ytd':'';
  const conflicting=(s:string)=>[/y-on-y|yoy|tahun ke tahun/,/m-to-m|mtm|bulan ke bulan|\bbulanan\b/,/y-to-d|ytd|tahun kalender/].filter(pattern=>pattern.test(s)).length>1;
  if(conflicting(a) || conflicting(b)) return {status:'unknown',reason:'Konflik metadata frekuensi antara judul, label, atau kolom pengukuran.'};
  if(period(a) && period(b) && period(a)!==period(b)) return reject('Konsep inflasi tidak sepadan.');
  if(a.includes('inflasi') && /ihk|indeks harga konsumen/.test(b) || b.includes('inflasi') && /ihk|indeks harga konsumen/.test(a)) return reject('Indeks Harga Konsumen dan laju inflasi bukan ukuran yang sama.');
  const base=(s:string)=>s.match(/\b((?:19|20)\d{2})\s*=\s*100/)?.[1]||'';
  if(base(a) && base(b) && base(a)!==base(b)) return reject('Tahun dasar indeks tidak sepadan.');
  if(Boolean(period(a))!==Boolean(period(b)) || Boolean(base(a))!==Boolean(base(b))) return {status:'unknown',reason:'Metadata konsep periode atau tahun dasar belum lengkap.'};
  if (a.includes("nasional") !== b.includes("nasional") || a.includes("indonesia") !== b.includes("indonesia"))
    return reject("Cakupan wilayah berbeda.");
  const gender = (s: string) => /jenis kelamin|gender/.test(s);
  if (gender(a) !== gender(b)) return reject("Dimensi disagregasi berbeda.");
  const families = (s: string) => Object.entries(rules._INDICATOR_FAMILIES)
    .filter(([, terms]) => terms.some(term => s.includes(term))).map(([name]) => name);
  const fa = families(a), fb = families(b);
  if (fa.length && fb.length && !fa.some(f => fb.includes(f))) return reject("Indikator tidak sepadan.");
  for (const component of ["rata-rata lama sekolah", "rata rata lama sekolah", "harapan lama sekolah", "umur harapan hidup", "pengeluaran per kapita"])
    if ((a.includes(component) && fb.includes("ipm") && !b.includes(component)) ||
        (b.includes(component) && fa.includes("ipm") && !a.includes(component))) return reject("Komponen dan indeks komposit berbeda.");
  if (a.includes("paud") !== b.includes("paud")) return reject("Konsep indikator administratif berbeda.");
  const family = (s: string) => Object.entries(rules._UNIT_FAMILIES)
    .find(([, terms]) => terms.some(term => s.toLowerCase().includes(term)))?.[0] || "";
  const ua = family(unitA), ub = family(unitB);
  if (ua && ub && ua !== ub) return reject("Satuan tidak sepadan.");
  const scale = (s: string) => ["triliun", "miliar", "juta", "ribu"].find(term => s.toLowerCase().includes(term)) || "";
  if (ua === ub && ["rupiah", "jumlah"].includes(ua) && scale(unitA) !== scale(unitB)) return reject("Skala satuan tidak sepadan.");
  const mass = (s: string) => /kuintal|kwintal/.test(s) ? "kuintal" : /kilogram|kg/.test(s) ? "kg" : s.includes("ton") ? "ton" : "gram";
  if (ua === "massa" && ub === "massa" && mass(unitA.toLowerCase()) !== mass(unitB.toLowerCase())) return reject("Satuan massa tidak sepadan.");
  const dimension = (s: string) => /hektar|hectare/.test(s) ? "luas" : s.includes("rumah tangga") ? "rumah tangga" : /orang|jiwa/.test(s) ? "orang" : "unit";
  if (ua === "jumlah" && ub === "jumlah" && dimension(unitA.toLowerCase()) !== dimension(unitB.toLowerCase())) return reject("Dimensi satuan tidak sepadan.");
  if (a.includes("penduduk") && b.includes("penduduk") && /miskin|kemiskinan/.test(a) !== /miskin|kemiskinan/.test(b))
    return reject("Indikator tidak sepadan: penduduk total berbeda dari penduduk miskin.");
  if (/per\s*kapita|percapita/.test(a) !== /per\s*kapita|percapita/.test(b)) return reject("Dimensi per kapita berbeda.");
  const priceBasis = (s: string) => /adhk|harga konstan/.test(s) ? "konstan" : /adhb|harga berlaku/.test(s) ? "berlaku" : "";
  if (priceBasis(a) && priceBasis(b) && priceBasis(a) !== priceBasis(b)) return reject("Basis harga tidak sepadan (ADHB vs ADHK).");
  const measure = (s: string) => /kontribusi|pangsa|peranan|share/.test(s) ? "kontribusi" : /pertumbuhan|growth/.test(s) ? "pertumbuhan" : /indeks|ihk/.test(s) ? "indeks" : /persentase|tingkat/.test(s) ? "persentase" : "";
  if (measure(a) && measure(b) && measure(a) !== measure(b)) return reject("Jenis ukuran tidak sepadan.");
  if (!ua || !ub || !fa.length || !fb.length) return { status: "unknown", reason: "Metadata indikator atau satuan belum cukup untuk memastikan kesepadanan." };
  return { status: "comparable", reason: "Konsep dan satuan sesuai; cocokkan wilayah, kategori, dan periode observasi sebelum membandingkan angka." };
}
