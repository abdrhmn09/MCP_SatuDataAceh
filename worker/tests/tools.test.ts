import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { InMemoryTransport } from "@modelcontextprotocol/sdk/inMemory.js";
import { afterEach, expect, it, vi } from "vitest";
import { createServer, type Env } from "../src/index";

afterEach(() => vi.unstubAllGlobals());

it("MCP comparison rejects mismatched units using actual BPS labels and observation years", async () => {
  const env: Env = { CATALOG_URL: "https://example.com/tools-catalog.json", DATA_YEAR: "2025", CATALOG_TTL_SECONDS: "60", MAX_REQUESTS_PER_MINUTE: "2", BPS_API_KEY: "test-secret" };
  const id = "0116d97b-1b4a-4c6a-a243-33833660fb85";
  let portalEmpty = false;
  vi.stubGlobal("fetch", vi.fn(async (url: string) => {
    if (url === env.CATALOG_URL) return new Response(JSON.stringify({ dataset: [{ identifier: id, title: "Garis Kemiskinan Aceh", modified: "2099-01-01", landingPage: `https://satudata.acehprov.go.id/datasets/${id}` }] }));
    if (url.includes("webapi.bps.go.id")) return new Response(JSON.stringify({ status: "OK", data: [{ kode_wilayah: "1101", tahun: 2024, indikator: "Persentase Penduduk Miskin", nilai: 12, satuan: "Persen" }] }));
    return new Response(portalEmpty ? "tahun,nilai\n" : "tahun,nilai,satuan\n2023,100,Rupiah/Kapita/Bulan\n");
  }));
  const server = createServer(env, "mcp-regression");
  const client = new Client({ name: "test", version: "1.0" });
  const [clientTransport, serverTransport] = InMemoryTransport.createLinkedPair();
  await server.connect(serverTransport);
  await client.connect(clientTransport);
  try {
    expect((await client.listTools()).tools).toHaveLength(5);
    const comparison = await client.callTool({ name: "bandingkan_data", arguments: { indikator: "kemiskinan" } });
    expect((comparison.structuredContent as { comparability_status: string }).comparability_status).toBe("incomparable");
    const text = JSON.stringify(comparison);
    expect(text).toContain("Persentase Penduduk Miskin");
    expect(text).toContain("2023");
    expect(text).not.toContain("tahun **2099");
    expect(text).not.toContain("test-secret");
    portalEmpty = true;
    const fallback = await client.callTool({ name: "fetch", arguments: { id } });
    const payload = fallback.structuredContent as { metadata: { source: string; csv_url: string } };
    expect(payload.metadata.source).toBe("BPS");
    expect(payload.metadata.csv_url).not.toContain("test-secret");
    expect(payload.metadata.csv_url).not.toContain("/th/");
    // Initialization and listTools did not consume tool quota, nor were tool calls double-counted.
    const limited = await client.callTool({ name: "search", arguments: { query: "kemiskinan" } });
    expect(limited.isError).toBe(true);
  } finally {
    await client.close();
    await server.close();
  }
});
