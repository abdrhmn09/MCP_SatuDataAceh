import { describe, expect, it } from "vitest";
import { analyzeCsvText, datasetYear, isPublicHttpsUrl, parseCsvRows, searchDatasets } from "../src/index";

describe("Cloudflare Worker adapter", () => {
  it("menerima URL HTTPS publik dan menolak alamat lokal", () => {
    expect(isPublicHttpsUrl("https://satudata.acehprov.go.id/data.json")).toBe(true);
    expect(isPublicHttpsUrl("http://satudata.acehprov.go.id/data.json")).toBe(false);
    expect(isPublicHttpsUrl("https://localhost/data.csv")).toBe(false);
    expect(isPublicHttpsUrl("https://127.0.0.1/data.csv")).toBe(false);
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

  it("mempertahankan header-only sebagai status kosong", () => {
    const result = analyzeCsvText("nama,nilai\n", 20);
    expect(result.status).toBe("header_only");
    expect(result.text).toBe("");
  });
});