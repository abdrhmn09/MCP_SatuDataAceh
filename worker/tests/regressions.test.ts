import { afterEach, describe, expect, it, vi } from "vitest";
import cases from "../../tests/fixtures/comparability.json";
import { compareIndicators } from "../src/comparison";
import { readPublicText, isPublicHttpsUrl } from "../src/http";
import { allowRequest, analyzeCsvText, bpsPayloadToText, csvUrl, fetchFromBpsDirect, loadCatalog, searchCatalog, type Env } from "../src/index";

const env: Env = { CATALOG_URL: "https://example.com/catalog.json", DATA_YEAR: "2025", CATALOG_TTL_SECONDS: "60", MAX_REQUESTS_PER_MINUTE: "60", BPS_API_KEY: "test-secret" };
afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); vi.useRealTimers(); });

describe("statistical regressions", () => {
  for (const item of cases) it(`${item.title} / ${item.label} / ${item.unit_a}`, () => {
    expect(compareIndicators(item.title, item.label, item.unit_a, item.unit_b).status).toBe(item.status);
  });

  it("counts quoted multiline cells as one observation and escapes markdown", () => {
    const result = analyzeCsvText('tahun,catatan,nilai\n2024,"baris pertama\nbaris kedua | kutip ""benar""",12\n2025,lain,15', 20);
    expect(result.rowCount).toBe(2);
    expect(result.observationStart).toBe("2024");
    expect(result.observationEnd).toBe("2025");
    expect(result.preview).toContain("<br>");
    expect(result.preview).toContain("\\|");
    expect(analyzeCsvText('a,b\n"unfinished,1', 20).status).toBe("invalid");
    expect(analyzeCsvText("a,b\n1,2,3", 20).status).toBe("invalid");
  });

  it("does not extract years from values or restrict portal downloads to one year", () => {
    expect(analyzeCsvText("kode,nilai\n2024,2025", 20).observationEnd).toBe("");
    expect(csvUrl({ identifier: "id", landingPage: "https://satudata.acehprov.go.id/datasets/id" }, env)).not.toContain("tahun=");
  });

  it("preserves BPS years, categories and subperiods and rejects undecodable keys", () => {
    const payload = {
      var: [{ val: 42, label: "Kemiskinan", unit: "Persen" }],
      vervar: [{ val: 1101, label: "Simeulue" }],
      tahun: [{ val: 124, label: "2024" }, { val: 125, label: "2025" }],
      turvar: [{ val: 1, label: "Kota" }, { val: 2, label: "Desa" }],
      turtahun: [{ val: 1, label: "Maret" }, { val: 2, label: "September" }],
      datacontent: { "11014211241": 12, "11014221252": 15 } as Record<string, number>,
    };
    const result = analyzeCsvText(bpsPayloadToText(payload), 20);
    expect([result.observationStart, result.observationEnd]).toEqual(["2024", "2025"]);
    for (const value of ["Kota", "Desa", "Maret", "September"]) expect(result.preview).toContain(value);
    payload.datacontent["unknown-key"] = 999;
    expect(bpsPayloadToText(payload)).toBe("");
  });

  it("does not expose BPS keys and first requests all available periods", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({
      status: "OK", "data-availability": "available", data: [{ tahun: 2026, nilai: 10 }],
    })));
    vi.stubGlobal("fetch", fetchMock);
    const result = await fetchFromBpsDirect("42", "1100", env);
    expect(result?.analysis.status).toBe("valid");
    expect(JSON.stringify(result)).not.toContain("test-secret");
    expect(fetchMock.mock.calls[0][0]).not.toContain("/th/");
  });
});

describe("outbound requests and cache", () => {
  it("isolates client quotas and expires the window", () => {
    const limitedEnv = { ...env, MAX_REQUESTS_PER_MINUTE: "1" };
    const now = Date.now();
    vi.spyOn(Date, "now").mockReturnValue(now);
    expect(allowRequest(limitedEnv, "client-a")).toBe(true);
    expect(allowRequest(limitedEnv, "client-a")).toBe(false);
    expect(allowRequest(limitedEnv, "client-b")).toBe(true);
    vi.mocked(Date.now).mockReturnValue(now + 60_000);
    expect(allowRequest(limitedEnv, "client-a")).toBe(true);
  });

  it("filters before ranking and paginates all matches", () => {
    const datasets = Array.from({ length: 8 }, (_, i) => ({ identifier: String(i), title: "Jumlah Penduduk Aceh", publisher: { name: "BPS" } }));
    datasets.push({ identifier: "other", title: "Jumlah Penduduk Medan", publisher: { name: "BPS" } });
    const result = searchCatalog(datasets, "penduduk", "Aceh", "BPS", 3, 3);
    expect(result.results.map(r => r.id)).toEqual(["3", "4", "5"]);
    expect(result.total).toBe(8);
    expect(result.next_offset).toBe(6);
  });

  it.each(["https://10.0.0.1/x", "https://172.16.1.2/x", "https://192.168.1.1/x", "https://100.64.0.1/x", "https://[::1]/x", "https://[::ffff:127.0.0.1]/x", "https://[fc00::1]/x", "https://localhost./x", "https://2130706433/x"])("rejects %s", url => {
    expect(isPublicHttpsUrl(url)).toBe(false);
  });

  it("uses a request deadline and rejects redirects", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response("data"));
    vi.stubGlobal("fetch", fetchMock);
    expect(await readPublicText("https://example.com/a.csv", 10)).toBe("data");
    expect(fetchMock.mock.calls[0][1].redirect).toBe("error");
    expect(fetchMock.mock.calls[0][1].signal).toBeInstanceOf(AbortSignal);
  });

  it("cancels a streaming response as soon as the byte limit is exceeded", async () => {
    const cancel = vi.fn();
    const body = new ReadableStream({ start(controller) { controller.enqueue(new Uint8Array(11)); }, cancel });
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(body)));
    await expect(readPublicText("https://example.com/a.csv", 10)).rejects.toThrow();
    expect(cancel).toHaveBeenCalled();
  });

  it("coalesces concurrent loads and serves cached catalog on upstream failure", async () => {
    const fetchMock = vi.fn().mockImplementation(async () => new Response(JSON.stringify({ dataset: [{ identifier: "one" }] })));
    vi.stubGlobal("fetch", fetchMock);
    const localEnv = { ...env, CATALOG_URL: "https://example.com/coalesced.json" };
    const [a, b] = await Promise.all([loadCatalog(localEnv), loadCatalog(localEnv)]);
    expect(a).toEqual(b);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const now = Date.now();
    vi.spyOn(Date, "now").mockReturnValue(now + 61_000);
    fetchMock.mockRejectedValue(new Error("offline"));
    expect(await loadCatalog(localEnv)).toEqual(a);
    expect(await loadCatalog(localEnv)).toEqual(a);
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });
});
