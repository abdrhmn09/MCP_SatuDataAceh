"""BPS Aceh variable mapping dan parser respons Web API BPS.

Modul ini mengelola:
- Peta indikator strategis Aceh: identifier Satu Data Aceh → variabel BPS
- Resolver variabel BPS dari kata kunci (untuk tool langsung tanpa dataset)
- Parser respons Web API BPS (datacontent matriks multidimensi)
"""

from __future__ import annotations

import json
import math
from importlib.resources import files
from pathlib import Path
import logging
import re
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)
_package_files = files(__package__) if __package__ else Path(__file__).parent
_catalog = json.loads(_package_files.joinpath("bps_catalog.json").read_text(encoding="utf-8"))

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
BPS_INDICATOR_MAP: dict[str, dict[str, str]] = _catalog["indicators"]

# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Kamus Kata Kunci → Variabel BPS (untuk tool langsung tanpa ID dataset)
# ---------------------------------------------------------------------------
BPS_KEYWORD_TO_VAR: dict[str, dict[str, str]] = _catalog["keywords"]


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

    if math.prod(map(len, (vervar, tahun_list, turvar_list, turtahun_list))) > 1_000_000:
        logger.warning("Matriks dimensi BPS terlalu besar.")
        return None

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

    if len(rows) != len(datacontent):
        logger.warning("Dimensi BPS tidak lengkap; menolak hasil parsial.")
        return None

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
