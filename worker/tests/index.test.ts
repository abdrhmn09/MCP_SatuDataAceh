import { describe, expect, it } from "vitest";
import { isPublicHttpsUrl, parseCsvRows, searchDatasets } from "../src/index";

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

  it("mengambil header dan baris CSV sesuai batas", () => {
    const csv = "nama,nilai\nAceh,10\nSumut,20\nJabar,30\n";
    expect(parseCsvRows(csv, 2)).toBe("nama,nilai\nAceh,10\nSumut,20");
  });
});