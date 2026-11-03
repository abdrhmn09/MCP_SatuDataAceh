# MCP Satu Data Aceh

[![Status](https://img.shields.io/badge/Status-Active%20%7C%20Online-success)](https://www.mcpsatudataaceh.web.id/health)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.11%20%7C%203.12-blue)](pyproject.toml)
[![Protocol](https://img.shields.io/badge/Protocol-Model%20Context%20Protocol%20(MCP)-emerald)](https://modelcontextprotocol.io)

**MCP Satu Data Aceh** adalah server [Model Context Protocol (MCP)](https://modelcontextprotocol.io) yang menghubungkan berbagai klien AI modern (**Claude Desktop, Cursor, ChatGPT, VS Code Copilot, LibreChat**) secara langsung ke **Portal Resmi Satu Data Aceh (4.000+ dataset)** dan **Web API Badan Pusat Statistik (BPS) Provinsi Aceh (Domain 1100)**.

Landing page resmi & status server: **[https://www.mcpsatudataaceh.web.id](https://www.mcpsatudataaceh.web.id)**

---

## 🚀 URL Endpoint Remote MCP

Gunakan endpoint SSE resmi berikut pada aplikasi AI Anda:

```text
https://www.mcpsatudataaceh.web.id/sse
```

> **Catatan Keamanan & Privasi**: Server ini bersifat *read-only*, hanya mengakses data terbuka (*open data*) publik, serta tidak memerlukan login, cookie, maupun data pribadi pengguna.

---

## Runtime dan endpoint

Repositori menyediakan dua runtime dengan lima tool yang sama:

| Runtime | Transport | Endpoint |
| --- | --- | --- |
| Python | STDIO, SSE, atau Streamable HTTP | `/sse` atau `/mcp`, sesuai `MCP_TRANSPORT` |
| Cloudflare Worker | Streamable HTTP stateless | `/mcp` |

Gunakan `/mcp` untuk deployment Worker. Panduan SSE di bawah berlaku untuk deployment Python dengan `MCP_TRANSPORT=sse`. Status endpoint produksi belum diverifikasi oleh unit test.

Pemetaan BPS, sinonim pencarian, dan kamus kesepadanan disimpan bersama di `src/bps_catalog.json`, `src/search_rules.json`, dan `src/comparison_rules.json`. Edit berkas tersebut agar kedua runtime tetap konsisten. `BPS_DATASET_MAP` hanya untuk override yang telah diverifikasi; konfigurasi lama dapat menimpa perbaikan pemetaan.

### Pencarian dan metadata

`search` menerima parameter opsional `wilayah`, `produsen`, `limit` (1–50, default 5), dan `offset` (default 0). Respons mencakup `total`, `offset`, serta `next_offset`. Filter wilayah memakai judul/deskripsi/kata kunci katalog, sehingga cakupan observasi tetap perlu diperiksa melalui `fetch`.

Contoh argumen tool:

```json
{"query":"penduduk","wilayah":"Aceh","produsen":"BPS","limit":10,"offset":0}
```

`fetch` memisahkan `observation_start`/`observation_end` dari `published_at`/`modified_at`, mencatat `retrieved_at`, dan menyertakan status cache katalog. Tahun observasi diambil dari kolom waktu, bukan dari nilai numerik atau tanggal publikasi. Tahun yang tidak diketahui dikembalikan sebagai string kosong.

Unduhan portal mengambil seluruh tahun. Permintaan BPS pertama mencoba tanpa filter `th`; jika tidak tersedia, server mencoba periode kurasi pada pemetaan dan tahun fallback. Ketiadaan data baru tidak membuktikan bahwa BPS belum menerbitkannya. Parser menolak matriks dengan kunci dimensi yang tidak dapat didekode, alih-alih menebak wilayah atau tahun.

`bandingkan_data` membedakan indikator tidak sepadan dari metadata yang belum cukup. Kesamaan konsep dan satuan belum memastikan kesamaan seluruh wilayah, kategori, atau subperiode. Tool ini menyajikan kedua sumber dan periode observasinya; belum menghitung selisih angka per pasangan observasi. Worker juga mengembalikan `structuredContent` berisi status kesepadanan dan metadata kedua sumber.

### Konfigurasi dan keamanan

Salin `.env.example` menjadi `.env` untuk Python. Untuk Worker, gunakan `worker/.dev.vars.example` sebagai contoh pengembangan lokal dan simpan key produksi melalui `wrangler secret put BPS_API_KEY` dari direktori `worker`.

| Python | Worker | Fungsi |
| --- | --- | --- |
| `BPS_API_KEY` | `BPS_API_KEY` | Secret BPS; opsional untuk fitur katalog/CSV portal |
| `BPS_DOMAIN` | `BPS_DOMAIN` | Domain BPS, default `1100` |
| `SATU_DATA_ACEH_CATALOG_URL` | `CATALOG_URL` | URL katalog |
| `SATU_DATA_ACEH_CACHE_TTL` | `CATALOG_TTL_SECONDS` | TTL katalog, default 3.600 detik |
| `MCP_RATE_LIMIT_PER_MINUTE` | `MAX_REQUESTS_PER_MINUTE` | Batas pemanggilan tool per klien, default 60 |
| `MCP_ALLOWED_HOSTS` | — | Daftar Host HTTP yang diizinkan, dipisahkan koma |
| `MCP_ALLOWED_ORIGINS` | — | Daftar Origin yang diizinkan, dipisahkan koma |
| `SATU_DATA_ACEH_LOCAL_PATH` | — | Lokasi snapshot katalog fallback |

Tambahkan hostname deployment sendiri ke `MCP_ALLOWED_HOSTS` dan origin HTTPS yang sesuai ke `MCP_ALLOWED_ORIGINS`. Proteksi DNS rebinding MCP tetap aktif. Python memeriksa hasil DNS unduhan CSV/HTML, menghubungkan ke IP yang telah diperiksa, dan mempertahankan hostname untuk validasi TLS. Worker menolak IP privat/lokal literal; kebijakan DNS dan egress mengikuti platform Cloudflare. Kedua runtime menolak redirect unduhan CSV/HTML.

Batas unduhan: CSV dan BPS 5 MiB, HTML 2 MiB, dan katalog 32 MiB. Worker memakai deadline pengambilan 30 detik. Cache yang kedaluwarsa dapat tetap dipakai saat upstream gagal, ditandai `stale`, dengan jeda retry 30 detik. `/health` adalah liveness check dan menyertakan status cache; `status=ok` tidak menyatakan upstream sedang tersedia.

Rate limit berada dalam memori proses/isolate. Python menggunakan alamat peer transport; di belakang proxy bersama, konfigurasikan kepercayaan proxy pada server secara tepat. Worker menggunakan `CF-Connecting-IP` yang dikelola Cloudflare. Kuota belum terdistribusi antarproses atau antar-isolate.

API key yang pernah masuk Git harus dicabut/dirotasi melalui akun BPS. Menghapusnya dari kode tidak mencabut key lama atau menghapus riwayat Git. Respons dan log menyamarkan key pada URL endpoint BPS.

### Pengembangan dan verifikasi

```bash
python3 -m pip install -e .
python3 -m unittest discover -s tests -v
```

Dari direktori `worker`:

```bash
npm ci
npm run typecheck
npm test
npm run dev
```

Tes unit berjalan tanpa API key dan tidak mengakses BPS. Tes live terpisah melalui `npm run test:live`, dan dilewati bila `BPS_API_KEY` tidak tersedia di environment. CI menjalankan tes Python 3.11–3.13 serta pemeriksaan tipe dan unit test Worker. Kasus kesepadanan bersama berada di `tests/fixtures/comparability.json`.

Image Docker menyertakan snapshot `data.json` sebagai fallback dan berjalan sebagai pengguna non-root. Snapshot tersebut harus diperbarui berkala; status fallback lokal ditandai sebagai data cache lama.

---

## 🛠️ Daftar Tools yang Tersedia

Server menyediakan 5 tool terstandar:

| Tool | Fungsi Utama | Parameter Input |
| :--- | :--- | :--- |
| **`search`** | Mencari dataset Aceh berperingkat relevansi (bobot judul, wilayah Aceh, dan kurasi statistik) | `query`: string; opsional: `wilayah`, `produsen`, `limit`, `offset` |
| **`fetch`** | Mengambil preview tabel numerik, mendeteksi kolom indikator riil, satuan, dan rentang tahun observasi | `id`: string (UUID dataset) |
| **`cari_katalog_data`** | Pencarian katalog naratif lengkap dengan produsen data dan tautan unduh CSV | `kata_kunci`: string |
| **`baca_isi_csv`** | Mengunduh dan membaca baris numerik dari URL CSV publik ke format tabel Markdown | `url`: string (HTTPS), `baris_maksimal`: int (1–50) |
| **`bandingkan_data`** | **(Unggulan)** Komparasi otomatis antara Satu Data Aceh dan BPS Web API dengan validasi kesepadanan metodologis | `indikator`: string (misal: "IPM", "kemiskinan", "inflasi", "padi") |

---

## 💻 Panduan Integrasi Klien AI

### 1. Claude Desktop (Remote SSE)
Claude Desktop **tidak membaca field `url`** dari `claude_desktop_config.json`. Gunakan salah satu cara berikut:

**A. Melalui menu Connectors (paling mudah)**
1. Buka **Settings** > **Connectors** > **Add custom connector**.
2. Masukkan URL: `https://www.mcpsatudataaceh.web.id/sse`
3. Simpan, lalu mulai percakapan baru.

**B. Melalui `mcp-remote` (jika Connectors belum tersedia)**
Tambahkan ke `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "satu-data-aceh": {
      "command": "npx",
      "args": ["-y", "mcp-remote", "https://www.mcpsatudataaceh.web.id/sse"]
    }
  }
}
```

*Lokasi file konfigurasi:*
- **macOS**: `~/Library/Application Support/Claude/claude_desktop_config.json`
- **Windows**: `%APPDATA%\Claude\claude_desktop_config.json`
- **Linux**: `~/.config/Claude/claude_desktop_config.json`

---

### 2. Cursor IDE
Tambahkan pada file `.cursor/mcp.json` di project Anda atau melalui menu **Settings** > **MCP**:

```json
{
  "mcpServers": {
    "satu-data-aceh": {
      "url": "https://www.mcpsatudataaceh.web.id/sse"
    }
  }
}
```

---

### 3. ChatGPT (Developer Mode / Custom Actions)
1. Buka **Settings** > **Developer mode** / **Connectors** / **MCP**.
2. Pilih **Add New MCP Server**.
3. Pilih tipe transport: **Server-Sent Events (SSE)**.
4. Masukkan URL:
   ```text
   https://www.mcpsatudataaceh.web.id/sse
   ```
5. Simpan dan mulai percakapan baru.

---

### 4. VS Code / GitHub Copilot
Buat file `.vscode/mcp.json` di root project (bukan `settings.json`):

```json
{
  "servers": {
    "satu-data-aceh": {
      "type": "sse",
      "url": "https://www.mcpsatudataaceh.web.id/sse"
    }
  }
}
```

Setelah itu jalankan perintah **MCP: List Servers** dari Command Palette, lalu pilih `satu-data-aceh` > **Start Server**.

---

### 5. Mode Lokal (STDIO via Python)
Jika Anda ingin menjalankan server langsung di mesin lokal tanpa jaringan remote:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Lalu gunakan konfigurasi berikut:

```json
{
  "mcpServers": {
    "satu-data-aceh-lokal": {
      "command": "python3",
      "args": ["-m", "src.server"],
      "cwd": "/path/ke/MCP_SatuDataAceh",
      "env": {
        "MCP_TRANSPORT": "stdio",
        "BPS_API_KEY": "api_key_bps_anda"
      }
    }
  }
}
```

---

## 💡 Contoh Pertanyaan / Prompts

Setelah MCP terhubung, Anda dapat mengajukan pertanyaan seperti:

- *"Bandingkan angka kemiskinan di Aceh antara data BPS dan data Satu Data Aceh terbaru."*
- *"Cari dataset IPM Provinsi Aceh menurut kabupaten/kota dan tampilkan 5 baris pertamanya."*
- *"Berapa tren jumlah penduduk Aceh dari tahun 2006 sampai 2024?"*
- *"Cari dataset tentang kualitas air laut di Aceh dan tampilkan tautan CSV-nya."*

---

## 🏗️ Fitur Unggulan Riset Statistik

1. **Multi-Year CSV Fetch**:
   - Mendukung unduhan seluruh deret waktu historis tanpa batasan parameter tahun tunggal (misal data 2006–2024 terambil lengkap 19 baris).
2. **Ekstraksi Tahun Observasi Aktual**:
   - Mengekstrak tahun observasi dari kolom tabel numerik, bukan dari timestamp metadata publikasi portal (mencegah salah deteksi tahun rilis).
3. **Validasi Kesepadanan Indikator (`Smart Comparability`)**:
   - Menolak perbandingan yang berbeda satuan (mis. Rupiah vs Persen), berbeda skala (Juta vs Ribu Rupiah), berbeda indikator (mis. stunting vs harapan lama sekolah), atau berbeda jenis ukuran (kontribusi/pangsa vs laju pertumbuhan).
   - Tetap memeriksa perbedaan cakupan wilayah (nasional vs Aceh) dan disagregasi gender.
4. **Deteksi Kolom Indikator & Satuan**:
   - Mengidentifikasi nama variabel numerik substantif dan satuan data (`Poin`, `Persen`, `Rupiah/Kapita/Bulan`, `Jiwa`), termasuk satuan resmi dari respons BPS.
5. **Transparansi Keterbatasan BPS**:
   - Jika indikator tidak tersedia di BPS Domain 1100 (mis. stunting, produksi perikanan tangkap, jumlah guru), tool tidak memaksakan perbandingan dan akan menampilkan status `tidak_ditemukan`.

---

## 🧪 Pengujian & Pemeriksaan Server

### Cek Status Server (Health Check)
```bash
curl -s https://www.mcpsatudataaceh.web.id/health
```
Output yang diharapkan:
```json
{"status":"ok","service":"satu-data-aceh-mcp"}
```

### Menjalankan Unit Test Lokal
```bash
# Dari root repositori
python3 -m pytest tests
```
Seluruh test suite harus berstatus **passed**. Unit test menggunakan mock jaringan; tes live Worker dijalankan terpisah.

---

## 🏛️ Sumber Data

- **Portal Satu Data Aceh**: [https://satudata.acehprov.go.id](https://satudata.acehprov.go.id)
- **Badan Pusat Statistik Provinsi Aceh**: [https://aceh.bps.go.id](https://aceh.bps.go.id)

---

## 📄 Lisensi

Proyek ini dirilis di bawah lisensi [MIT License](LICENSE).
