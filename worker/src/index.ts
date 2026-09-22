import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { WebStandardStreamableHTTPServerTransport } from "@modelcontextprotocol/sdk/server/webStandardStreamableHttp.js";
import { z } from "zod";

interface Env {
  CATALOG_URL: string;
  DATA_YEAR: string;
  CATALOG_TTL_SECONDS: string;
  MAX_REQUESTS_PER_MINUTE: string;
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

function csvUrl(dataset: Dataset, env: Env): string {
  const page = datasetPage(dataset);
  try {
    const hostname = new URL(page).hostname;
    if (hostname === "satudata.acehprov.go.id") {
      const id = encodeURIComponent(datasetId(dataset));
      if (id) {
        return `https://satudata.acehprov.go.id/api/datasets/${id}/datasources/download?tahun=${encodeURIComponent(env.DATA_YEAR || "2025")}`;
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
  return datasets
    .filter((dataset) => searchableText(dataset).includes(needle))
    .slice(0, 5)
    .map((dataset) => ({
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

async function fetchDatasetText(dataset: Dataset, env: Env): Promise<string> {
  const url = csvUrl(dataset, env);
  if (!isPublicHttpsUrl(url)) throw new Error("Dataset URL is not a public HTTPS URL");
  const response = await fetch(url);
  if (!response.ok) throw new Error(`CSV request failed: ${response.status}`);
  const contentLength = Number(response.headers.get("content-length") || 0);
  if (contentLength > MAX_CSV_BYTES) throw new Error("CSV exceeds the 5 MB limit");
  const body = await response.arrayBuffer();
  if (body.byteLength > MAX_CSV_BYTES) throw new Error("CSV exceeds the 5 MB limit");
  return parseCsvRows(new TextDecoder("utf-8").decode(body), MAX_ROWS);
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
      const text = await fetchDatasetText(dataset, env);
      const payload = {
        id,
        title: datasetTitle(dataset),
        text,
        url: datasetPage(dataset) || csvUrl(dataset, env),
        metadata: { publisher: dataset.publisher ?? null },
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
