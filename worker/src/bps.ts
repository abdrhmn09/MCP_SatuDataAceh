/**
 * BPS Aceh variable mapping dan parser respons Web API BPS untuk Cloudflare Worker.
 */

export interface BpsIndicator {
  var: string;
  label: string;
  category: string;
}

export interface BpsKeywordMatch {
  var: string;
  label: string;
}

export interface BpsDiagnosticResult {
  ok: boolean;
  message: string;
  dataAvailable: boolean;
}

export const BPS_INDICATOR_MAP: Record<string, BpsIndicator> = {
  // ── Kemiskinan ──────────────────────────────────────────────────────────
  "0116d97b-1b4a-4c6a-a243-33833660fb85": {
    var: "621",
    label: "Persentase Penduduk Miskin Aceh Menurut Kabupaten/Kota",
    category: "kemiskinan",
  },
  "afefeee7-2dbb-4ab8-aa2c-71610fc5fdb6": {
    var: "2212",
    label: "Persentase Penduduk Miskin Ekstrem",
    category: "kemiskinan",
  },
  // ── Pembangunan Manusia & Pendidikan ─────────────────────────────────────
  "78794e4b-2bbe-45ef-abd1-0a65c2e98702": {
    var: "498",
    label: "Indeks Pembangunan Manusia (IPM)",
    category: "ipm",
  },
  "2414165c-27b1-41a1-8229-0a51a128636d": {
    var: "498",
    label: "IPM Berdasarkan Jenis Kelamin",
    category: "ipm",
  },
  "f2585d70-70d1-49f9-8c78-6750a46e1780": {
    var: "490",
    label: "Rata-rata Lama Sekolah Provinsi Aceh Menurut Kabupaten/Kota",
    category: "pendidikan",
  },
  "6cab69b8-d936-4f8a-b5a1-ea1fb45589e9": {
    var: "490",
    label: "Indikator Pendidikan / Rata-rata Lama Sekolah",
    category: "pendidikan",
  },
  // ── Ketenagakerjaan ─────────────────────────────────────────────────────
  "97e549de-0a20-452a-9948-455abe2532a8": {
    var: "529",
    label: "Tingkat Pengangguran Terbuka (TPT)",
    category: "ketenagakerjaan",
  },
  // ── Ekonomi & PDRB ─────────────────────────────────────────────────────
  "22d3b2b0-8c0e-46cb-915d-7780fd4e1158": {
    var: "199",
    label: "Laju Pertumbuhan Ekonomi Aceh",
    category: "pdrb",
  },
  "95ceff6a-c0d9-4ef5-b6cb-86eee4764833": {
    var: "786",
    label: "PDRB Per Kapita Provinsi Aceh",
    category: "pdrb",
  },
  "bfe0cc05-78ff-46f2-9329-c943863e5c50": {
    var: "199",
    label: "Kontribusi Sektor Perikanan Terhadap PDRB",
    category: "pdrb",
  },
  // ── Harga & Inflasi ─────────────────────────────────────────────────────
  "e8c8605b-5ce1-4637-be23-9108837e89c9": {
    var: "1400",
    label: "Tingkat Inflasi Tahun ke Tahun Provinsi Aceh",
    category: "inflasi",
  },
  // ── Ketimpangan ─────────────────────────────────────────────────────────
  "0c63d096-1671-4afd-94b5-39048d378e56": {
    var: "631",
    label: "Rasio Gini Provinsi Aceh",
    category: "ketimpangan",
  },
  // ── Gizi & Kesehatan ────────────────────────────────────────────────────
  "1d4d7e1a-9d53-45a4-a11e-dc24d6c8cf25": {
    var: "2212",
    label: "Prevalensi Stunting Balita Aceh",
    category: "kesehatan",
  },
  "81dc3ba5-e050-47fe-846b-298ca2977216": {
    var: "529",
    label: "Persentase Fasyankes yang Terpenuhi SDM Kesehatan",
    category: "kesehatan",
  },
  // ── Pertanian Tanaman Pangan ────────────────────────────────────────────
  "d8c8a7f0-d329-4872-8546-294fd6267c7b": {
    var: "1321",
    label: "Produksi Padi Menurut Kabupaten/Kota",
    category: "pertanian",
  },
  // ── Hortikultura ────────────────────────────────────────────────────────
  "21cece89-360f-480d-a3e9-a841a79e752d": {
    var: "1350",
    label: "Produksi Tanaman Sayur-Sayuran Menurut Jenis dan Kabupaten/Kota",
    category: "hortikultura",
  },
  // ── Peternakan ──────────────────────────────────────────────────────────
  "9d11046b-a61b-4169-bf20-b691483162ba": {
    var: "1375",
    label: "Jumlah Potong Hewan Menurut Jenis Ternak",
    category: "peternakan",
  },
  // ── Perikanan ───────────────────────────────────────────────────────────
  "3f92d70a-8533-4f25-bc9f-332b7a4c8b84": {
    var: "1398",
    label: "Produksi Perikanan Tangkap di Perairan Darat",
    category: "perikanan",
  },
};

export const BPS_KEYWORD_TO_VAR: Record<string, BpsKeywordMatch> = {
  // Pendidikan
  pendidikan: { var: "490", label: "Rata-rata Lama Sekolah (RLS)" },
  sekolah: { var: "490", label: "Rata-rata Lama Sekolah (RLS)" },
  guru: { var: "490", label: "Indikator Pendidikan / RLS" },
  murid: { var: "490", label: "Indikator Pendidikan / RLS" },
  siswa: { var: "490", label: "Indikator Pendidikan / RLS" },
  "lama sekolah": { var: "490", label: "Rata-rata Lama Sekolah" },
  "rata-rata lama sekolah": { var: "490", label: "Rata-rata Lama Sekolah" },
  "harapan lama sekolah": { var: "495", label: "Harapan Lama Sekolah" },
  rls: { var: "490", label: "Rata-rata Lama Sekolah" },
  hls: { var: "495", label: "Harapan Lama Sekolah" },
  aps: { var: "490", label: "Angka Partisipasi Sekolah" },
  "angka partisipasi sekolah": { var: "490", label: "Angka Partisipasi Sekolah" },
  apm: { var: "490", label: "Angka Partisipasi Murni" },
  apk: { var: "490", label: "Angka Partisipasi Kasar" },

  // Kemiskinan
  kemiskinan: { var: "621", label: "Persentase Penduduk Miskin" },
  miskin: { var: "621", label: "Persentase Penduduk Miskin" },
  "kemiskinan ekstrem": { var: "2212", label: "Persentase Kemiskinan Ekstrem" },
  "garis kemiskinan": { var: "622", label: "Garis Kemiskinan" },

  // IPM
  ipm: { var: "498", label: "Indeks Pembangunan Manusia" },
  "pembangunan manusia": { var: "498", label: "Indeks Pembangunan Manusia" },

  // Ketenagakerjaan
  pengangguran: { var: "529", label: "Tingkat Pengangguran Terbuka" },
  tpt: { var: "529", label: "Tingkat Pengangguran Terbuka" },
  "angkatan kerja": { var: "527", label: "Angkatan Kerja" },

  // Ekonomi
  pdrb: { var: "786", label: "PDRB Per Kapita" },
  "pertumbuhan ekonomi": { var: "199", label: "Laju Pertumbuhan Ekonomi" },
  "laju pertumbuhan": { var: "199", label: "Laju Pertumbuhan Ekonomi" },

  // Inflasi & Harga
  inflasi: { var: "1400", label: "Laju Inflasi" },
  ihn: { var: "1400", label: "Indeks Harga Nasional" },

  // Ketimpangan
  gini: { var: "631", label: "Rasio Gini" },
  "rasio gini": { var: "631", label: "Rasio Gini" },

  // Pertanian
  padi: { var: "1321", label: "Produksi Padi" },
  jagung: { var: "1323", label: "Produksi Jagung" },
  kedelai: { var: "1325", label: "Produksi Kedelai" },
  sayur: { var: "1350", label: "Produksi Sayuran" },
  hortikultura: { var: "1350", label: "Produksi Hortikultura" },

  // Peternakan
  ternak: { var: "1375", label: "Populasi Ternak" },
  sapi: { var: "1377", label: "Populasi Sapi" },
  ayam: { var: "1379", label: "Populasi Ayam" },

  // Perikanan
  perikanan: { var: "1398", label: "Produksi Perikanan" },
  ikan: { var: "1398", label: "Produksi Perikanan" },

  // Kesehatan
  stunting: { var: "2212", label: "Prevalensi Stunting" },
  "usia harapan hidup": { var: "494", label: "Umur Harapan Hidup" },
  uhh: { var: "494", label: "Umur Harapan Hidup" },

  // Sosial
  "kemiskinan ekstrem desa": { var: "2213", label: "Kemiskinan Ekstrem Perdesaan" },
  "perlindungan sosial": { var: "621", label: "Penerima Perlindungan Sosial" },
};

function escapeRegex(text: string): string {
  return text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

/**
 * Mencari variabel BPS dari kata kunci pengguna dengan pencocokan kata utuh (word boundary).
 * Mencegah false positives seperti "pendidikan" mencocokkan "ikan".
 */
export function cariVarBpsDariKataKunci(kataKunci: string): BpsKeywordMatch | null {
  const needle = kataKunci.trim().toLowerCase();
  if (!needle) return null;

  // 1. Exact match
  if (needle in BPS_KEYWORD_TO_VAR) {
    return BPS_KEYWORD_TO_VAR[needle];
  }

  // 2. Phrase match dengan word boundary (prioritaskan kunci yang lebih panjang/spesifik)
  const sortedKeys = Object.keys(BPS_KEYWORD_TO_VAR).sort((a, b) => b.length - a.length);
  for (const key of sortedKeys) {
    const pattern = new RegExp(`\\b${escapeRegex(key)}\\b`, "i");
    if (pattern.test(needle)) {
      return BPS_KEYWORD_TO_VAR[key];
    }
  }

  // 3. Token-based word match: jika token kata input ada yang persis sama dengan kunci
  const tokens = needle.split(/[\s,./\-_+]+/).filter((t) => t.length > 1);
  for (const token of tokens) {
    if (token in BPS_KEYWORD_TO_VAR) {
      return BPS_KEYWORD_TO_VAR[token];
    }
  }

  return null;
}

function asText(value: unknown): string {
  return typeof value === "string" ? value : value == null ? "" : String(value);
}

/**
 * Menganalisis respons Web API BPS untuk mengekstrak pesan status dan diagnostik error.
 */
export function parseBpsDiagnostics(payload: unknown): BpsDiagnosticResult {
  if (!payload || typeof payload !== "object") {
    return { ok: false, message: "Respons BPS tidak valid atau kosong.", dataAvailable: false };
  }
  const root = payload as Record<string, unknown>;
  const status = asText(root.status).toLowerCase();
  const availability = asText(root["data-availability"]).toLowerCase();
  const message = asText(root.message);

  if (status === "error" || message.toLowerCase().includes("not allowed") || message.toLowerCase().includes("key")) {
    return {
      ok: false,
      message: message || "Akses BPS ditolak. Periksa kembali BPS API Key Anda.",
      dataAvailable: false,
    };
  }

  if (availability === "unavailable" || availability === "list-not-available" || message.toLowerCase().includes("tidak ditemukan")) {
    return {
      ok: false,
      message: message || "Data tidak ditemukan untuk indikator/domain tersebut di BPS.",
      dataAvailable: false,
    };
  }

  if ("datacontent" in root && typeof root.datacontent === "object" && root.datacontent !== null) {
    const datacontent = root.datacontent as Record<string, unknown>;
    const count = Object.keys(datacontent).length;
    if (count > 0) {
      return { ok: true, message: `Berhasil memuat ${count} data point BPS.`, dataAvailable: true };
    }
  }

  if (Array.isArray(root.data) && root.data.length > 0) {
    return { ok: true, message: `Berhasil memuat ${root.data.length} baris data BPS.`, dataAvailable: true };
  }

  return {
    ok: false,
    message: message || "Tidak ada observasi data yang dapat dibaca dari respons BPS.",
    dataAvailable: false,
  };
}

export function bpsPayloadToText(payload: unknown): string {
  const root = payload && typeof payload === "object" ? (payload as Record<string, unknown>) : {};

  // ── Format 1: Dynamic Data BPS (datacontent matriks multidimensi) ──────────
  if ("datacontent" in root && typeof root.datacontent === "object" && root.datacontent !== null) {
    const datacontent = root.datacontent as Record<string, number>;
    const varList = Array.isArray(root.var) ? (root.var as Record<string, unknown>[]) : [{}];
    const vervar = Array.isArray(root.vervar) ? (root.vervar as Record<string, unknown>[]) : [];
    const tahunList = Array.isArray(root.tahun) ? (root.tahun as Record<string, unknown>[]) : [];
    const turvar = Array.isArray(root.turvar)
      ? (root.turvar as Record<string, unknown>[])
      : [{ val: 0, label: "" }];
    const turtahun = Array.isArray(root.turtahun)
      ? (root.turtahun as Record<string, unknown>[])
      : [{ val: 0, label: "Tahunan" }];

    const varVal = String(varList[0]?.val ?? "");
    const varLabel = asText(varList[0]?.label ?? "Nilai");
    const unit = asText(varList[0]?.unit ?? "");

    const rows: Record<string, string>[] = [];
    for (const vv of vervar) {
      for (const th of tahunList) {
        for (const tv of turvar) {
          for (const tt of turtahun) {
            // turtahun harus 2 digit (zero-padded) sesuai format datacontent BPS
            const ttVal = String(tt.val ?? "0").padStart(2, "0");
            const key = `${vv.val}${varVal}${tv.val}${th.val}${ttVal}`;
            if (key in datacontent) {
              const row: Record<string, string> = {
                kode_wilayah: String(vv.val ?? ""),
                nama_wilayah: asText(vv.label),
                tahun: asText(th.label),
                indikator: varLabel,
              };
              if (turvar.length > 1) row.kategori = asText(tv.label);
              if (turtahun.length > 1) row.periode = asText(tt.label);
              row.nilai = String(datacontent[key]);
              if (unit) row.satuan = unit;
              rows.push(row);
            }
          }
        }
      }
    }
    if (rows.length > 0) {
      // Urutkan tahun terbaru di atas
      rows.sort((a, b) => b.tahun.localeCompare(a.tahun));
      const columns = [...new Set(rows.flatMap((r) => Object.keys(r)))];
      const escape = (v: unknown) => `"${asText(v).replaceAll('"', '""')}"`;
      return [
        columns.map(escape).join(","),
        ...rows.map((r) => columns.map((c) => escape(r[c])).join(",")),
      ].join("\n");
    }
  }

  // ── Format 2: Array list (fallback / static table) ──────────────────────────
  const rows = Array.isArray(root.data)
    ? root.data
    : root.data && typeof root.data === "object" && Array.isArray((root.data as Record<string, unknown>).data)
      ? ((root.data as Record<string, unknown>).data as unknown[])
      : [];
  if (!rows.length) return "";
  const objects = rows.filter((row): row is Record<string, unknown> => Boolean(row && typeof row === "object"));
  if (!objects.length) return "";
  const columns = [...new Set(objects.flatMap((row) => Object.keys(row)))];
  const escape = (value: unknown) => `"${asText(value).replaceAll('"', '""')}"`;
  return [
    columns.map(escape).join(","),
    ...objects.map((row) => columns.map((column) => escape(row[column])).join(",")),
  ].join("\n");
}
