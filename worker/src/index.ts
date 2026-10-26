import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { WebStandardStreamableHTTPServerTransport } from "@modelcontextprotocol/sdk/server/webStandardStreamableHttp.js";
import { z } from "zod";
import {
  BPS_INDICATOR_MAP,
  cariVarBpsDariKataKunci,
  bpsPayloadToText,
  parseBpsDiagnostics,
} from "./bps";

export { bpsPayloadToText, parseBpsDiagnostics, cariVarBpsDariKataKunci } from "./bps";

export interface Env {
  CATALOG_URL: string;
  DATA_YEAR: string;
  CATALOG_TTL_SECONDS: string;
  MAX_REQUESTS_PER_MINUTE: string;
  BPS_API_KEY?: string;
  BPS_DOMAIN?: string;
  BPS_DATASET_MAP?: string;
}

export interface Dataset {
  identifier?: unknown;
  title?: unknown;
  description?: unknown;
  keyword?: unknown;
  issued?: unknown;
  modified?: unknown;
  landingPage?: unknown;
  publisher?: unknown;
  distribution?: unknown;
}

export interface CatalogResponse {
  dataset?: unknown;
}

export interface SearchResult {
  id: string;
  title: string;
  url: string;
}

export interface CsvAnalysis {
  status: "valid" | "header_only" | "empty" | "html";
  text: string;
  preview: string;
  rowCount: number;
  columnCount: number;
  message?: string;
}

export interface BpsSource {
  domain: string;
  variable: string;
  referenceUrl: string;
}

const MAX_CSV_BYTES = 5 * 1024 * 1024;
const MAX_HTML_BYTES = 2 * 1024 * 1024;
const MAX_ROWS = 50;
const cache = new Map<string, { expiresAt: number; datasets: Dataset[] }>();
const requestTimes: number[] = [];

function envInt(value: string | undefined, fallback: number): number {
  const parsed = Number.parseInt(value ?? "", 10);
  return Number.isFinite(parsed) ? parsed : fallback;
}

export function isPublicHttpsUrl(value: string): boolean {
  try {
    const url = new URL(value);
    if (url.protocol !== "https:" || url.username || url.password) return false;
    const hostname = url.hostname.toLowerCase();
    return ![
      "localhost",
      "localhost.localdomain",
      "127.0.0.1",
      "::1",
      "0.0.0.0",
      "169.254.169.254",
    ].includes(hostname) && !hostname.endsWith(".localhost");
  } catch {
    return false;
  }
}

export function allowRequest(env: Env): boolean {
  const limit = Math.max(1, envInt(env.MAX_REQUESTS_PER_MINUTE, 60));
  const now = Date.now();
  while (requestTimes.length && now - requestTimes[0] >= 60_000) requestTimes.shift();
  if (requestTimes.length >= limit) return false;
  requestTimes.push(now);
  return true;
}

export function asText(value: unknown): string {
  return typeof value === "string" ? value : value == null ? "" : String(value);
}

export function datasetId(dataset: Dataset): string {
  return asText(dataset.identifier).trim();
}

export function datasetTitle(dataset: Dataset): string {
  return asText(dataset.title) || "Dataset Aceh";
}

export function datasetPage(dataset: Dataset): string {
  const landingPage = asText(dataset.landingPage);
  if (landingPage) return landingPage;
  if (Array.isArray(dataset.distribution)) {
    for (const distribution of dataset.distribution) {
      if (distribution && typeof distribution === "object") {
        const accessURL = asText((distribution as Record<string, unknown>).accessURL);
        if (accessURL) return accessURL;
      }
    }
  }
  return "";
}

export function datasetYear(dataset: Dataset, env: Env): string {
  const metadata = [dataset.title, dataset.description, dataset.issued, dataset.modified]
    .map(asText)
    .join(" ");
  return metadata.match(/\b20\d{2}\b/)?.[0] ?? env.DATA_YEAR ?? "2025";
}

export function csvUrl(dataset: Dataset, env: Env): string {
  const page = datasetPage(dataset);
  try {
    const hostname = new URL(page).hostname;
    if (hostname === "satudata.acehprov.go.id") {
      const id = encodeURIComponent(datasetId(dataset));
      if (id) {
        return `https://satudata.acehprov.go.id/api/datasets/${id}/datasources/download?tahun=${encodeURIComponent(datasetYear(dataset, env))}`;
      }
    }
  } catch {
    // Fall through to a distribution URL or the landing page.
  }

  if (Array.isArray(dataset.distribution)) {
    for (const distribution of dataset.distribution) {
      if (!distribution || typeof distribution !== "object") continue;
      const item = distribution as Record<string, unknown>;
      const mediaType = asText(item.mediaType).toLowerCase();
      const format = asText(item.format).toLowerCase();
      if (mediaType.includes("csv") || format.includes("csv")) {
        const url = asText(item.downloadURL || item.accessURL);
        if (url) return url;
      }
    }
  }
  return page;
}

export function bpsSource(dataset: Dataset, env: Env): BpsSource | null {
  const identifier = datasetId(dataset);
  if (!identifier) return null;
  let mapping: Record<string, string> = {};
  try {
    mapping = JSON.parse(env.BPS_DATASET_MAP || "{}") as Record<string, string>;
  } catch {
    // Ignore JSON parse errors
  }
  let variable = mapping[identifier] || (identifier === "621" ? "621" : "");
  if (!variable && identifier in BPS_INDICATOR_MAP) {
    variable = BPS_INDICATOR_MAP[identifier].var;
  }
  if (!variable) return null;
  const domain = env.BPS_DOMAIN || "1100";
  return {
    domain,
    variable,
    referenceUrl: datasetPage(dataset),
  };
}

export function bpsUrl(source: BpsSource, env: Env, thParam: string = "124"): string {
  return `https://webapi.bps.go.id/v1/api/list/model/data/domain/${encodeURIComponent(source.domain)}/var/${encodeURIComponent(source.variable)}/th/${encodeURIComponent(thParam)}/key/${encodeURIComponent(env.BPS_API_KEY || "")}/`;
}

export async function fetchBpsJson(
  url: string,
): Promise<{ ok: boolean; payload?: unknown; status?: number; error?: string }> {
  try {
    const response = await fetch(url, {
      headers: {
        "User-Agent":
          "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "id-ID,id;q=0.9,en-US;q=0.8,en;q=0.7",
      },
    });

    const textBody = await response.text();
    if (!textBody || !textBody.trim()) {
      return {
        ok: false,
        status: response.status,
        error: `BPS mengembalikan respons kosong (HTTP ${response.status}).`,
      };
    }

    const trimmed = textBody.trim();
    if (trimmed.startsWith("<!DOCTYPE") || trimmed.startsWith("<html") || trimmed.startsWith("<")) {
      return {
        ok: false,
        status: response.status,
        error: `BPS mengembalikan halaman HTML/WAF (HTTP ${response.status}). Pastikan API Key valid.`,
      };
    }

    try {
      const payload = JSON.parse(textBody);
      return { ok: true, payload, status: response.status };
    } catch (parseError) {
      return {
        ok: false,
        status: response.status,
        error: `Gagal mengurai respons JSON dari BPS (HTTP ${response.status}): ${parseError instanceof Error ? parseError.message : "Invalid JSON"}. Cuplikan: ${trimmed.slice(0, 100)}`,
      };
    }
  } catch (error) {
    return {
      ok: false,
      error: `Gagal terhubung ke BPS Web API: ${error instanceof Error ? error.message : "Network error"}`,
    };
  }
}

export async function fetchFromBps(dataset: Dataset, env: Env): Promise<{ analysis: CsvAnalysis; source: BpsSource } | null> {
  const source = bpsSource(dataset, env);
  if (!source || !env.BPS_API_KEY) return null;
  const thCandidates = ["124", "123", "122"];
  for (const th of thCandidates) {
    const url = bpsUrl(source, env, th);
    const result = await fetchBpsJson(url);
    if (!result.ok || !result.payload) {
      continue;
    }
    const diag = parseBpsDiagnostics(result.payload);
    if (!diag.ok || !diag.dataAvailable) {
      continue;
    }
    const text = bpsPayloadToText(result.payload);
    if (!text) {
      continue;
    }
    return { analysis: analyzeCsvText(text, MAX_ROWS), source };
  }
  return null;
}

export async function fetchFromBpsDirect(
  varId: string,
  domain: string,
  env: Env,
  maxRows: number = MAX_ROWS,
  preferredTh?: string,
): Promise<{ analysis: CsvAnalysis; url: string; diagnostic?: string } | null> {
  if (!env.BPS_API_KEY) {
    return {
      analysis: {
        status: "empty",
        text: "",
        preview: "",
        rowCount: 0,
        columnCount: 0,
        message: "BPS_API_KEY belum dikonfigurasi. Daftarkan key Anda via secret Cloudflare Worker: npx wrangler secret put BPS_API_KEY",
      },
      url: `https://webapi.bps.go.id/v1/api/list/model/data/domain/${encodeURIComponent(domain)}/var/${encodeURIComponent(varId)}/th/124/key/***/`,
      diagnostic: "API Key belum disetel. Jalankan: npx wrangler secret put BPS_API_KEY",
    };
  }
  const thCandidates = preferredTh ? [preferredTh, "124", "123"] : ["124", "123", "122"];
  let lastDiag = "Data tidak ditemukan di BPS.";
  let lastUrl = `https://webapi.bps.go.id/v1/api/list/model/data/domain/${encodeURIComponent(domain)}/var/${encodeURIComponent(varId)}/th/124/key/***/`;

  for (const th of thCandidates) {
    const url = `https://webapi.bps.go.id/v1/api/list/model/data/domain/${encodeURIComponent(domain)}/var/${encodeURIComponent(varId)}/th/${encodeURIComponent(th)}/key/${encodeURIComponent(env.BPS_API_KEY)}/`;
    lastUrl = url;
    const result = await fetchBpsJson(url);
    if (!result.ok || !result.payload) {
      lastDiag = result.error || "Gagal mengambil data dari BPS.";
      continue;
    }
    const diag = parseBpsDiagnostics(result.payload);
    lastDiag = diag.message;
    if (!diag.ok || !diag.dataAvailable) {
      continue;
    }
    const text = bpsPayloadToText(result.payload);
    if (!text) {
      lastDiag = "Payload BPS berhasil diterima tetapi konversi data ke format CSV kosong.";
      continue;
    }
    return {
      analysis: analyzeCsvText(text, maxRows),
      url,
      diagnostic: diag.message,
    };
  }

  return {
    analysis: {
      status: "empty",
      text: "",
      preview: "",
      rowCount: 0,
      columnCount: 0,
      message: `BPS API: ${lastDiag}`,
    },
    url: lastUrl,
    diagnostic: lastDiag,
  };
}

export async function loadCatalog(env: Env): Promise<Dataset[]> {
  const now = Date.now();
  const ttl = Math.max(60, envInt(env.CATALOG_TTL_SECONDS, 3600)) * 1000;
  const cached = cache.get(env.CATALOG_URL);
  if (cached && cached.expiresAt > now) return cached.datasets;

  const response = await fetch(env.CATALOG_URL);
  if (!response.ok) throw new Error(`Catalog request failed: ${response.status}`);
  const payload = (await response.json()) as CatalogResponse;
  const datasets = Array.isArray(payload.dataset)
    ? payload.dataset.filter((item): item is Dataset => Boolean(item && typeof item === "object"))
    : [];
  if (!datasets.length) throw new Error("Catalog does not contain a dataset array");
  cache.set(env.CATALOG_URL, { expiresAt: now + ttl, datasets });
  return datasets;
}

function searchableText(dataset: Dataset): string {
  const publisher = dataset.publisher && typeof dataset.publisher === "object"
    ? asText((dataset.publisher as Record<string, unknown>).name)
    : "";
  return [dataset.title, dataset.description, dataset.keyword, publisher, dataset.identifier]
    .map(asText)
    .join(" ")
    .toLowerCase();
}

function normalizeTerms(query: string): string[] {
  const normalized = query.toLowerCase().trim();
  const synonyms: Record<string, string[]> = {
    kemiskinan: ["kemiskinan", "miskin", "garis kemiskinan", "penduduk miskin"],
    miskin: ["kemiskinan", "miskin", "penduduk miskin"],
    bps: ["bps", "badan pusat statistik", "susenas"],
    pendidikan: ["pendidikan", "sekolah", "guru", "murid", "siswa", "lama sekolah"],
  };
  const terms = new Set<string>(normalized ? [normalized] : []);
  for (const token of normalized.split(/\s+/).filter(Boolean)) {
    terms.add(token);
    for (const syn of synonyms[token] ?? []) terms.add(syn);
  }
  return [...terms];
}

export function matchDatasets(datasets: Dataset[], query: string): Dataset[] {
  const terms = normalizeTerms(query);
  if (!terms.length) return [];
  const scored: { score: number; dataset: Dataset }[] = [];

  for (const dataset of datasets) {
    const text = searchableText(dataset);
    const title = datasetTitle(dataset).toLowerCase();
    const matched = terms.filter((term) => text.includes(term));
    if (!matched.length) continue;
    const score = matched.length + matched.filter((term) => title.includes(term)).length * 2;
    scored.push({ score, dataset });
  }

  scored.sort((a, b) => b.score - a.score);
  return scored.slice(0, 5).map((item) => item.dataset);
}

export function searchDatasets(datasets: Dataset[], query: string): SearchResult[] {
  return matchDatasets(datasets, query).map((dataset) => ({
    id: datasetId(dataset),
    title: datasetTitle(dataset),
    url: datasetPage(dataset) || datasetId(dataset),
  }));
}

function parseCsvLine(line: string): string[] {
  const cells: string[] = [];
  let cur = "";
  let inQuotes = false;
  for (let i = 0; i < line.length; i++) {
    const c = line[i];
    if (c === '"') {
      if (inQuotes && line[i + 1] === '"') {
        cur += '"';
        i++;
      } else {
        inQuotes = !inQuotes;
      }
    } else if (c === "," && !inQuotes) {
      cells.push(cur);
      cur = "";
    } else {
      cur += c;
    }
  }
  cells.push(cur);
  return cells;
}

export function csvToMarkdownTable(csvText: string, maxRows: number = 20): string {
  const cleaned = csvText.replace(/^\uFEFF/, "").trim();
  if (!cleaned) return "";
  const lines = cleaned.split(/\r?\n/).filter(Boolean);
  if (!lines.length) return "";

  const parsedRows = lines.slice(0, maxRows + 1).map(parseCsvLine);
  if (!parsedRows.length) return "";
  const header = parsedRows[0];
  const colCount = header.length;
  if (colCount === 0) return "";

  const headerStr = `| ${header.map((h) => h.trim()).join(" | ")} |`;
  const sepStr = `| ${header.map(() => "---").join(" | ")} |`;
  const bodyStrs = parsedRows.slice(1).map((row) => {
    const rowPadded = Array.from({ length: colCount }, (_, i) => (row[i] ?? "").trim());
    return `| ${rowPadded.join(" | ")} |`;
  });

  return [headerStr, sepStr, ...bodyStrs].join("\n");
}

export function parseCsvRows(text: string, maxRows: number): string {
  const lines = text.replace(/^\uFEFF/, "").split(/\r?\n/).filter(Boolean);
  if (!lines.length) return "";
  return lines.slice(0, Math.max(1, Math.min(maxRows, MAX_ROWS)) + 1).join("\n");
}

export function analyzeCsvText(text: string, maxRows: number): CsvAnalysis {
  const cleaned = text.replace(/^\uFEFF/, "").trim();
  if (!cleaned) {
    return { status: "empty", text: "", preview: "", rowCount: 0, columnCount: 0, message: "File CSV tidak berisi data." };
  }
  if (cleaned.startsWith("<") && cleaned.slice(0, 500).toLowerCase().includes("html")) {
    return { status: "html", text: "", preview: "", rowCount: 0, columnCount: 0, message: "Sumber mengembalikan halaman HTML, bukan CSV." };
  }
  const lines = cleaned.split(/\r?\n/).filter(Boolean);
  const columnCount = parseCsvLine(lines[0]).length;
  const rowCount = Math.max(0, lines.length - 1);
  if (rowCount === 0) {
    return { status: "header_only", text: "", preview: "", rowCount, columnCount, message: "Sumber CSV hanya berisi header tanpa observasi." };
  }
  const preview = csvToMarkdownTable(cleaned, maxRows);
  return { status: "valid", text: parseCsvRows(cleaned, maxRows), preview, rowCount, columnCount };
}

export async function fetchCsvFromUrl(url: string, maxRows: number): Promise<CsvAnalysis> {
  if (!isPublicHttpsUrl(url)) {
    throw new Error("URL CSV harus menggunakan HTTPS dan alamat publik yang valid.");
  }
  const response = await fetch(url, {
    headers: {
      "User-Agent":
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
      "Accept": "text/csv, text/plain, application/json, */*",
    },
  });
  if (!response.ok) {
    throw new Error(`Gagal mengunduh file CSV dari URL tersebut (HTTP ${response.status}).`);
  }
  const contentLength = Number(response.headers.get("content-length") || 0);
  if (contentLength > MAX_CSV_BYTES) {
    return {
      status: "empty",
      text: "",
      preview: "",
      rowCount: 0,
      columnCount: 0,
      message: "File CSV terlalu besar untuk diproses (maksimal 5 MB).",
    };
  }
  const body = await response.arrayBuffer();
  if (body.byteLength > MAX_CSV_BYTES) {
    return {
      status: "empty",
      text: "",
      preview: "",
      rowCount: 0,
      columnCount: 0,
      message: "File CSV terlalu besar untuk diproses (maksimal 5 MB).",
    };
  }
  const text = new TextDecoder("utf-8").decode(body);
  return analyzeCsvText(text, maxRows);
}

export async function findCsvLinkInHtml(pageUrl: string): Promise<string | null> {
  if (!isPublicHttpsUrl(pageUrl)) return null;
  try {
    const response = await fetch(pageUrl);
    if (!response.ok) return null;
    const html = await response.text();
    if (html.length > MAX_HTML_BYTES) return null;
    const linkMatches = html.matchAll(/<(?:a|link)\s+[^>]*href=["']([^"']+)["'][^>]*>/gi);
    for (const match of linkMatches) {
      const href = match[1];
      const fullTag = match[0].toLowerCase();
      if (href.toLowerCase().endsWith(".csv") || fullTag.includes("csv")) {
        const candidate = new URL(href, pageUrl).toString();
        if (isPublicHttpsUrl(candidate)) {
          return candidate;
        }
      }
    }
    return null;
  } catch {
    return null;
  }
}

async function fetchDatasetText(dataset: Dataset, env: Env): Promise<CsvAnalysis> {
  const url = csvUrl(dataset, env);
  return fetchCsvFromUrl(url, MAX_ROWS);
}

export function createServer(env: Env): McpServer {
  const server = new McpServer({
    name: "Satu Data Aceh Server",
    version: "0.2.0",
  });

  // ── 1. Tool: search ───────────────────────────────────────────────────────
  server.registerTool(
    "search",
    {
      description: "Mencari dataset Aceh dan mengembalikan hasil dengan URL yang dapat dikutip.",
      inputSchema: { query: z.string().describe("Kata kunci pencarian dataset") },
    },
    async ({ query }) => {
      if (!allowRequest(env)) {
        throw new Error("Batas permintaan tercapai. Coba lagi beberapa saat.");
      }
      const trimmed = asText(query).trim();
      if (!trimmed) {
        return {
          content: [{ type: "text", text: JSON.stringify({ results: [] }) }],
          structuredContent: { results: [] },
        };
      }
      const datasets = await loadCatalog(env);
      const payload = { results: searchDatasets(datasets, trimmed) };
      return {
        content: [{ type: "text", text: JSON.stringify(payload) }],
        structuredContent: payload,
      };
    },
  );

  // ── 2. Tool: fetch ────────────────────────────────────────────────────────
  server.registerTool(
    "fetch",
    {
      description: "Mengambil isi ringkas CSV dataset berdasarkan identifier hasil search.",
      inputSchema: { id: z.string().describe("Identifier dataset") },
    },
    async ({ id }) => {
      if (!allowRequest(env)) {
        throw new Error("Batas permintaan tercapai. Coba lagi beberapa saat.");
      }
      const datasets = await loadCatalog(env);
      const dataset = datasets.find((item) => datasetId(item) === id);
      if (!dataset) throw new Error("Dataset tidak ditemukan untuk identifier tersebut.");
      const directCsvUrl = csvUrl(dataset, env);
      if (!directCsvUrl) throw new Error("Dataset tidak memiliki URL CSV yang dapat diakses.");

      let analysis: CsvAnalysis;
      try {
        analysis = await fetchDatasetText(dataset, env);
      } catch (error) {
        analysis = {
          status: "empty",
          text: "",
          preview: "",
          rowCount: 0,
          columnCount: 0,
          message: error instanceof Error ? error.message : "Gagal mengunduh file CSV",
        };
      }

      let source = "Satu Data Aceh";
      let referenceSource = datasetPage(dataset);
      let sourceUrl = directCsvUrl;

      if (analysis.status !== "valid") {
        const bps = await fetchFromBps(dataset, env);
        if (bps) {
          analysis = bps.analysis;
          source = "BPS";
          referenceSource = bps.source.referenceUrl;
          sourceUrl = bpsUrl(bps.source, env);
        }
      }

      const text = analysis.status === "valid" ? (analysis.preview || analysis.text) : (analysis.message || "");
      const payload = {
        id,
        title: datasetTitle(dataset),
        text,
        url: datasetPage(dataset) || directCsvUrl,
        metadata: {
          publisher: dataset.publisher ?? null,
          csv_url: sourceUrl,
          landing_url: datasetPage(dataset),
          source,
          reference_source: referenceSource,
          period: dataset.modified ?? dataset.issued ?? "",
          status: analysis.status,
          row_count: analysis.rowCount,
          column_count: analysis.columnCount,
          message: analysis.message ?? "",
        },
      };

      return {
        content: [{ type: "text", text: JSON.stringify(payload) }],
        structuredContent: payload,
      };
    },
  );

  // ── 3. Tool: cari_katalog_data ───────────────────────────────────────────
  server.registerTool(
    "cari_katalog_data",
    {
      description:
        "Mencari dataset publik di Portal Satu Data Aceh berdasarkan kata kunci.\nGunakan alat ini setiap kali pengguna meminta informasi statistik atau data dari Aceh.",
      inputSchema: {
        kata_kunci: z.string().describe("Kata atau frasa pencarian (contoh: 'kemiskinan', 'penduduk', 'sekolah', 'pendidikan')."),
      },
    },
    async ({ kata_kunci }) => {
      if (!allowRequest(env)) {
        return { content: [{ type: "text", text: "Batas permintaan tercapai. Coba lagi beberapa saat." }] };
      }
      const trimmed = asText(kata_kunci).trim();
      if (!trimmed) {
        return { content: [{ type: "text", text: "Kata kunci pencarian tidak boleh kosong." }] };
      }

      let datasets: Dataset[];
      try {
        datasets = await loadCatalog(env);
      } catch {
        return {
          content: [
            { type: "text", text: "Sistem sedang tidak dapat mengakses katalog data.json dari portal." },
          ],
        };
      }

      const matches = matchDatasets(datasets, trimmed);
      if (!matches.length) {
        return {
          content: [
            { type: "text", text: `Tidak ditemukan dataset yang cocok dengan kata kunci: '${trimmed}'` },
          ],
        };
      }

      const hasilPencarian: string[] = [];
      for (const item of matches) {
        const judul = datasetTitle(item);
        const publisherObj = item.publisher && typeof item.publisher === "object"
          ? (item.publisher as Record<string, unknown>)
          : null;
        const penerbit = asText(publisherObj?.name) || "Instansi Tidak Diketahui";
        let linkCsv = csvUrl(item, env);
        if (linkCsv === datasetPage(item)) {
          const found = await findCsvLinkInHtml(linkCsv);
          if (found) linkCsv = found;
        }
        hasilPencarian.push(
          `- **Judul Dataset**: ${judul}\n  **Instansi**: ${penerbit}\n  **Tautan CSV**: ${linkCsv}`,
        );
      }

      return {
        content: [
          {
            type: "text",
            text: "Berikut adalah hasil pencarian teratas:\n\n" + hasilPencarian.join("\n\n"),
          },
        ],
      };
    },
  );

  // ── 4. Tool: baca_isi_csv ────────────────────────────────────────────────
  server.registerTool(
    "baca_isi_csv",
    {
      description:
        "Mengunduh dan membaca isi data numerik dari file CSV berdasarkan URL.\nGunakan alat ini jika Anda (AI) sudah mendapatkan URL CSV dari alat pencarian, dan pengguna meminta Anda menganalisis atau menampilkan angka-angkanya.",
      inputSchema: {
        url: z.string().describe("Tautan langsung ke file CSV (biasanya didapat dari hasil cari_katalog_data)."),
        baris_maksimal: z
          .number()
          .int()
          .min(1)
          .max(50)
          .default(20)
          .describe("Jumlah baris data yang ingin diambil (default 20, max 50)."),
      },
    },
    async ({ url, baris_maksimal = 20 }) => {
      if (!allowRequest(env)) {
        return { content: [{ type: "text", text: "Batas permintaan tercapai. Coba lagi beberapa saat." }] };
      }
      if (!url || typeof url !== "string" || !isPublicHttpsUrl(url)) {
        return {
          content: [
            { type: "text", text: "URL CSV harus menggunakan HTTPS dan alamat publik yang valid." },
          ],
        };
      }
      const limit = Math.max(1, Math.min(baris_maksimal, 50));

      try {
        const result = await fetchCsvFromUrl(url, limit);
        if (result.status !== "valid") {
          return {
            content: [{ type: "text", text: `Data tidak tersedia (${result.status}): ${result.message}` }],
          };
        }
        const infoTambahan = `\n\n*(Catatan: Menampilkan ${Math.min(result.rowCount, limit)} baris pertama dari total ${result.rowCount} baris data)*`;
        return { content: [{ type: "text", text: (result.preview || result.text) + infoTambahan }] };
      } catch (error) {
        return {
          content: [
            {
              type: "text",
              text: error instanceof Error ? error.message : "Gagal mengunduh file CSV dari URL tersebut.",
            },
          ],
        };
      }
    },
  );

  // ── 5. Tool: bandingkan_data ─────────────────────────────────────────────
  server.registerTool(
    "bandingkan_data",
    {
      description:
        "Mengambil data dari DUA sumber (Satu Data Aceh dan BPS) sekaligus dan membandingkan mana yang lebih valid dan terbaru.\n\nGunakan alat ini ketika pengguna meminta data statistik resmi Aceh dan Anda ingin memastikan angka yang paling akurat dan mutakhir.",
      inputSchema: {
        indikator: z.string().describe("Nama indikator statistik (contoh: 'pendidikan', 'kemiskinan', 'IPM', 'pengangguran', 'inflasi', 'PDRB', 'gini', 'stunting', 'padi', 'perikanan')."),
      },
    },
    async ({ indikator }) => {
      if (!allowRequest(env)) {
        return { content: [{ type: "text", text: "Batas permintaan tercapai. Coba lagi beberapa saat." }] };
      }
      const trimmed = asText(indikator).trim();
      if (!trimmed) {
        return { content: [{ type: "text", text: "Nama indikator tidak boleh kosong." }] };
      }

      let datasets: Dataset[] = [];
      try {
        datasets = await loadCatalog(env);
      } catch {
        // Continue with empty datasets
      }

      const bagian: string[] = [];

      // ── Cari di Satu Data Aceh ──
      const hasilSda = matchDatasets(datasets, trimmed);
      let sdaStatus = "tidak_ditemukan";
      let sdaPeriode = "-";
      let sdaBaris = 0;
      let sdaTeks = "";
      let sdaJudul = "-";
      let sdaUrl = "-";

      if (hasilSda.length > 0) {
        const item = hasilSda[0];
        sdaJudul = datasetTitle(item);
        sdaUrl = datasetPage(item) || csvUrl(item, env);
        const directUrl = csvUrl(item, env);
        sdaPeriode = asText(item.modified || item.issued || "-");
        if (directUrl && isPublicHttpsUrl(directUrl)) {
          try {
            const resultSda = await fetchCsvFromUrl(directUrl, 20);
            sdaStatus = resultSda.status;
            sdaBaris = resultSda.rowCount;
            sdaTeks = resultSda.status === "valid" ? (resultSda.preview || resultSda.text) : (resultSda.message || "");
          } catch (e) {
            sdaStatus = "failed";
            sdaTeks = `Gagal mengunduh: ${e instanceof Error ? e.message : "Network error"}`;
          }
        } else {
          sdaStatus = "no_url";
          sdaTeks = "Tidak ada URL CSV tersedia di katalog.";
        }
      }

      bagian.push(
        `## Sumber 1: Portal Satu Data Aceh\n- **Status Data**: \`${sdaStatus}\` | **Baris**: ${sdaBaris} | **Periode**: ${sdaPeriode}\n- **Dataset**: ${sdaJudul}\n- **URL**: ${sdaUrl}\n\n${sdaTeks ? sdaTeks : "_Data tidak tersedia._"}`,
      );

      // ── Cari di BPS langsung ──
      let bpsStatus = "tidak_ditemukan";
      let bpsPeriode = "-";
      let bpsBaris = 0;
      let bpsTeks = "";
      let bpsUrlTampil = "-";
      const domain = env.BPS_DOMAIN || "1100";

      let varInfo: { var: string; label: string } | null = cariVarBpsDariKataKunci(trimmed);
      if (hasilSda.length > 0) {
        const bpsSrc = bpsSource(hasilSda[0], env);
        if (bpsSrc) {
          varInfo = { var: bpsSrc.variable, label: sdaJudul };
        }
      }

      if (varInfo) {
        bpsUrlTampil = `https://webapi.bps.go.id/v1/api/list/model/data/domain/${domain}/var/${varInfo.var}/th/124/key/***`;
        const bpsResult = await fetchFromBpsDirect(
          varInfo.var,
          domain,
          env,
          20,
          (varInfo as { defaultTh?: string }).defaultTh,
        );
        if (bpsResult) {
          const resultBps = bpsResult.analysis;
          bpsStatus = resultBps.status;
          bpsBaris = resultBps.rowCount;
          if (resultBps.status === "valid") {
            bpsTeks = resultBps.preview || resultBps.text;
            const tahunMatches = bpsTeks.match(/\b(20\d{2})\b/g);
            if (tahunMatches && tahunMatches.length > 0) {
              bpsPeriode = tahunMatches.reduce((max, y) => (y > max ? y : max), "0");
            }
          } else {
            bpsTeks = resultBps.message || bpsResult.diagnostic || "Data BPS tidak dapat diambil.";
          }
        } else {
          bpsStatus = "failed";
          bpsTeks = "Gagal menghubungi BPS Web API.";
        }
      } else {
        bpsTeks = `Tidak ditemukan variabel BPS yang dipetakan untuk indikator: '${trimmed}'.\nDaftar indikator yang didukung: pendidikan (RLS/HLS/APS), kemiskinan, IPM, pengangguran, inflasi, PDRB, gini, stunting, padi, sayuran, perikanan, peternakan, dan lainnya.`;
      }

      bagian.push(
        `## Sumber 2: BPS Web API (Domain 1100 – Provinsi Aceh)\n- **Status Data**: \`${bpsStatus}\` | **Baris**: ${bpsBaris} | **Tahun Terbaru Terdeteksi**: ${bpsPeriode}\n- **Indikator BPS**: ${varInfo ? varInfo.label : "-"} (var: ${varInfo ? varInfo.var : "-"})\n- **Endpoint**: \`${bpsUrlTampil}\`\n\n${bpsTeks ? bpsTeks : "_Data tidak tersedia._"}`,
      );

      // ── Kesimpulan ──
      let rekomendasi = "";
      if (sdaStatus === "valid" && bpsStatus === "valid") {
        const tahunSdaMatches = (sdaPeriode + " " + sdaTeks).match(/\b(20\d{2})\b/g) || [];
        const tahunBpsMatches = bpsPeriode.match(/\b(20\d{2})\b/g) || [];
        const maxSda = tahunSdaMatches.reduce((max, y) => (y > max ? y : max), "0");
        const maxBps = tahunBpsMatches.reduce((max, y) => (y > max ? y : max), "0");
        if (maxBps >= maxSda && maxBps !== "0") {
          rekomendasi = `✅ **BPS** menyediakan data hingga tahun **${maxBps}** (lebih baru atau setara). Gunakan data BPS sebagai referensi utama.`;
        } else if (maxSda !== "0") {
          rekomendasi = `✅ **Satu Data Aceh** menyediakan data hingga tahun **${maxSda}** (lebih baru). Gunakan data portal sebagai referensi utama.`;
        } else {
          rekomendasi = "✅ Kedua sumber memiliki data valid. Gunakan data BPS sebagai referensi standar statistik.";
        }
      } else if (bpsStatus === "valid") {
        rekomendasi = "✅ Hanya **BPS** yang memiliki data valid. Gunakan data BPS.";
      } else if (sdaStatus === "valid") {
        rekomendasi = "✅ Hanya **Satu Data Aceh** yang memiliki data valid. Gunakan data portal.";
      } else {
        rekomendasi = "⚠️ Kedua sumber tidak memiliki data yang valid untuk indikator ini. Periksa ketersediaan dataset di portal atau periksa BPS API Key Anda.";
      }

      const kesimpulan = `---\n## Kesimpulan Perbandingan\n${rekomendasi}`;
      return { content: [{ type: "text", text: bagian.join("\n\n---\n\n") + "\n\n" + kesimpulan }] };
    },
  );

  return server;
}

async function handleMcp(request: Request, env: Env): Promise<Response> {
  const server = createServer(env);
  const transport = new WebStandardStreamableHTTPServerTransport({ sessionIdGenerator: undefined });
  await server.connect(transport);
  return transport.handleRequest(request);
}

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const url = new URL(request.url);
    if (url.pathname === "/health" && request.method === "GET") {
      return Response.json({ status: "ok", service: "satu-data-aceh-mcp-worker" });
    }
    if (url.pathname !== "/mcp") return new Response("Not found", { status: 404 });
    if (!allowRequest(env)) return Response.json({ error: "Rate limit exceeded" }, { status: 429 });
    try {
      return await handleMcp(request, env);
    } catch (error) {
      console.error("MCP request failed", error);
      return Response.json({ error: "MCP request failed" }, { status: 500 });
    }
  },
};
