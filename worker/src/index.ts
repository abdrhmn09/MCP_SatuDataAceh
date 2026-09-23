import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { WebStandardStreamableHTTPServerTransport } from "@modelcontextprotocol/sdk/server/webStandardStreamableHttp.js";
import { z } from "zod";

interface Env {
  CATALOG_URL: string;
  DATA_YEAR: string;
  CATALOG_TTL_SECONDS: string;
  MAX_REQUESTS_PER_MINUTE: string;
  BPS_API_KEY?: string;
  BPS_DOMAIN?: string;
  BPS_DATASET_MAP?: string;
}

interface Dataset {
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

interface CatalogResponse {
  dataset?: unknown;
}

interface SearchResult {
  id: string;
  title: string;
  url: string;
}

interface CsvAnalysis {
  status: "valid" | "header_only" | "empty" | "html";
  text: string;
  rowCount: number;
  columnCount: number;
  message?: string;
}

interface BpsSource {
  domain: string;
  variable: string;
  referenceUrl: string;
}

const MAX_CSV_BYTES = 5 * 1024 * 1024;
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
      "127.0.0.1",
      "::1",
      "0.0.0.0",
      "169.254.169.254",
    ].includes(hostname);
  } catch {
    return false;
  }
}

function allowRequest(env: Env): boolean {
  const limit = Math.max(1, envInt(env.MAX_REQUESTS_PER_MINUTE, 60));
  const now = Date.now();
  while (requestTimes.length && now - requestTimes[0] >= 60_000) requestTimes.shift();
  if (requestTimes.length >= limit) return false;
  requestTimes.push(now);
  return true;
}

function asText(value: unknown): string {
  return typeof value === "string" ? value : value == null ? "" : String(value);
}

function datasetId(dataset: Dataset): string {
  return asText(dataset.identifier).trim();
}

function datasetTitle(dataset: Dataset): string {
  return asText(dataset.title) || "Dataset Aceh";
}

function datasetPage(dataset: Dataset): string {
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

function csvUrl(dataset: Dataset, env: Env): string {
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

function bpsSource(dataset: Dataset, env: Env): BpsSource | null {
  const identifier = datasetId(dataset);
  let mapping: Record<string, string> = {};
  try {
    mapping = JSON.parse(env.BPS_DATASET_MAP || "{}") as Record<string, string>;
  } catch {
    return null;
  }
  const variable = mapping[identifier] || (identifier === "621" ? "621" : "");
  if (!variable) return null;
  const domain = env.BPS_DOMAIN || "1100";
  return {
    domain,
    variable,
    referenceUrl: datasetPage(dataset),
  };
}

function bpsUrl(source: BpsSource, env: Env): string {
  return `https://webapi.bps.go.id/v1/api/list/model/data/domain/${encodeURIComponent(source.domain)}/var/${encodeURIComponent(source.variable)}/key/${encodeURIComponent(env.BPS_API_KEY || "")}/`;
}

function bpsPayloadToText(payload: unknown): string {
  const root = payload && typeof payload === "object" ? payload as Record<string, unknown> : {};

  // ── Format 1: Dynamic Data BPS (datacontent matriks multidimensi) ──────────
  if ("datacontent" in root && typeof root.datacontent === "object" && root.datacontent !== null) {
    const datacontent = root.datacontent as Record<string, number>;
    const varList = Array.isArray(root.var) ? root.var as Record<string, unknown>[] : [{}];
    const vervar = Array.isArray(root.vervar) ? root.vervar as Record<string, unknown>[] : [];
    const tahunList = Array.isArray(root.tahun) ? root.tahun as Record<string, unknown>[] : [];
    const turvar = Array.isArray(root.turvar) ? root.turvar as Record<string, unknown>[] : [{ val: 0, label: "" }];
    const turtahun = Array.isArray(root.turtahun) ? root.turtahun as Record<string, unknown>[] : [{ val: 0, label: "Tahunan" }];

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
      const columns = [...new Set(rows.flatMap((r) => Object.keys(r)))];
      const escape = (v: unknown) => `"${asText(v).replaceAll('"', '""')}"`;
      return [columns.map(escape).join(","), ...rows.map((r) => columns.map((c) => escape(r[c])).join(","))].join("\n");
    }
  }

  // ── Format 2: Array list (fallback / static table) ──────────────────────────
  const rows = Array.isArray(root.data) ? root.data :
    root.data && typeof root.data === "object" && Array.isArray((root.data as Record<string, unknown>).data)
      ? (root.data as Record<string, unknown>).data as unknown[] : [];
  if (!rows.length) return "";
  const objects = rows.filter((row): row is Record<string, unknown> => Boolean(row && typeof row === "object"));
  if (!objects.length) return "";
  const columns = [...new Set(objects.flatMap((row) => Object.keys(row)))];
  const escape = (value: unknown) => `"${asText(value).replaceAll('"', '""')}"`;
  return [columns.map(escape).join(","), ...objects.map((row) => columns.map((column) => escape(row[column])).join(","))].join("\n");
}

async function fetchFromBps(dataset: Dataset, env: Env): Promise<{ analysis: CsvAnalysis; source: BpsSource } | null> {
  const source = bpsSource(dataset, env);
  if (!source || !env.BPS_API_KEY) return null;
  try {
    const response = await fetch(bpsUrl(source, env));
    if (!response.ok) return null;
    const text = bpsPayloadToText(await response.json());
    return { analysis: analyzeCsvText(text, MAX_ROWS), source };
  } catch (error) {
    console.error("BPS fallback failed", error instanceof Error ? error.message : "unknown error");
    return null;
  }
}

async function loadCatalog(env: Env): Promise<Dataset[]> {
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

export function searchDatasets(datasets: Dataset[], query: string): SearchResult[] {
  const needle = query.trim().toLowerCase();
  if (!needle) return [];
  const synonyms: Record<string, string[]> = {
    kemiskinan: ["kemiskinan", "miskin", "garis kemiskinan", "penduduk miskin"],
    miskin: ["kemiskinan", "miskin", "penduduk miskin"],
    bps: ["bps", "badan pusat statistik", "susenas"],
  };
  const terms = new Set([needle]);
  for (const token of needle.split(/\s+/)) {
    for (const synonym of synonyms[token] ?? [token]) terms.add(synonym);
  }
  return datasets
    .map((dataset) => {
      const metadata = searchableText(dataset);
      const title = datasetTitle(dataset).toLowerCase();
      const matched = [...terms].filter((term) => metadata.includes(term));
      const score = matched.length + matched.filter((term) => title.includes(term)).length * 2;
      return { dataset, score };
    })
    .filter((entry) => entry.score > 0)
    .sort((left, right) => right.score - left.score)
    .slice(0, 5)
    .map(({ dataset }) => ({
      id: datasetId(dataset),
      title: datasetTitle(dataset),
      url: datasetPage(dataset) || csvUrl(dataset, { DATA_YEAR: "2025" } as Env),
    }));
}

export function parseCsvRows(text: string, maxRows: number): string {
  const lines = text.replace(/^\uFEFF/, "").split(/\r?\n/).filter(Boolean);
  if (!lines.length) return "";
  return lines.slice(0, Math.max(1, Math.min(maxRows, MAX_ROWS)) + 1).join("\n");
}

export function analyzeCsvText(text: string, maxRows: number): CsvAnalysis {
  const cleaned = text.replace(/^\uFEFF/, "").trim();
  if (!cleaned) {
    return { status: "empty", text: "", rowCount: 0, columnCount: 0, message: "File CSV tidak berisi data." };
  }
  if (cleaned.startsWith("<") && cleaned.slice(0, 500).toLowerCase().includes("html")) {
    return { status: "html", text: "", rowCount: 0, columnCount: 0, message: "Sumber mengembalikan HTML, bukan CSV." };
  }
  const lines = cleaned.split(/\r?\n/).filter(Boolean);
  const columnCount = lines[0].split(",").length;
  const rowCount = Math.max(0, lines.length - 1);
  if (rowCount === 0) {
    return { status: "header_only", text: "", rowCount, columnCount, message: "Sumber CSV hanya berisi header tanpa observasi." };
  }
  return { status: "valid", text: parseCsvRows(cleaned, maxRows), rowCount, columnCount };
}

async function fetchDatasetText(dataset: Dataset, env: Env): Promise<CsvAnalysis> {
  const url = csvUrl(dataset, env);
  if (!isPublicHttpsUrl(url)) throw new Error("Dataset URL is not a public HTTPS URL");
  const response = await fetch(url);
  if (!response.ok) throw new Error(`CSV request failed: ${response.status}`);
  const contentLength = Number(response.headers.get("content-length") || 0);
  if (contentLength > MAX_CSV_BYTES) throw new Error("CSV exceeds the 5 MB limit");
  const body = await response.arrayBuffer();
  if (body.byteLength > MAX_CSV_BYTES) throw new Error("CSV exceeds the 5 MB limit");
  return analyzeCsvText(new TextDecoder("utf-8").decode(body), MAX_ROWS);
}

function createServer(env: Env): McpServer {
  const server = new McpServer({ name: "Satu Data Aceh MCP", version: "0.1.0" });
  server.registerTool(
    "search",
    {
      description: "Search public Satu Data Aceh datasets.",
      inputSchema: { query: z.string() },
    },
    async ({ query }) => {
      const datasets = await loadCatalog(env);
      const payload = { results: searchDatasets(datasets, query) };
      return {
        content: [{ type: "text", text: JSON.stringify(payload) }],
        structuredContent: payload,
      };
    },
  );
  server.registerTool(
    "fetch",
    {
      description: "Fetch a CSV dataset preview by identifier.",
      inputSchema: { id: z.string() },
    },
    async ({ id }) => {
      const datasets = await loadCatalog(env);
      const dataset = datasets.find((item) => datasetId(item) === id);
      if (!dataset) throw new Error("Dataset not found");
      let analysis: CsvAnalysis;
      try {
        analysis = await fetchDatasetText(dataset, env);
      } catch (error) {
        analysis = {
          status: "empty",
          text: "",
          rowCount: 0,
          columnCount: 0,
          message: error instanceof Error ? error.message : "Gagal mengunduh file CSV",
        };
      }
      let source = "Satu Data Aceh";
      let referenceSource = datasetPage(dataset);
      let sourceUrl = csvUrl(dataset, env);
      if (analysis.status !== "valid") {
        const bps = await fetchFromBps(dataset, env);
        if (bps) {
          analysis = bps.analysis;
          source = "BPS";
          referenceSource = bps.source.referenceUrl;
          sourceUrl = bpsUrl(bps.source, env);
        }
      }
      const payload = {
        id,
        title: datasetTitle(dataset),
        text: analysis.text || analysis.message || "",
        url: datasetPage(dataset) || csvUrl(dataset, env),
        metadata: {
          publisher: dataset.publisher ?? null,
          source,
          reference_source: referenceSource,
          status: analysis.status,
          row_count: analysis.rowCount,
          column_count: analysis.columnCount,
          source_url: sourceUrl,
          landing_url: datasetPage(dataset),
          period: dataset.modified ?? dataset.issued ?? "",
          message: analysis.message ?? "",
        },
      };
      return {
        content: [{ type: "text", text: JSON.stringify(payload) }],
        structuredContent: payload,
      };
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
