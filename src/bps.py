"""BPS Aceh variable mapping dan parser respons Web API BPS.

Modul ini mengelola:
- Peta indikator strategis Aceh: identifier Satu Data Aceh → variabel BPS
- Resolver variabel BPS dari kata kunci (untuk tool langsung tanpa dataset)
- Parser respons Web API BPS (datacontent matriks multidimensi)
"""

from __future__ import annotations

import logging
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Peta Indikator Strategis BPS Aceh (Domain 1100)
#
# Format: "identifier_satu_data_aceh" → "var_id_bps"
#
# Untuk mendapatkan daftar var_id terbaru:
#   GET https://webapi.bps.go.id/v1/api/list/model/var/domain/1100/key/{KEY}
#
# Peta ini digunakan oleh _bps_source() sebagai FALLBACK ketika data Satu Data
# Aceh tidak tersedia, kosong, atau hanya berisi header.
# ---------------------------------------------------------------------------
BPS_INDICATOR_MAP: dict[str, dict[str, str]] = {
    # ── Kemiskinan ──────────────────────────────────────────────────────────
    "0116d97b-1b4a-4c6a-a243-33833660fb85": {
        "var": "621",
        "label": "Persentase Penduduk Miskin Aceh Menurut Kabupaten/Kota",
        "category": "kemiskinan",
    },
    "afefeee7-2dbb-4ab8-aa2c-71610fc5fdb6": {
        "var": "2212",
        "label": "Persentase Penduduk Miskin Ekstrem",
        "category": "kemiskinan",
    },
    # ── Pembangunan Manusia ─────────────────────────────────────────────────
    "78794e4b-2bbe-45ef-abd1-0a65c2e98702": {
        "var": "498",
        "label": "Indeks Pembangunan Manusia (IPM)",
        "category": "ipm",
    },
    "2414165c-27b1-41a1-8229-0a51a128636d": {
        "var": "498",
        "label": "IPM Berdasarkan Jenis Kelamin",
        "category": "ipm",
    },
    # ── Ketenagakerjaan ─────────────────────────────────────────────────────
    "97e549de-0a20-452a-9948-455abe2532a8": {
        "var": "529",
        "label": "Tingkat Pengangguran Terbuka (TPT)",
        "category": "ketenagakerjaan",
    },
    # ── Ekonomi & PDRB ─────────────────────────────────────────────────────
    "22d3b2b0-8c0e-46cb-915d-7780fd4e1158": {
        "var": "199",
        "label": "Laju Pertumbuhan Ekonomi Aceh",
        "category": "pdrb",
    },
    "95ceff6a-c0d9-4ef5-b6cb-86eee4764833": {
        "var": "786",
        "label": "PDRB Per Kapita Provinsi Aceh",
        "category": "pdrb",
    },
    "bfe0cc05-78ff-46f2-9329-c943863e5c50": {
        "var": "199",
        "label": "Kontribusi Sektor Perikanan Terhadap PDRB",
        "category": "pdrb",
    },
    # ── Harga & Inflasi ─────────────────────────────────────────────────────
    "e8c8605b-5ce1-4637-be23-9108837e89c9": {
        "var": "1400",
        "label": "Tingkat Inflasi Tahun ke Tahun Provinsi Aceh",
        "category": "inflasi",
    },
    # ── Ketimpangan ─────────────────────────────────────────────────────────
    "0c63d096-1671-4afd-94b5-39048d378e56": {
        "var": "631",
        "label": "Rasio Gini Provinsi Aceh",
        "category": "ketimpangan",
    },
    # ── Gizi & Kesehatan ────────────────────────────────────────────────────
    "1d4d7e1a-9d53-45a4-a11e-dc24d6c8cf25": {
        "var": "2212",
        "label": "Prevalensi Stunting Balita Aceh",
        "category": "kesehatan",
    },
    "81dc3ba5-e050-47fe-846b-298ca2977216": {
        "var": "529",
        "label": "Persentase Fasyankes yang Terpenuhi SDM Kesehatan",
        "category": "kesehatan",
    },
    # ── Pendidikan ──────────────────────────────────────────────────────────
    "f2585d70-70d1-49f9-8c78-6750a46e1780": {
        "var": "490",
        "label": "Rata-rata Lama Sekolah Provinsi Aceh",
        "category": "pendidikan",
    },
    # ── Pertanian Tanaman Pangan ────────────────────────────────────────────
    "d8c8a7f0-d329-4872-8546-294fd6267c7b": {
        "var": "1321",
        "label": "Produksi Padi Menurut Kabupaten/Kota",
        "category": "pertanian",
    },
    # ── Hortikultura ────────────────────────────────────────────────────────
    "21cece89-360f-480d-a3e9-a841a79e752d": {
        "var": "1350",
        "label": "Produksi Tanaman Sayur-Sayuran Menurut Jenis dan Kabupaten/Kota",
        "category": "hortikultura",
    },
    # ── Peternakan ──────────────────────────────────────────────────────────
    "9d11046b-a61b-4169-bf20-b691483162ba": {
        "var": "1375",
        "label": "Jumlah Potong Hewan Menurut Jenis Ternak",
        "category": "peternakan",
    },
    # ── Perikanan ───────────────────────────────────────────────────────────
    "3f92d70a-8533-4f25-bc9f-332b7a4c8b84": {
        "var": "1398",
        "label": "Produksi Perikanan Tangkap di Perairan Darat",
        "category": "perikanan",
    },
}

# ---------------------------------------------------------------------------
# Kamus Kata Kunci → Variabel BPS (untuk tool langsung tanpa ID dataset)
# Memungkinkan pencarian: "IPM Aceh" → var 498 tanpa perlu ID dataset
# ---------------------------------------------------------------------------
BPS_KEYWORD_TO_VAR: dict[str, dict[str, str]] = {
    # Kemiskinan
    "kemiskinan": {"var": "621", "label": "Persentase Penduduk Miskin"},
    "miskin": {"var": "621", "label": "Persentase Penduduk Miskin"},
    "kemiskinan ekstrem": {"var": "2212", "label": "Persentase Kemiskinan Ekstrem"},
    "garis kemiskinan": {"var": "622", "label": "Garis Kemiskinan"},
    # IPM & Pendidikan
    "ipm": {"var": "498", "label": "Indeks Pembangunan Manusia"},
    "pembangunan manusia": {"var": "498", "label": "Indeks Pembangunan Manusia"},
    "rata-rata lama sekolah": {"var": "490", "label": "Rata-rata Lama Sekolah"},
    "harapan lama sekolah": {"var": "495", "label": "Harapan Lama Sekolah"},
    # Ketenagakerjaan
    "pengangguran": {"var": "529", "label": "Tingkat Pengangguran Terbuka"},
    "tpt": {"var": "529", "label": "Tingkat Pengangguran Terbuka"},
    "angkatan kerja": {"var": "527", "label": "Angkatan Kerja"},
    # Ekonomi
    "pdrb": {"var": "786", "label": "PDRB Per Kapita"},
    "pertumbuhan ekonomi": {"var": "199", "label": "Laju Pertumbuhan Ekonomi"},
    "laju pertumbuhan": {"var": "199", "label": "Laju Pertumbuhan Ekonomi"},
    # Inflasi & Harga
    "inflasi": {"var": "1400", "label": "Laju Inflasi"},
    "ihn": {"var": "1400", "label": "Indeks Harga Nasional"},
    # Ketimpangan
    "gini": {"var": "631", "label": "Rasio Gini"},
    "rasio gini": {"var": "631", "label": "Rasio Gini"},
    # Pertanian
    "padi": {"var": "1321", "label": "Produksi Padi"},
    "jagung": {"var": "1323", "label": "Produksi Jagung"},
    "kedelai": {"var": "1325", "label": "Produksi Kedelai"},
    "sayur": {"var": "1350", "label": "Produksi Sayuran"},
    "hortikultura": {"var": "1350", "label": "Produksi Hortikultura"},
    # Peternakan
    "ternak": {"var": "1375", "label": "Populasi Ternak"},
    "sapi": {"var": "1377", "label": "Populasi Sapi"},
    "ayam": {"var": "1379", "label": "Populasi Ayam"},
    # Perikanan
    "perikanan": {"var": "1398", "label": "Produksi Perikanan"},
    "ikan": {"var": "1398", "label": "Produksi Perikanan"},
    # Kesehatan
    "stunting": {"var": "2212", "label": "Prevalensi Stunting"},
    "usia harapan hidup": {"var": "494", "label": "Umur Harapan Hidup"},
    "uhh": {"var": "494", "label": "Umur Harapan Hidup"},
    # Sosial
    "kemiskinan ekstrem desa": {"var": "2213", "label": "Kemiskinan Ekstrem Perdesaan"},
    "perlindungan sosial": {"var": "621", "label": "Penerima Perlindungan Sosial"},
}


def cari_var_bps_dari_kata_kunci(kata_kunci: str) -> dict[str, str] | None:
    """Cari var_id BPS dari kata kunci pengguna (case-insensitive, substring match)."""
    needle = kata_kunci.strip().lower()
    # Exact match dulu
    if needle in BPS_KEYWORD_TO_VAR:
        return BPS_KEYWORD_TO_VAR[needle]
    # Substring match
    for key, val in BPS_KEYWORD_TO_VAR.items():
        if key in needle or needle in key:
            return val
    return None


def bps_payload_ke_dataframe(payload: dict[str, Any]) -> pd.DataFrame | None:
    """Ubah respons Web API BPS (model/data) dengan datacontent ke DataFrame pandas.

    Web API BPS menggunakan struktur matriks multidimensi:
    - vervar:    wilayah (kabupaten/kota)
    - tahun:     tahun observasi
    - turvar:    turunan variabel (rincian komoditas / 0 jika tidak ada)
    - turtahun:  sub-periode (semester, triwulan / 0 jika tahunan)
    - datacontent: {"{vervar_val}{var_val}{turvar_val}{tahun_val}{turtahun_val}": angka}
    """
    if not isinstance(payload, dict):
        return None
    if "datacontent" not in payload:
        return None

    datacontent: dict[str, float] = payload.get("datacontent", {})
    vervar: list[dict[str, Any]] = payload.get("vervar", [])
    tahun_list: list[dict[str, Any]] = payload.get("tahun", [])
    var_list: list[dict[str, Any]] = payload.get("var", [{}])
    turvar_list: list[dict[str, Any]] = payload.get("turvar", [{"val": "0", "label": ""}])
    turtahun_list: list[dict[str, Any]] = payload.get("turtahun", [{"val": "0", "label": "Tahunan"}])

    var_label = var_list[0].get("label", "Nilai") if var_list else "Nilai"
    unit = var_list[0].get("unit", "") if var_list else ""
    var_val = str(var_list[0].get("val", "")) if var_list else ""

    rows: list[dict[str, Any]] = []
    for vv in vervar:
        vv_val = str(vv.get("val", ""))
        vv_label = vv.get("label", "")
        for th in tahun_list:
            th_val = str(th.get("val", ""))
            th_label = th.get("label", "")
            for tv in turvar_list:
                tv_val = str(tv.get("val", "0"))
                tv_label = tv.get("label", "")
                for tt in turtahun_list:
                    # turtahun_val harus 2 digit (zero-padded) sesuai format datacontent BPS
                    tt_raw = str(tt.get("val", "0"))
                    tt_val = tt_raw.zfill(2)
                    tt_label = tt.get("label", "Tahunan")
                    # Kunci BPS: vervar + var + turvar + tahun + turtahun(2 digit)
                    key = f"{vv_val}{var_val}{tv_val}{th_val}{tt_val}"
                    if key in datacontent:
                        row: dict[str, Any] = {
                            "kode_wilayah": vv_val,
                            "nama_wilayah": vv_label,
                            "tahun": th_label,
                            "indikator": var_label,
                        }
                        # Tambahkan kolom turunan hanya jika ada lebih dari 1 kategori
                        if len(turvar_list) > 1:
                            row["kategori"] = tv_label
                        if len(turtahun_list) > 1:
                            row["periode"] = tt_label
                        row["nilai"] = datacontent[key]
                        if unit:
                            row["satuan"] = unit
                        rows.append(row)

    if not rows:
        logger.warning("datacontent BPS ditemukan tetapi tidak ada nilai yang berhasil di-decode (mungkin kunci format berbeda).")
        return None

    df = pd.DataFrame(rows)
    # Urutkan berdasarkan tahun terbaru di atas
    if "tahun" in df.columns:
        df = df.sort_values("tahun", ascending=False)
    return df


def bps_payload_ke_csv(payload: dict[str, Any]) -> str:
    """Konversi respons Web API BPS ke teks CSV.

    Mendukung dua format:
    1. Matriks multidimensi (datacontent) — format Dynamic Data BPS
    2. Array list (data.data) — format lama / static table / fallback
    """
    # --- Format 1: Dynamic Data (datacontent) ---
    if isinstance(payload, dict) and "datacontent" in payload:
        df = bps_payload_ke_dataframe(payload)
        if df is not None and not df.empty:
            return df.to_csv(index=False)

    # --- Format 2: Array list (fallback) ---
    if not isinstance(payload, dict):
        return ""
    rows: Any = payload.get("data", [])
    if isinstance(rows, dict):
        rows = rows.get("data", [])
    if not isinstance(rows, list) or not rows:
        return ""
    objects = [r for r in rows if isinstance(r, dict)]
    if not objects:
        return ""
    import pandas as _pd
    columns = list(dict.fromkeys(col for r in objects for col in r))
    return _pd.DataFrame(objects, columns=columns).to_csv(index=False)
