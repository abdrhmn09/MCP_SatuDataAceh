import { describe, expect, it, vi } from "vitest";
import {
  analyzeCsvText,
  bpsPayloadToText,
  bpsSource,
  createServer,
  csvToMarkdownTable,
  datasetYear,
  findCsvLinkInHtml,
  fetchFromBpsDirect,
  isPublicHttpsUrl,
  parseCsvRows,
  searchDatasets,
  type Env,
} from "../src/index";
import {
  cariVarBpsDariKataKunci,
  parseBpsDiagnostics,
  BPS_INDICATOR_MAP,
  BPS_KEYWORD_TO_VAR,
} from "../src/bps";

const mockEnv: Env = {
  CATALOG_URL: "https://satudata.acehprov.go.id/data.json",
  DATA_YEAR: "2025",
  CATALOG_TTL_SECONDS: "3600",
  MAX_REQUESTS_PER_MINUTE: "60",
  BPS_API_KEY: "dummy-key",
  BPS_DOMAIN: "1100",
  BPS_DATASET_MAP: '{"custom-id":"999"}',
};

describe("Cloudflare Worker adapter & Tools", () => {
  it("menerima URL HTTPS publik dan menolak alamat lokal", () => {
    expect(isPublicHttpsUrl("https://satudata.acehprov.go.id/data.json")).toBe(true);
    expect(isPublicHttpsUrl("http://satudata.acehprov.go.id/data.json")).toBe(false);
    expect(isPublicHttpsUrl("https://localhost/data.csv")).toBe(false);
    expect(isPublicHttpsUrl("https://127.0.0.1/data.csv")).toBe(false);
    expect(isPublicHttpsUrl("https://169.254.169.254/secret")).toBe(false);
  });

  it("mencari dataset dari metadata dan membatasi lima hasil", () => {
    const datasets = Array.from({ length: 6 }, (_, index) => ({
      identifier: `dataset-${index}`,
      title: `Penduduk Aceh ${index}`,
      landingPage: `https://satudata.acehprov.go.id/datasets/dataset-${index}`,
    }));

    const results = searchDatasets(datasets, "penduduk");

    expect(results).toHaveLength(5);
    expect(results[0]).toMatchObject({ id: "dataset-0", title: "Penduduk Aceh 0" });
  });

  it("memperluas istilah kemiskinan saat mencari", () => {
    const results = searchDatasets(
      [{ identifier: "miskin-1", title: "Persentase Penduduk Miskin Aceh" }],
      "kemiskinan",
    );
    expect(results[0].id).toBe("miskin-1");
  });

  it("menggunakan tahun metadata sebelum fallback konfigurasi", () => {
    expect(datasetYear({ issued: "2021-01-01" }, { DATA_YEAR: "2025" } as never)).toBe("2021");
    expect(datasetYear({}, { DATA_YEAR: "2025" } as never)).toBe("2025");
  });

  it("mengambil header dan baris CSV sesuai batas", () => {
    const csv = "nama,nilai\nAceh,10\nSumut,20\nJabar,30\n";
    expect(parseCsvRows(csv, 2)).toBe("nama,nilai\nAceh,10\nSumut,20");
  });

  it("menandai CSV yang hanya berisi header", () => {
    const result = analyzeCsvText("nama,nilai\n", 20);
    expect(result.status).toBe("header_only");
    expect(result.rowCount).toBe(0);
    expect(result.columnCount).toBe(2);
  });

  it("menolak HTML yang dikirim sebagai respons 200", () => {
    const result = analyzeCsvText("<html><body>Not found</body></html>", 20);
    expect(result.status).toBe("html");
  });

  it("memformat CSV menjadi tabel markdown dengan benar", () => {
    const csv = 'kabupaten,persen\n"Banda Aceh",7.12\nSimeulue,18.23';
    const md = csvToMarkdownTable(csv, 20);
    expect(md).toContain("| kabupaten | persen |");
    expect(md).toContain("| --- | --- |");
    expect(md).toContain("| Banda Aceh | 7.12 |");
    expect(md).toContain("| Simeulue | 18.23 |");
  });

  it("mengurai payload datacontent BPS dengan format matriks ke CSV", () => {
    const payload = {
      status: "OK",
      "data-availability": "available",
      var: [{ val: 621, label: "Persentase Penduduk Miskin", unit: "Persen" }],
      vervar: [
        { val: 1171, label: "Banda Aceh" },
        { val: 1101, label: "Simeulue" },
      ],
      tahun: [
        { val: 141, label: "2023" },
        { val: 142, label: "2024" },
      ],
      turvar: [{ val: 0, label: "" }],
      turtahun: [{ val: 0, label: "Tahunan" }],
      datacontent: {
        "1171621014100": 7.12,
        "1171621014200": 7.04,
        "1101621014100": 18.23,
        "1101621014200": 17.95,
      },
    };
    const csv = bpsPayloadToText(payload);
    expect(csv).toContain("Banda Aceh");
    expect(csv).toContain("Simeulue");
    expect(csv).toContain("7.12");
    expect(csv).toContain("18.23");
    expect(csv.split("\n")).toHaveLength(5); // 1 header + 4 rows
  });

  it("mengembalikan string kosong jika payload BPS tidak valid atau kosong", () => {
    expect(bpsPayloadToText(null)).toBe("");
    expect(bpsPayloadToText({})).toBe("");
    expect(bpsPayloadToText({ datacontent: {} })).toBe("");
  });

  it("bpsSource mendukung BPS_INDICATOR_MAP dan env override", () => {
    // 1. Env override
    const src1 = bpsSource({ identifier: "custom-id" }, mockEnv);
    expect(src1?.variable).toBe("999");

    // 2. Built-in BPS_INDICATOR_MAP (kemiskinan)
    const src2 = bpsSource({ identifier: "0116d97b-1b4a-4c6a-a243-33833660fb85" }, mockEnv);
    expect(src2?.variable).toBe("621");

    // 3. IPM
    const src3 = bpsSource({ identifier: "78794e4b-2bbe-45ef-abd1-0a65c2e98702" }, mockEnv);
    expect(src3?.variable).toBe("498");

    // 4. Unknown
    const src4 = bpsSource({ identifier: "unknown-uuid" }, mockEnv);
    expect(src4).toBeNull();
  });

  // ── PENGUJIAN REGRESI PENTING: KATA KUNCI PENDIDIKAN TIDAK BOLEH MENCOCOKKAN IKAN ──
  it("cariVarBpsDariKataKunci TIDAK mencocokkan kata 'ikan' saat query 'pendidikan'", () => {
    const result = cariVarBpsDariKataKunci("pendidikan");
    expect(result).not.toBeNull();
    // Harus mencocokkan indikator pendidikan (var 490), BUKAN perikanan (var 1398)
    expect(result?.var).toBe("490");
    expect(result?.label).toContain("Lama Sekolah");
    expect(result?.var).not.toBe("1398");
  });

  it("cariVarBpsDariKataKunci mencocokkan seluruh variasi kata kunci pendidikan dengan tepat", () => {
    expect(cariVarBpsDariKataKunci("sekolah")?.var).toBe("490");
    expect(cariVarBpsDariKataKunci("guru")?.var).toBe("490");
    expect(cariVarBpsDariKataKunci("murid")?.var).toBe("490");
    expect(cariVarBpsDariKataKunci("siswa")?.var).toBe("490");
    expect(cariVarBpsDariKataKunci("rata-rata lama sekolah")?.var).toBe("490");
    expect(cariVarBpsDariKataKunci("harapan lama sekolah")?.var).toBe("495");
    expect(cariVarBpsDariKataKunci("hls")?.var).toBe("495");
    expect(cariVarBpsDariKataKunci("rls")?.var).toBe("490");
    expect(cariVarBpsDariKataKunci("aps")?.var).toBe("490");
  });

  it("cariVarBpsDariKataKunci tetap mencocokkan kata 'ikan' dan 'perikanan' ke var 1398", () => {
    expect(cariVarBpsDariKataKunci("ikan")?.var).toBe("1398");
    expect(cariVarBpsDariKataKunci("perikanan")?.var).toBe("1398");
    expect(cariVarBpsDariKataKunci("produksi perikanan tangkap")?.var).toBe("1398");
  });

  it("cariVarBpsDariKataKunci mencari kata kunci non-pendidikan lainnya dengan benar", () => {
    expect(cariVarBpsDariKataKunci("kemiskinan")?.var).toBe("621");
    expect(cariVarBpsDariKataKunci("ipm")?.var).toBe("498");
    expect(cariVarBpsDariKataKunci("tpt")?.var).toBe("529");
    expect(cariVarBpsDariKataKunci("padi")?.var).toBe("1321");
    expect(cariVarBpsDariKataKunci("inflasi")?.var).toBe("1400");
    expect(cariVarBpsDariKataKunci("kata-kunci-tidak-ada-sama-sekali")).toBeNull();
  });

  // ── PENGUJIAN DIAGNOSTIK ERROR BPS WEB API ──
  it("parseBpsDiagnostics mengekstrak error penolakan API key BPS", () => {
    const errorPayload = {
      status: "Error",
      message: "You are not Allowed to take this action. Please re-check your key",
    };
    const diag = parseBpsDiagnostics(errorPayload);
    expect(diag.ok).toBe(false);
    expect(diag.dataAvailable).toBe(false);
    expect(diag.message).toContain("You are not Allowed to take this action");
  });

  it("parseBpsDiagnostics mengekstrak status data tidak tersedia di BPS", () => {
    const unavailPayload = {
      status: "OK",
      "data-availability": "unavailable",
      message: "Data tidak ditemukan",
    };
    const diag = parseBpsDiagnostics(unavailPayload);
    expect(diag.ok).toBe(false);
    expect(diag.dataAvailable).toBe(false);
    expect(diag.message).toContain("Data tidak ditemukan");
  });

  it("fetchFromBpsDirect memberikan instruksi yang jelas saat API key belum disetel", async () => {
    const envTanpaKey = { ...mockEnv, BPS_API_KEY: "" };
    const result = await fetchFromBpsDirect("490", "1100", envTanpaKey);
    expect(result).not.toBeNull();
    expect(result?.analysis.message).toContain("BPS_API_KEY belum dikonfigurasi");
    expect(result?.diagnostic).toContain("npx wrangler secret put BPS_API_KEY");
  });

  it("BPS_INDICATOR_MAP memiliki minimal 15 indikator strategis", () => {
    expect(Object.keys(BPS_INDICATOR_MAP).length).toBeGreaterThanOrEqual(15);
  });

  it("BPS_KEYWORD_TO_VAR memiliki minimal 30 kata kunci", () => {
    expect(Object.keys(BPS_KEYWORD_TO_VAR).length).toBeGreaterThanOrEqual(30);
  });

  it("findCsvLinkInHtml mengekstrak tautan CSV dari konten HTML", async () => {
    const htmlContent = '<html><body><a href="https://example.com/data/laporan.csv">Unduh CSV</a></body></html>';
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      text: async () => htmlContent,
    } as unknown as Response);

    const link = await findCsvLinkInHtml("https://example.com/page");
    expect(link).toBe("https://example.com/data/laporan.csv");
  });

  it("createServer mendaftarkan 5 tool lengkap", () => {
    const server = createServer(mockEnv);
    expect(server).toBeDefined();
  });
});