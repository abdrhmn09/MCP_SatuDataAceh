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

// Shared with the Python package; edit src/bps_catalog.json only.
import catalog from "../../src/bps_catalog.json";
export const BPS_INDICATOR_MAP: Record<string, BpsIndicator> = catalog.indicators;
export const BPS_KEYWORD_TO_VAR: Record<string, BpsKeywordMatch> = catalog.keywords;

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

    if (vervar.length * tahunList.length * Math.max(1, turvar.length) * Math.max(1, turtahun.length) > 1_000_000) return "";

    const varVal = String(varList[0]?.val ?? "");
    const varLabel = asText(varList[0]?.label ?? "Nilai");
    const unit = asText(varList[0]?.unit ?? "");

    const rows: Record<string, string>[] = [];
    for (const vv of vervar) for (const th of tahunList)
      for (const tv of turvar.length ? turvar : [{ val: 0, label: "" }])
        for (const tt of turtahun.length ? turtahun : [{ val: 0, label: "Tahunan" }]) {
          const key = `${vv.val}${varVal}${tv.val}${th.val}${tt.val}`;
          if (!Object.prototype.hasOwnProperty.call(datacontent, key)) continue;
          const row: Record<string, string> = {
            kode_wilayah: asText(vv.val), nama_wilayah: asText(vv.label),
            tahun: asText(th.label), indikator: varLabel, nilai: asText(datacontent[key]),
          };
          if (turvar.length > 1) row.kategori = asText(tv.label);
          if (turtahun.length > 1) row.periode = asText(tt.label);
          if (unit) row.satuan = unit;
          rows.push(row);
        }
    // Unknown dimension keys must never be assigned a guessed year or region.
    if (rows.length !== Object.keys(datacontent).length) return "";
    rows.sort((a, b) => b.tahun.localeCompare(a.tahun));
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
