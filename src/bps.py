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
# PENTING: peta ini hanya boleh berisi pasangan yang sudah diverifikasi terhadap
# katalog data.json dan respons BPS. Pemetaan yang tidak yakin sengaja dihapus
# agar tool tidak membandingkan indikator yang berbeda.
#
# Entri berikut pernah ada tetapi dihapus karena tidak lagi cocok dengan
# dataset portal (identifier dipakai ulang oleh dataset lain):
#   afefeee7... (bukan Jumlah Penduduk Miskin)
#   2414165c... (IPM menurut jenis kelamin nasional, bukan RLS)
#   6cab69b8... (Jumlah Guru SMP, BPS tidak menyediakan data SMP)
#   bfe0cc05... (Kontribusi Perikanan, bukan Pertumbuhan PDRB)
#   3f92d70a... (Produksi Perikanan Tangkap, BPS var 253 tidak punya data)
#   1d4d7e1a... (Prevalensi Stunting, BPS domain 1100 tidak punya var stunting)
#   81dc3ba5... (Persentase Fasyankes, bukan Garis Kemiskinan)
BPS_INDICATOR_MAP: dict[str, dict[str, str]] = {
    # ── Kemiskinan ──────────────────────────────────────────────────────────
    "0116d97b-1b4a-4c6a-a243-33833660fb85": {
        "var": "42",
        "label": "Persentase Penduduk Miskin (P0) menurut Kabupaten/Kota",
        "category": "kemiskinan",
        "defaultTh": "124",
    },
    # ── IPM & Pendidikan ────────────────────────────────────────────────────
    "5832d12b-52b2-44b2-b85c-0a3bd89782f3": {
        "var": "74",
        "label": "Indeks Pembangunan Manusia (IPM) menurut Kabupaten/Kota",
        "category": "ipm",
        "defaultTh": "124",
    },
    "78794e4b-2bbe-45ef-abd1-0a65c2e98702": {
        "var": "74",
        "label": "Indeks Pembangunan Manusia (IPM) menurut Kabupaten/Kota",
        "category": "ipm",
        "defaultTh": "124",
    },
    "f2585d70-70d1-49f9-8c78-6750a46e1780": {
        "var": "245",
        "label": "Rata-rata Lama Sekolah menurut Kabupaten/Kota",
        "category": "pendidikan",
        "defaultTh": "124",
    },
    # ── Ketenagakerjaan ─────────────────────────────────────────────────────
    "97e549de-0a20-452a-9948-455abe2532a8": {
        "var": "206",
        "label": "Tingkat Pengangguran Terbuka (TPT) menurut Kabupaten/Kota",
        "category": "ketenagakerjaan",
        "defaultTh": "124",
    },
    # ── Ekonomi & PDRB ─────────────────────────────────────────────────────
    "22d3b2b0-8c0e-46cb-915d-7780fd4e1158": {
        "var": "403",
        "label": "Laju Pertumbuhan PDRB Tahunan Atas Dasar Harga Konstan (ADHK)",
        "category": "pdrb",
        "defaultTh": "124",
    },
    "95ceff6a-c0d9-4ef5-b6cb-86eee4764833": {
        "var": "434",
        "label": "PDRB Per Kapita Tahunan Atas Dasar Harga Berlaku (ADHB)",
        "category": "pdrb",
        "defaultTh": "124",
    },
    # ── Harga & Inflasi ─────────────────────────────────────────────────────
    "e8c8605b-5ce1-4637-be23-9108837e89c9": {
        "var": "564",
        "label": "Inflasi Tahun ke Tahun (y-on-y)",
        "category": "inflasi",
        "defaultTh": "124",
    },
    # ── Ketimpangan ─────────────────────────────────────────────────────────
    "0c63d096-1671-4afd-94b5-39048d378e56": {
        "var": "60",
        "label": "Gini Rasio menurut Klasifikasi Desa/Kota",
        "category": "ketimpangan",
        "defaultTh": "124",
    },
    # ── Pertanian Tanaman Pangan & Hortikultura ─────────────────────────────
    "d8c8a7f0-d329-4872-8546-294fd6267c7b": {
        "var": "574",
        "label": "Luas Panen, Produktivitas, dan Produksi Padi menurut Kabupaten/Kota",
        "category": "pertanian",
        "defaultTh": "123",
    },
    "21cece89-360f-480d-a3e9-a841a79e752d": {
        "var": "581",
        "label": "Produksi Tanaman Sayuran menurut Kabupaten/Kota dan Jenis Tanaman",
        "category": "pertanian",
        "defaultTh": "123",
    },
}

# ---------------------------------------------------------------------------
import re

# ---------------------------------------------------------------------------
# Kamus Kata Kunci → Variabel BPS (untuk tool langsung tanpa ID dataset)
# ---------------------------------------------------------------------------
BPS_KEYWORD_TO_VAR: dict[str, dict[str, str]] = {
    # Pendidikan
    "pendidikan": {"var": "245", "label": "Rata-rata Lama Sekolah", "defaultTh": "124"},
    "lama sekolah": {"var": "245", "label": "Rata-rata Lama Sekolah", "defaultTh": "124"},
    "rata-rata lama sekolah": {"var": "245", "label": "Rata-rata Lama Sekolah", "defaultTh": "124"},
    "rls": {"var": "245", "label": "Rata-rata Lama Sekolah", "defaultTh": "124"},
    "harapan lama sekolah": {"var": "246", "label": "Harapan Lama Sekolah", "defaultTh": "124"},
    "hls": {"var": "246", "label": "Harapan Lama Sekolah", "defaultTh": "124"},
    "aps": {"var": "92", "label": "Angka Partisipasi Sekolah (APS)", "defaultTh": "124"},

    # Kemiskinan
    "kemiskinan": {"var": "42", "label": "Persentase Penduduk Miskin", "defaultTh": "124"},
    "miskin": {"var": "42", "label": "Persentase Penduduk Miskin", "defaultTh": "124"},
    "penduduk miskin": {"var": "42", "label": "Persentase Penduduk Miskin", "defaultTh": "124"},
    "jumlah penduduk miskin": {"var": "41", "label": "Jumlah Penduduk Miskin", "defaultTh": "124"},
    "garis kemiskinan": {"var": "45", "label": "Garis Kemiskinan", "defaultTh": "124"},

    # IPM Komposit
    "ipm": {"var": "74", "label": "Indeks Pembangunan Manusia (IPM)", "defaultTh": "124"},
    "indeks pembangunan manusia": {"var": "74", "label": "Indeks Pembangunan Manusia (IPM)", "defaultTh": "124"},
    "pembangunan manusia": {"var": "74", "label": "Indeks Pembangunan Manusia (IPM)", "defaultTh": "124"},

    # Komponen IPM
    "umur harapan hidup": {"var": "244", "label": "Umur Harapan Hidup (UHH)", "defaultTh": "124"},
    "uhh": {"var": "244", "label": "Umur Harapan Hidup (UHH)", "defaultTh": "124"},
    "angka harapan hidup": {"var": "244", "label": "Angka Harapan Hidup", "defaultTh": "124"},
    "pengeluaran perkapita": {"var": "247", "label": "Pengeluaran Perkapita Disesuaikan", "defaultTh": "124"},

    # Ketenagakerjaan
    "pengangguran": {"var": "206", "label": "Tingkat Pengangguran Terbuka", "defaultTh": "124"},
    "tpt": {"var": "206", "label": "Tingkat Pengangguran Terbuka", "defaultTh": "124"},

    # Ekonomi & PDRB
    "pdrb": {"var": "403", "label": "Laju Pertumbuhan PDRB Tahunan (ADHK)", "defaultTh": "124"},
    "pertumbuhan ekonomi": {"var": "403", "label": "Laju Pertumbuhan Ekonomi", "defaultTh": "124"},
    "laju pertumbuhan": {"var": "403", "label": "Laju Pertumbuhan Ekonomi", "defaultTh": "124"},

    # Inflasi
    "inflasi": {"var": "564", "label": "Laju Inflasi Tahun ke Tahun", "defaultTh": "124"},
    "ihk": {"var": "2", "label": "Indeks Harga Konsumen", "defaultTh": "124"},

    # Ketimpangan
    "gini": {"var": "60", "label": "Rasio Gini", "defaultTh": "124"},
    "rasio gini": {"var": "60", "label": "Rasio Gini", "defaultTh": "124"},

    # Pertanian
    "padi": {"var": "574", "label": "Produksi Padi", "defaultTh": "123"},
    "produksi padi": {"var": "574", "label": "Produksi Padi", "defaultTh": "123"},
    "sayur": {"var": "581", "label": "Produksi Tanaman Sayuran", "defaultTh": "123"},
    "sayuran": {"var": "581", "label": "Produksi Tanaman Sayuran", "defaultTh": "123"},
}


def cari_var_bps_dari_kata_kunci(kata_kunci: str) -> dict[str, str] | None:
    """Cari var_id BPS dari kata kunci pengguna dengan pencocokan kata utuh (word boundary)."""
    needle = kata_kunci.strip().lower()
    if not needle:
        return None

    # 1. Exact match dulu
    if needle in BPS_KEYWORD_TO_VAR:
        return BPS_KEYWORD_TO_VAR[needle]

    # 2. Phrase match dengan word boundary regex (prioritaskan kunci yang lebih panjang)
    sorted_keys = sorted(BPS_KEYWORD_TO_VAR.keys(), key=len, reverse=True)
    for key in sorted_keys:
        pattern = rf"\b{re.escape(key)}\b"
        if re.search(pattern, needle):
            return BPS_KEYWORD_TO_VAR[key]

    # 3. Token match: jika ada token kata input yang sama persis dengan kata kunci
    tokens = [t for t in re.split(r"[\s,./\-_+]+", needle) if len(t) > 1]
    for token in tokens:
        if token in BPS_KEYWORD_TO_VAR:
            return BPS_KEYWORD_TO_VAR[token]

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
    # BPS mengembalikan datacontent sebagai list kosong ketika data untuk
    # tahun/periode tersebut belum tersedia. Perlakukan sebagai "tidak ada data"
    # agar pemanggil bisa mencoba tahun lain, bukan crash.
    if not isinstance(datacontent, dict):
        return None
    vervar: list[dict[str, Any]] = payload.get("vervar") or []
    tahun_list: list[dict[str, Any]] = payload.get("tahun") or []
    var_list: list[dict[str, Any]] = payload.get("var") or [{}]
    turvar_list: list[dict[str, Any]] = payload.get("turvar") or [{"val": "0", "label": ""}]
    turtahun_list: list[dict[str, Any]] = payload.get("turtahun") or [
        {"val": "0", "label": "Tahunan"}
    ]

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
                    # Kunci BPS memakai nilai turtahun apa adanya (biasanya "0").
                    tt_val = str(tt.get("val", "0"))
                    tt_label = tt.get("label", "Tahunan")
                    # Kunci BPS: vervar + var + turvar + tahun + turtahun
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
        # Fallback: iterasi langsung dari kunci datacontent
        vervar_map = {str(vv.get("val", "")): vv.get("label", "") for vv in vervar}
        th_label = tahun_list[0].get("label", "2024") if tahun_list else "2024"
        for key, val in datacontent.items():
            matched_val = ""
            matched_label = ""
            for v_val, v_label in vervar_map.items():
                if v_val and key.startswith(v_val):
                    matched_val = v_val
                    matched_label = v_label
                    break
            rows.append({
                "kode_wilayah": matched_val or key[:4],
                "nama_wilayah": matched_label or f"Wilayah {key[:4]}",
                "tahun": th_label,
                "indikator": var_label,
                "nilai": val,
            })
            if unit:
                rows[-1]["satuan"] = unit

    if not rows:
        logger.warning("datacontent BPS ditemukan tetapi tidak ada nilai yang berhasil di-decode.")
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
