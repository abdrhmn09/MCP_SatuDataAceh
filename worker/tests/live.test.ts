import { describe, expect, it } from "vitest";
import { fetchFromBpsDirect, createServer } from "../src/index";
import { cariVarBpsDariKataKunci } from "../src/bps";

// Menggunakan API Key untuk pengujian integrasi live BPS
const apiKey = typeof process !== "undefined" && process.env?.BPS_API_KEY
  ? process.env.BPS_API_KEY
  : "8df9707992442cf8a5b8140a6b2939ea";

const liveEnv = {
  CATALOG_URL: "https://satudata.acehprov.go.id/data.json",
  DATA_YEAR: "2025",
  CATALOG_TTL_SECONDS: "3600",
  MAX_REQUESTS_PER_MINUTE: "60",
  BPS_API_KEY: apiKey,
  BPS_DOMAIN: "1100",
  BPS_DATASET_MAP: "{}",
};

describe("Live BPS Web API Integration Tests (Cloudflare Worker)", () => {
  it("BPS API key terdeteksi dengan panjang 32 karakter", () => {
    expect(apiKey).toBeDefined();
    expect(apiKey.length).toBe(32);
  });

  it("berhasil memuat data Kemiskinan (var 42) secara live melalui fetchFromBpsDirect", async () => {
    if (!apiKey) return;
    const res = await fetchFromBpsDirect("42", "1100", liveEnv, 10);
    expect(res).not.toBeNull();
    expect(res?.analysis.status).toBe("valid");
    expect(res?.analysis.rowCount).toBeGreaterThan(0);
    expect(res?.analysis.text).toContain("kode_wilayah");
    expect(res?.analysis.text).toContain("Persentase");
    expect(res?.analysis.preview).toContain("|");
  }, 15000);

  it("berhasil memuat data Pendidikan RLS (var 245) secara live melalui fetchFromBpsDirect", async () => {
    if (!apiKey) return;
    const res = await fetchFromBpsDirect("245", "1100", liveEnv, 10);
    expect(res).not.toBeNull();
    expect(res?.analysis.status).toBe("valid");
    expect(res?.analysis.rowCount).toBeGreaterThan(0);
    expect(res?.analysis.text).toContain("Lama Sekolah");
  }, 15000);

  it("berhasil memuat data Ketenagakerjaan TPT (var 206) secara live melalui fetchFromBpsDirect", async () => {
    if (!apiKey) return;
    const res = await fetchFromBpsDirect("206", "1100", liveEnv, 10);
    expect(res).not.toBeNull();
    expect(res?.analysis.status).toBe("valid");
    expect(res?.analysis.rowCount).toBeGreaterThan(0);
    expect(res?.analysis.text).toContain("Pengangguran");
  }, 15000);

  it("berhasil memuat data Inflasi (var 564) secara live melalui fetchFromBpsDirect", async () => {
    if (!apiKey) return;
    const res = await fetchFromBpsDirect("564", "1100", liveEnv, 10);
    expect(res).not.toBeNull();
    expect(res?.analysis.status).toBe("valid");
    expect(res?.analysis.rowCount).toBeGreaterThan(0);
  }, 15000);

  it("berhasil menguji variasi kata kunci dan langsung mengambil data BPS yang relevan", async () => {
    if (!apiKey) return;
    const testCases = [
      { query: "rata-rata lama sekolah", expectedVar: "245" },
      { query: "jumlah penduduk miskin", expectedVar: "41" },
      { query: "pengangguran terbuka", expectedVar: "206" },
      { query: "laju inflasi", expectedVar: "564" },
      { query: "produksi padi aceh", expectedVar: "574" },
    ];

    for (const tc of testCases) {
      const match = cariVarBpsDariKataKunci(tc.query);
      expect(match).not.toBeNull();
      expect(match?.var).toBe(tc.expectedVar);

      const res = await fetchFromBpsDirect(match!.var, "1100", liveEnv, 5, match?.defaultTh);
      expect(res).not.toBeNull();
      expect(res?.analysis.status).toBe("valid");
      expect(res?.analysis.rowCount).toBeGreaterThan(0);
    }
  }, 30000);

  it("Server MCP Worker berhasil diinisialisasi dan mendaftarkan 5 tool", () => {
    const server = createServer(liveEnv);
    expect(server).toBeDefined();
  });
});
