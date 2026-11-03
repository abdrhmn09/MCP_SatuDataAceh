import { proxyAccount, resolveAccount } from "./accounts";
import { endpointCatalog, executeBps } from "./bps-api";
import searchSynonyms from "../../src/search_rules.json";
import { isPublicHttpsUrl, readPublicText, redactSecrets } from "./http";
import { parseCsv, encodeCsv, observationMetadata } from "./csv";
import { compareIndicators } from "./comparison";
export { isPublicHttpsUrl } from "./http";
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
  ACCOUNTS_SERVICE_URL?: string;
  ACCOUNTS_SERVICE_SECRET?: string;
  ASSETS?: { fetch(request: Request): Promise<Response> };
  CATALOG_URL: string;
  DATA_YEAR: string;
  CATALOG_TTL_SECONDS: string;
  MAX_REQUESTS_PER_MINUTE: string;
  BPS_API_KEY?: string;
  BPS_SDGS_TOKEN?: string;
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
  status: "valid" | "header_only" | "empty" | "html" | "invalid";
  observationStart?: string;
  observationEnd?: string;
  unit?: string;
  indicator?: string;
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
  label?: string;
  defaultTh?: string;
}

const MAX_CSV_BYTES = 5 * 1024 * 1024;
const MAX_HTML_BYTES = 2 * 1024 * 1024;
const MAX_ROWS = 50;
const cache = new Map<string, { expiresAt: number; fetchedAt: number; stale: boolean; datasets: Dataset[] }>();
const requestTimes = new Map<string, number[]>();

function envInt(value: string | undefined, fallback: number): number {
  const parsed = Number.parseInt(value ?? "", 10);
  return Number.isFinite(parsed) ? parsed : fallback;
}

export function allowRequest(env: Env, clientKey = "local"): boolean {
  const limit = Math.max(1, envInt(env.MAX_REQUESTS_PER_MINUTE, 60));
  const now = Date.now();
  if (!requestTimes.has(clientKey)) {
    for (const [key, times] of requestTimes) if (!times.length || now - times[times.length - 1] >= 60_000) requestTimes.delete(key);
    if (requestTimes.size >= 10_000) return false;
    requestTimes.set(clientKey, []);
  }
  const times = requestTimes.get(clientKey)!;
  while (times.length && now - times[0] >= 60_000) times.shift();
  if (times.length >= limit) return false;
  times.push(now);
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
        return `https://satudata.acehprov.go.id/api/datasets/${id}/datasources/download`;
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
  let variable = mapping && typeof mapping === "object" && !Array.isArray(mapping) && typeof mapping[identifier] === "string" ? mapping[identifier] : "";
  if (!variable && identifier in BPS_INDICATOR_MAP) {
    variable = BPS_INDICATOR_MAP[identifier].var;
  }
  if (!variable) return null;
  const domain = env.BPS_DOMAIN || "1100";
  return {
    domain,
    variable,
    referenceUrl: `https://webapi.bps.go.id/`,
    label: BPS_INDICATOR_MAP[identifier]?.var === variable ? BPS_INDICATOR_MAP[identifier].label : "",
    defaultTh: BPS_INDICATOR_MAP[identifier]?.defaultTh,
  };
}

export function bpsUrl(source: BpsSource, env: Env, thParam: string = "124"): string {
  return `https://webapi.bps.go.id/v1/api/list/model/data/domain/${encodeURIComponent(source.domain)}/var/${encodeURIComponent(source.variable)}${thParam ? `/th/${encodeURIComponent(thParam)}` : ""}/key/${encodeURIComponent(env.BPS_API_KEY || "")}/`;
}

export async function fetchBpsJson(
  url: string,
): Promise<{ ok: boolean; payload?: unknown; status?: number; error?: string }> {
  try {
    const textBody = await readPublicText(url, MAX_CSV_BYTES);
    const response = { status: 200 };
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
        error: "Respons JSON BPS tidak valid.",
      };
    }
  } catch (error) {
    return {
      ok: false,
      error: "Gagal terhubung ke BPS Web API.",
    };
  }
}

export async function fetchFromBps(dataset: Dataset, env: Env): Promise<{ analysis: CsvAnalysis; source: BpsSource; url: string } | null> {
  const source = bpsSource(dataset, env);
  if (!source || !env.BPS_API_KEY) return null;
  const thCandidates = ["", ...new Set([source.defaultTh || "124", "124", "123", "122"])];
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
    return { analysis: analyzeCsvText(text, MAX_ROWS), source, url: redactSecrets(url) };
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
  const thCandidates = ["", ...new Set([preferredTh || "124", "124", "123", "122"])];
  let lastDiag = "Data tidak ditemukan di BPS.";
  let lastUrl = `https://webapi.bps.go.id/v1/api/list/model/data/domain/${encodeURIComponent(domain)}/var/${encodeURIComponent(varId)}/th/124/key/***/`;

  for (const th of thCandidates) {
    const url = `https://webapi.bps.go.id/v1/api/list/model/data/domain/${encodeURIComponent(domain)}/var/${encodeURIComponent(varId)}${th ? `/th/${encodeURIComponent(th)}` : ""}/key/${encodeURIComponent(env.BPS_API_KEY)}/`;
    lastUrl = redactSecrets(url);
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
      url: redactSecrets(url),
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

export function catalogStatus(env: Env) {
  const state = cache.get(env.CATALOG_URL);
  return { loaded: Boolean(state), source: state ? state.stale ? "stale" : "remote" : "unavailable",
    stale: Boolean(state && (state.stale || state.expiresAt <= Date.now())),
    dataset_count: state?.datasets.length || 0, last_success_at: state ? state.fetchedAt / 1000 : null };
}

const catalogFailures = new Map<string, number>();
const catalogLoads = new Map<string, Promise<Dataset[]>>();
export async function loadCatalog(env: Env): Promise<Dataset[]> {
  const now = Date.now();
  const cached = cache.get(env.CATALOG_URL);
  if (!cached && (catalogFailures.get(env.CATALOG_URL) || 0) > now) throw new Error("Katalog tidak dapat diakses; coba kembali setelah jeda retry.");
  if (cached && cached.expiresAt > now) return cached.datasets;
  const pending = catalogLoads.get(env.CATALOG_URL);
  if (pending) return pending;
  const load = (async () => {
    try {
      const payload = JSON.parse(await readPublicText(env.CATALOG_URL, 32 * 1024 * 1024)) as CatalogResponse;
      if (!Array.isArray(payload.dataset) || !payload.dataset.every(item => item && typeof item === "object" && !Array.isArray(item)))
        throw new Error("Format katalog tidak valid.");
      const datasets = payload.dataset as Dataset[];
      cache.set(env.CATALOG_URL, { expiresAt: Date.now() + Math.max(60, envInt(env.CATALOG_TTL_SECONDS, 3600)) * 1000, fetchedAt: Date.now(), stale: false, datasets });
      catalogFailures.delete(env.CATALOG_URL);
      return datasets;
    } catch {
      catalogFailures.set(env.CATALOG_URL, Date.now() + 30_000);
      if (cached) {
        // Short retry delay prevents every client retrying an unavailable upstream.
        cache.set(env.CATALOG_URL, { ...cached, stale: true, expiresAt: Date.now() + 30_000 });
        console.warn("Catalog unavailable; serving stale cached catalog");
        return cached.datasets;
      }
      throw new Error("Katalog tidak dapat diakses.");
    }
  })();
  catalogLoads.set(env.CATALOG_URL, load);
  try { return await load; } finally { catalogLoads.delete(env.CATALOG_URL); }
}

function normalizeTerms(query: string): string[] {
  const normalized = query.toLowerCase().trim();
  const synonyms: Record<string, string[]> = searchSynonyms;
  const terms = new Set<string>(normalized ? [normalized] : []);
  for (const token of normalized.split(/\s+/).filter(token => token.length > 1)) {
    terms.add(token);
    for (const syn of synonyms[token] ?? []) terms.add(syn);
  }
  return [...terms];
}

export function matchDatasets(datasets: Dataset[], query: string, maxResults = 5): Dataset[] {
  const normalized = query.trim().toLowerCase();
  if (!normalized) return [];
  const terms = normalizeTerms(query);
  const scored: { score: number; dataset: Dataset }[] = [];
  for (const dataset of datasets) {
    const title = asText(dataset.title).toLowerCase();
    const desc = asText(dataset.description).toLowerCase();
    const keywords = Array.isArray(dataset.keyword) ? dataset.keyword.filter((v): v is string => typeof v === "string").map(v => v.toLowerCase()) : [];
    const publisher = dataset.publisher && typeof dataset.publisher === "object" ? asText((dataset.publisher as Record<string, unknown>).name).toLowerCase() : "";
    let score = title.includes(normalized) ? 40 : 0;
    for (const term of terms) {
      if (title.includes(term)) score += 12;
      if (keywords.some(keyword => keyword.includes(term))) score += 6;
      if (desc.includes(term)) score += 2;
      if (publisher.includes(term)) score += 2;
    }
    if (!score) continue;
    const curated = BPS_INDICATOR_MAP[datasetId(dataset)];
    if (curated) { score += 10; if (normalized.includes(curated.category)) score += 40; }
    if (["bps", "badan pusat statistik", "bappeda"].some(term => publisher.includes(term))) score += 5;
    if (title.includes("aceh")) score += 8;
    if (title.includes("kabupaten") || title.includes("kota")) score += 4;
    if ((title.includes("nasional") || title.includes("indonesia")) && !normalized.includes("nasional") && !normalized.includes("indonesia")) score -= 20;
    if (title.includes("miskin") && !normalized.includes("miskin") && !normalized.includes("kemiskinan")) score -= 25;
    if (title.includes("jumlah penduduk") && normalized.includes("penduduk") && !normalized.includes("miskin") && !normalized.includes("kemiskinan") &&
        !["berumur", "bekerja", "angkatan kerja", "pekerjaan", "status kawin", "agama", "golongan darah", "disabilitas", "jenjang pendidikan"].some(term => title.includes(term))) score += 35;
    for (const term of ["paud", "sop", "aktivitas", "rutin", "penyelenggaraan", "tata kelola", "belanja", "barang jasa", "pengadaan"])
      if (title.includes(term) && !normalized.includes(term)) score -= 30;
    scored.push({ score, dataset });
  }
  return scored.sort((a, b) => b.score - a.score).slice(0, maxResults).map(item => item.dataset);
}

export function searchCatalog(datasets: Dataset[], query: string, wilayah = "", produsen = "", limit = 5, offset = 0) {
  if (!Number.isInteger(limit) || limit < 1 || limit > 50 || !Number.isInteger(offset) || offset < 0) throw new Error("limit harus 1–50 dan offset nonnegatif.");
  const filtered = datasets.filter(dataset => {
    const text = [dataset.title, dataset.description, dataset.keyword].map(asText).join(" ").toLowerCase();
    const publisher = dataset.publisher && typeof dataset.publisher === "object" ? asText((dataset.publisher as Record<string, unknown>).name) : "";
    return text.includes(wilayah.trim().toLowerCase()) && publisher.toLowerCase().includes(produsen.trim().toLowerCase());
  });
  const matches = matchDatasets(filtered, query, filtered.length);
  return { results: matches.slice(offset, offset + limit).map(dataset => ({ id: datasetId(dataset), title: datasetTitle(dataset), url: datasetPage(dataset) || datasetId(dataset) })),
    total: matches.length, offset, next_offset: offset + limit < matches.length ? offset + limit : null };
}

export function searchDatasets(datasets: Dataset[], query: string): SearchResult[] {
  return matchDatasets(datasets, query).map((dataset) => ({
    id: datasetId(dataset),
    title: datasetTitle(dataset),
    url: datasetPage(dataset) || datasetId(dataset),
  }));
}

export function csvToMarkdownTable(csvText: string, maxRows: number): string {
  const rows = parseCsv(csvText);
  if (!rows.length) return "";
  const escape = (cell: string) => cell.replaceAll("|", "\\|").replace(/\r?\n/g, "<br>");
  return [rows[0], rows[0].map(() => "---"), ...rows.slice(1, Math.max(1, Math.min(maxRows, MAX_ROWS)) + 1)]
    .map(row => `| ${row.map(escape).join(" | ")} |`).join("\n");
}

export function parseCsvRows(text: string, maxRows: number): string {
  return encodeCsv(parseCsv(text).slice(0, Math.max(1, Math.min(maxRows, MAX_ROWS)) + 1));
}

export function analyzeCsvText(text: string, maxRows: number): CsvAnalysis {
  const cleaned = text.replace(/^\uFEFF/, "").trim();
  const empty = { text: "", preview: "", rowCount: 0, columnCount: 0 };
  if (!cleaned) return { ...empty, status: "empty", message: "File CSV tidak berisi data." };
  if (cleaned.startsWith("<") && cleaned.slice(0, 500).toLowerCase().includes("html"))
    return { ...empty, status: "html", message: "Sumber mengembalikan HTML, bukan CSV." };
  try {
    const rows = parseCsv(cleaned);
    const rowCount = rows.length - 1, columnCount = rows[0].length;
    if (!rowCount) return { ...empty, columnCount, status: "header_only", message: "CSV hanya berisi header." };
    return { status: "valid", text: parseCsvRows(cleaned, maxRows), preview: csvToMarkdownTable(cleaned, maxRows),
      rowCount, columnCount, ...observationMetadata(rows) };
  } catch {
    return { ...empty, status: "invalid", message: "Format CSV tidak valid." };
  }
}

export async function fetchCsvFromUrl(url: string, maxRows: number): Promise<CsvAnalysis> {
  return analyzeCsvText(await readPublicText(url, MAX_CSV_BYTES), maxRows);
}

export async function findCsvLinkInHtml(pageUrl: string): Promise<string | null> {
  if (!isPublicHttpsUrl(pageUrl)) return null;
  try {
    const html = await readPublicText(pageUrl, MAX_HTML_BYTES);
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

export function createServer(env: Env, clientKey = "local"): McpServer {
  const server = new McpServer({
    name: "Satu Data Aceh Server",
    version: "0.2.0",
  });

  const response = (payload: Record<string, unknown>) => ({ content: [{ type: "text" as const, text: JSON.stringify(payload) }], structuredContent: payload });
  server.registerTool("bps_endpoints", {
    description: "Daftar 59 operasi resmi BPS pada semua domain; isi operation untuk skema parameter lengkap. Tidak memerlukan API key.",
    inputSchema: { operation: z.string().max(100).default(""), query: z.string().max(200).default("") },
  }, async ({ operation, query }) => {
    if (!allowRequest(env, clientKey)) return response({ error: "rate_limited" });
    return response(endpointCatalog(operation, query));
  });
  server.registerTool("bps_request", {
    description: "Jalankan operasi read-only BPS pada semua domain. Cari operation/parameters melalui bps_endpoints. Key berasal dari header koneksi, bukan argumen tool. Respons mempertahankan pagination dan dimensi BPS.",
    inputSchema: { operation: z.string().max(100), parameters: z.record(z.union([z.string().max(500), z.number().int()])).default({}) },
  }, async ({ operation, parameters }) => {
    if (!allowRequest(env, clientKey)) return response({ error: "rate_limited" });
    try { return response(await executeBps(operation, parameters, env.BPS_SDGS_TOKEN ? new Headers({ "X-BPS-SDGS-Token": env.BPS_SDGS_TOKEN }) : new Headers(), env.BPS_API_KEY)); }
    catch (error) { return response({ ok: false, message: error instanceof Error ? error.message : "Permintaan tidak valid." }); }
  });
  server.registerTool("bps_check_key", {
    description: "Validasi credential koneksi ke BPS atau SDGs tanpa menyimpan atau menampilkan key.",
    inputSchema: { service: z.enum(["bps", "sdgs"]).default("bps") },
  }, async ({ service }) => {
    if (!allowRequest(env, clientKey)) return response({ error: "rate_limited" });
    try {
      const headers = new Headers();
      if (env.BPS_SDGS_TOKEN) headers.set("X-BPS-SDGS-Token", env.BPS_SDGS_TOKEN);
      const result = await executeBps(service === "bps" ? "listDomains" : "getSdgsHome", service === "bps" ? { type: "all" } : {}, headers, env.BPS_API_KEY);
      return response({ ok: result.ok, service, message: result.ok ? "Credential diterima BPS." : "Credential belum dapat diverifikasi." });
    } catch { return response({ ok: false, service, message: "Credential belum tersedia atau tidak valid." }); }
  });

  // ── 1. Tool: search ───────────────────────────────────────────────────────
  server.registerTool(
    "search",
    {
      description: "Mencari dataset Aceh dan mengembalikan hasil dengan URL yang dapat dikutip.",
      inputSchema: {
        query: z.string().max(500).describe("Kata kunci pencarian dataset"),
        wilayah: z.string().max(200).default("").describe("Filter wilayah pada metadata katalog"),
        produsen: z.string().max(200).default("").describe("Filter nama produsen"),
        limit: z.number().int().min(1).max(50).default(5),
        offset: z.number().int().min(0).default(0),
      },
    },
    async ({ query, wilayah = "", produsen = "", limit = 5, offset = 0 }) => {
      if (!allowRequest(env, clientKey)) {
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
      const payload = searchCatalog(datasets, trimmed, wilayah, produsen, limit, offset);
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
      if (!allowRequest(env, clientKey)) {
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
          sourceUrl = bps.url;
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
          catalog: catalogStatus(env),
          csv_url: redactSecrets(sourceUrl),
          landing_url: datasetPage(dataset),
          source,
          reference_source: referenceSource,
          period: analysis.observationEnd || "",
          observation_start: analysis.observationStart || "",
          observation_end: analysis.observationEnd || "",
          satuan: analysis.unit || "",
          indikator_bps: analysis.indicator || "",
          published_at: dataset.issued ?? "",
          modified_at: dataset.modified ?? "",
          retrieved_at: new Date().toISOString(),
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
      if (!allowRequest(env, clientKey)) {
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
      if (!allowRequest(env, clientKey)) {
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
      if (!allowRequest(env, clientKey)) {
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
      hasilSda.sort((a, b) => Number(Boolean(bpsSource(b, env))) - Number(Boolean(bpsSource(a, env))));
      if (!hasilSda.some(item => bpsSource(item, env))) {
        const mapped = datasets.find(item => BPS_INDICATOR_MAP[datasetId(item)] && matchDatasets([item], trimmed).length);
        if (mapped) hasilSda.unshift(mapped);
      }
      let sdaStatus = "tidak_ditemukan";
      let sdaPeriode = "-";
      let sdaBaris = 0;
      let sdaTeks = "";
      let sdaJudul = "-";
      let sdaUrl = "-";
      let sdaAnalysis: CsvAnalysis | undefined;
      let bpsAnalysis: CsvAnalysis | undefined;

      let selectedSda: Dataset | undefined;
      for (const item of hasilSda.slice(0, 3)) {
        const directUrl = csvUrl(item, env);
        if (!directUrl || !isPublicHttpsUrl(directUrl)) continue;
        let result: CsvAnalysis;
        try { result = await fetchCsvFromUrl(directUrl, 20); }
        catch { result = { status: "invalid", text: "", preview: "", rowCount: 0, columnCount: 0, message: "Gagal mengunduh CSV portal." }; }
        if (!selectedSda || result.status === "valid") {
          selectedSda = item;
          sdaAnalysis = result;
          sdaJudul = datasetTitle(item);
          sdaUrl = datasetPage(item) || directUrl;
          sdaPeriode = result.observationEnd || "-";
          sdaStatus = result.status;
          sdaBaris = result.rowCount;
          sdaTeks = result.status === "valid" ? result.preview || result.text : result.message || "";
        }
        if (result.status === "valid") break;
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

      let varInfo: { var: string; label: string; defaultTh?: string } | null = cariVarBpsDariKataKunci(trimmed);
      if (selectedSda) {
        const bpsSrc = bpsSource(selectedSda, env);
        if (bpsSrc) {
          varInfo = { var: bpsSrc.variable, label: bpsSrc.label || "", defaultTh: bpsSrc.defaultTh };
        }
      }

      if (varInfo) {
        bpsUrlTampil = `https://webapi.bps.go.id/v1/api/list/model/data/domain/${encodeURIComponent(domain)}/var/${encodeURIComponent(varInfo.var)}/key/***`;
        const bpsResult = await fetchFromBpsDirect(
          varInfo.var,
          domain,
          env,
          20,
          (varInfo as { defaultTh?: string }).defaultTh,
        );
        if (bpsResult) {
          const resultBps = bpsResult.analysis;
          bpsAnalysis = resultBps;
          if (resultBps.indicator) varInfo.label = resultBps.indicator;
          bpsStatus = !env.BPS_API_KEY ? "api_key_tidak_ada" : resultBps.status;
          bpsBaris = resultBps.rowCount;
          if (resultBps.status === "valid") {
            bpsTeks = resultBps.preview || resultBps.text;
            bpsPeriode = resultBps.observationEnd || "-";
          } else {
            bpsTeks = resultBps.message || bpsResult.diagnostic || "Data BPS tidak dapat diambil.";
          }
        } else {
          bpsStatus = "failed";
          bpsTeks = "Gagal menghubungi BPS Web API.";
        }
      } else {
        bpsTeks = `Tidak ditemukan variabel BPS yang dipetakan untuk indikator: '${trimmed}'.\nDaftar indikator yang didukung: pendidikan (RLS/HLS/APS), kemiskinan, IPM, pengangguran, inflasi, PDRB, gini, padi, dan sayuran.`;
      }

      bagian.push(
        `## Sumber 2: BPS Web API (Domain ${domain})\n- **Status Data**: \`${bpsStatus}\` | **Baris**: ${bpsBaris} | **Tahun Terbaru Terdeteksi**: ${bpsPeriode}\n- **Indikator BPS**: ${varInfo ? varInfo.label : "-"} (var: ${varInfo ? varInfo.var : "-"})\n- **Endpoint**: \`${bpsUrlTampil}\`\n\n${bpsTeks ? bpsTeks : "_Data tidak tersedia._"}`,
      );

      const comparison = compareIndicators(sdaJudul, varInfo?.label || "", sdaAnalysis?.unit, bpsAnalysis?.unit);
      let rekomendasi = "";
      if (sdaStatus === "valid" && bpsStatus === "valid") {
        if (comparison.status !== "comparable") {
          rekomendasi = `⚠️ **${comparison.status === "incomparable" ? "Incomparable (Tidak Sepadan)" : "Kesepadanan Belum Dapat Dipastikan"}**: ${comparison.reason}`;
        } else {
          const maxSda = sdaAnalysis?.observationEnd || "";
          const maxBps = bpsAnalysis?.observationEnd || "";
          rekomendasi = !maxSda || !maxBps ? "Tahun observasi belum cukup untuk menentukan sumber terbaru."
            : maxBps > maxSda ? `BPS memiliki observasi lebih baru (${maxBps}); portal hingga ${maxSda}.`
            : maxSda > maxBps ? `Satu Data Aceh memiliki observasi lebih baru (${maxSda}); BPS hingga ${maxBps}.`
            : `Kedua sumber memiliki tahun observasi terbaru yang sama (${maxSda}).`;
          rekomendasi += ` ${comparison.reason}`;
        }
      } else if (bpsStatus === "valid") rekomendasi = "Hanya BPS yang memiliki data yang berhasil dibaca; kesepadanan kedua sumber belum dapat dinilai.";
      else if (sdaStatus === "valid") rekomendasi = "Hanya Satu Data Aceh yang memiliki data yang berhasil dibaca; kesepadanan kedua sumber belum dapat dinilai.";
      else rekomendasi = "Kedua sumber belum menyediakan observasi yang dapat dibaca untuk indikator ini.";

      const kesimpulan = `---\n## Kesimpulan Perbandingan\n${rekomendasi}`;
      return { content: [{ type: "text", text: bagian.join("\n\n---\n\n") + "\n\n" + kesimpulan }],
        structuredContent: { comparability_status: sdaStatus === "valid" && bpsStatus === "valid" ? comparison.status : "unknown", reason: comparison.reason,
          sources: { sda: { status: sdaStatus, observation_end: sdaAnalysis?.observationEnd || "", unit: sdaAnalysis?.unit || "" },
            bps: { status: bpsStatus, observation_end: bpsAnalysis?.observationEnd || "", unit: bpsAnalysis?.unit || "" } } } };
    },
  );

  return server;
}

async function handleMcp(request: Request, env: Env): Promise<Response> {
  const user = await resolveAccount(request, env);
  if (!user) return Response.json({ error: "unauthorized", message: "Gunakan token MCP dari dashboard akun." }, { status: 401, headers: { "WWW-Authenticate": 'Bearer realm="MCP Satu Data Aceh"' } });
  const scopedEnv = { ...env, BPS_API_KEY: user.bps, BPS_SDGS_TOKEN: user.sdgs };
  const server = createServer(scopedEnv, user.id);
  const transport = new WebStandardStreamableHTTPServerTransport({ sessionIdGenerator: undefined });
  await server.connect(transport);
  return transport.handleRequest(request);
}

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const url = new URL(request.url);
    if (url.pathname === "/health" && request.method === "GET") {
      return Response.json({ status: "ok", service: "satu-data-aceh-mcp-worker", catalog: catalogStatus(env) });
    }
    if (url.pathname.startsWith("/api/account/")) {
      try { return await proxyAccount(request, env); }
      catch { return Response.json({ error: "account_service_unavailable" }, { status: 503 }); }
    }
    if (url.pathname === "/api/bps/endpoints" && request.method === "GET") {
      try { return Response.json(endpointCatalog(url.searchParams.get("operation") || "", url.searchParams.get("query") || ""), { headers: { "Cache-Control": "no-store" } }); }
      catch { return Response.json({ error: "Operasi tidak dikenal." }, { status: 400 }); }
    }
    if (url.pathname === "/api/bps" && request.method === "POST") {
      if (!allowRequest(env, request.headers.get("CF-Connecting-IP") || "local")) return Response.json({ error: "rate_limited" }, { status: 429 });
      try {
        let size = 0, text = "";
        const reader = request.body?.getReader();
        if (!reader) throw new Error("Body wajib diisi.");
        const decoder = new TextDecoder();
        try { while (true) { const chunk = await reader.read(); if (chunk.done) break; size += chunk.value.byteLength; if (size > 16_384) throw new Error("Body terlalu besar."); text += decoder.decode(chunk.value, { stream: true }); } text += decoder.decode(); }
        finally { await reader.cancel(); }
        const body = JSON.parse(text);
        const user = await resolveAccount(request, env, "session");
        if (!user) return Response.json({ error: "login_required" }, { status: 401 });
        const headers = new Headers();
        if (user.sdgs) headers.set('X-BPS-SDGS-Token',user.sdgs);
        return Response.json(await executeBps(body.operation, body.parameters || {}, headers, user.bps), { headers: { "Cache-Control": "no-store" } });
      } catch { return Response.json({ ok: false, message: "Permintaan atau credential tidak valid." }, { status: 400, headers: { "Cache-Control": "no-store" } }); }
    }
    if (request.method === "GET" && !url.pathname.startsWith("/mcp") && env.ASSETS) return env.ASSETS.fetch(request);
    if (url.pathname !== "/mcp") return new Response("Not found", { status: 404 });
    try {
      return await handleMcp(request, env);
    } catch (error) {
      console.error("MCP request failed");
      return Response.json({ error: "account_service_unavailable" }, { status: 503 });
    }
  },
};
