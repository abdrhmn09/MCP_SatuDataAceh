/**
 * BPS Aceh variable mapping dan parser respons Web API BPS untuk Cloudflare Worker.
 */

export interface BpsIndicator {
  var: string;
  label: string;
  category: string;
  defaultTh?: string; // th_id (124=2024, 123=2023)
}

export interface BpsKeywordMatch {
  var: string;
  label: string;
  defaultTh?: string;
}

export interface BpsDiagnosticResult {
  ok: boolean;
  message: string;
  dataAvailable: boolean;
}

export const BPS_INDICATOR_MAP: Record<string, BpsIndicator> = {
  // ── Kemiskinan ──────────────────────────────────────────────────────────
  "0116d97b-1b4a-4c6a-a243-33833660fb85": {
    var: "42",
    label: "Persentase Penduduk Miskin Aceh Menurut Kabupaten/Kota",
    category: "kemiskinan",
    defaultTh: "124",
  },
  "afefeee7-2dbb-4ab8-aa2c-71610fc5fdb6": {
    var: "41",
    label: "Jumlah Penduduk Miskin Menurut Kabupaten/Kota",
    category: "kemiskinan",
    defaultTh: "124",
  },
  // ── Pembangunan Manusia & Pendidikan ─────────────────────────────────────
  "78794e4b-2bbe-45ef-abd1-0a65c2e98702": {
    var: "245",
    label: "Rata-rata Lama Sekolah (RLS) Menurut Kabupaten/Kota",
    category: "pendidikan",
    defaultTh: "124",
  },
  "2414165c-27b1-41a1-8229-0a51a128636d": {
    var: "245",
    label: "Rata-rata Lama Sekolah (RLS)",
    category: "pendidikan",
    defaultTh: "124",
  },
  "f2585d70-70d1-49f9-8c78-6750a46e1780": {
    var: "245",
    label: "Rata-rata Lama Sekolah Provinsi Aceh Menurut Kabupaten/Kota",
    category: "pendidikan",
    defaultTh: "124",
  },
  "6cab69b8-d936-4f8a-b5a1-ea1fb45589e9": {
    var: "245",
    label: "Rata-rata Lama Sekolah (RLS) BPS Aceh",
    category: "pendidikan",
    defaultTh: "124",
  },
  // ── Ketenagakerjaan ─────────────────────────────────────────────────────
  "97e549de-0a20-452a-9948-455abe2532a8": {
    var: "206",
    label: "Tingkat Pengangguran Terbuka (TPT) Menurut Kabupaten/Kota",
    category: "ketenagakerjaan",
    defaultTh: "124",
  },
  // ── Ekonomi & PDRB ─────────────────────────────────────────────────────
  "22d3b2b0-8c0e-46cb-915d-7780fd4e1158": {
    var: "204",
    label: "Laju Pertumbuhan Ekonomi Aceh",
    category: "pdrb",
    defaultTh: "124",
  },
  "95ceff6a-c0d9-4ef5-b6cb-86eee4764833": {
    var: "397",
    label: "PDRB Tahunan Atas Dasar Harga Berlaku Provinsi Aceh",
    category: "pdrb",
    defaultTh: "124",
  },
  "bfe0cc05-78ff-46f2-9329-c943863e5c50": {
    var: "204",
    label: "Pertumbuhan PDRB Provinsi Aceh",
    category: "pdrb",
    defaultTh: "124",
  },
  // ── Harga & Inflasi ─────────────────────────────────────────────────────
  "e8c8605b-5ce1-4637-be23-9108837e89c9": {
    var: "564",
    label: "Tingkat Inflasi Tahun ke Tahun Provinsi Aceh",
    category: "inflasi",
    defaultTh: "124",
  },
  // ── Ketimpangan ─────────────────────────────────────────────────────────
  "0c63d096-1671-4afd-94b5-39048d378e56": {
    var: "60",
    label: "Rasio Gini Provinsi Aceh",
    category: "ketimpangan",
    defaultTh: "124",
  },
  // ── Pertanian Tanaman Pangan ────────────────────────────────────────────
  "d8c8a7f0-d329-4872-8546-294fd6267c7b": {
    var: "574",
    label: "Produksi Padi Menurut Kabupaten/Kota",
    category: "pertanian",
    defaultTh: "123",
  },
  // ── Perikanan ───────────────────────────────────────────────────────────
  "3f92d70a-8533-4f25-bc9f-332b7a4c8b84": {
    var: "204",
    label: "PDRB Sektor Pertanian, Kehutanan dan Perikanan Aceh",
    category: "perikanan",
    defaultTh: "124",
  },
  // ── Indikator Tambahan Terverifikasi ────────────────────────────────────
  "1d4d7e1a-9d53-45a4-a11e-dc24d6c8cf25": {
    var: "246",
    label: "Harapan Lama Sekolah (HLS) Menurut Kabupaten/Kota",
    category: "pendidikan",
    defaultTh: "124",
  },
  "81dc3ba5-e050-47fe-846b-298ca2977216": {
    var: "45",
    label: "Garis Kemiskinan Menurut Kabupaten/Kota",
    category: "kemiskinan",
    defaultTh: "124",
  },
  "21cece89-360f-480d-a3e9-a841a79e752d": {
    var: "2",
    label: "Indeks Harga Konsumen (IHK) Provinsi Aceh",
    category: "inflasi",
    defaultTh: "124",
  },
};

export const BPS_KEYWORD_TO_VAR: Record<string, BpsKeywordMatch> = {
  // Pendidikan
  pendidikan: { var: "245", label: "Rata-rata Lama Sekolah (RLS)", defaultTh: "124" },
  sekolah: { var: "245", label: "Rata-rata Lama Sekolah (RLS)", defaultTh: "124" },
  guru: { var: "245", label: "Indikator Pendidikan / RLS", defaultTh: "124" },
  murid: { var: "245", label: "Indikator Pendidikan / RLS", defaultTh: "124" },
  siswa: { var: "245", label: "Indikator Pendidikan / RLS", defaultTh: "124" },
  "lama sekolah": { var: "245", label: "Rata-rata Lama Sekolah", defaultTh: "124" },
  "rata-rata lama sekolah": { var: "245", label: "Rata-rata Lama Sekolah", defaultTh: "124" },
  "harapan lama sekolah": { var: "246", label: "Harapan Lama Sekolah", defaultTh: "124" },
  rls: { var: "245", label: "Rata-rata Lama Sekolah", defaultTh: "124" },
  hls: { var: "246", label: "Harapan Lama Sekolah", defaultTh: "124" },
  aps: { var: "245", label: "Angka Partisipasi Sekolah / RLS", defaultTh: "124" },

  // Kemiskinan
  kemiskinan: { var: "42", label: "Persentase Penduduk Miskin", defaultTh: "124" },
  miskin: { var: "42", label: "Persentase Penduduk Miskin", defaultTh: "124" },
  "penduduk miskin": { var: "42", label: "Persentase Penduduk Miskin", defaultTh: "124" },
  "jumlah penduduk miskin": { var: "41", label: "Jumlah Penduduk Miskin", defaultTh: "124" },
  "garis kemiskinan": { var: "45", label: "Garis Kemiskinan", defaultTh: "124" },

  // IPM
  ipm: { var: "245", label: "Indeks Pembangunan Manusia / RLS", defaultTh: "124" },
  "pembangunan manusia": { var: "245", label: "Indeks Pembangunan Manusia / RLS", defaultTh: "124" },

  // Ketenagakerjaan
  pengangguran: { var: "206", label: "Tingkat Pengangguran Terbuka", defaultTh: "124" },
  tpt: { var: "206", label: "Tingkat Pengangguran Terbuka", defaultTh: "124" },
  "angkatan kerja": { var: "206", label: "Ketenagakerjaan / TPT", defaultTh: "124" },

  // Ekonomi & PDRB
  pdrb: { var: "204", label: "Laju Pertumbuhan PDRB", defaultTh: "124" },
  "pertumbuhan ekonomi": { var: "204", label: "Laju Pertumbuhan Ekonomi", defaultTh: "124" },
  "laju pertumbuhan": { var: "204", label: "Laju Pertumbuhan Ekonomi", defaultTh: "124" },

  // Inflasi
  inflasi: { var: "564", label: "Laju Inflasi Tahun ke Tahun", defaultTh: "124" },
  ihk: { var: "2", label: "Indeks Harga Konsumen", defaultTh: "124" },

  // Ketimpangan
  gini: { var: "60", label: "Rasio Gini", defaultTh: "124" },
  "rasio gini": { var: "60", label: "Rasio Gini", defaultTh: "124" },

  // Pertanian
  padi: { var: "574", label: "Produksi Padi", defaultTh: "123" },
  "produksi padi": { var: "574", label: "Produksi Padi", defaultTh: "123" },

  // Perikanan
  perikanan: { var: "204", label: "PDRB Lapangan Usaha Perikanan", defaultTh: "124" },
  ikan: { var: "204", label: "PDRB Lapangan Usaha Perikanan", defaultTh: "124" },
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

    // Peta vervar untuk lookup cepat
    const vervarMap = new Map<string, string>();
    for (const vv of vervar) {
      vervarMap.set(String(vv.val ?? ""), asText(vv.label));
    }

    const rows: Record<string, string>[] = [];
    for (const [key, value] of Object.entries(datacontent)) {
      // Ambil kode wilayah dari 4 digit pertama (atau lookup vervarMap)
      let matchedVervarVal = "";
      let matchedVervarLabel = "";
      for (const [vVal, vLabel] of vervarMap.entries()) {
        if (key.startsWith(vVal)) {
          matchedVervarVal = vVal;
          matchedVervarLabel = vLabel;
          break;
        }
      }

      const tahunLabel = tahunList[0] ? asText(tahunList[0].label) : "2024";
      const row: Record<string, string> = {
        kode_wilayah: matchedVervarVal || key.slice(0, 4),
        nama_wilayah: matchedVervarLabel || `Wilayah ${key.slice(0, 4)}`,
        tahun: tahunLabel,
        indikator: varLabel,
        nilai: String(value),
      };
      if (unit && unit !== "Tidak Ada Satuan") {
        row.satuan = unit;
      }
      rows.push(row);
    }

    if (rows.length > 0) {
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
