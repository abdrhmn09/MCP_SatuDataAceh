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

## 🛠️ Daftar Tools yang Tersedia

Server menyediakan 5 tool terstandar:

| Tool | Fungsi Utama | Parameter Input |
| :--- | :--- | :--- |
| **`search`** | Mencari dataset Aceh berperingkat relevansi (bobot judul, wilayah Aceh, dan kurasi statistik) | `query`: string |
| **`fetch`** | Mengambil preview tabel numerik, mendeteksi kolom indikator riil, satuan, dan rentang tahun observasi | `id`: string (UUID dataset) |
| **`cari_katalog_data`** | Pencarian katalog naratif lengkap dengan produsen data dan tautan unduh CSV | `kata_kunci`: string |
| **`baca_isi_csv`** | Mengunduh dan membaca baris numerik dari URL CSV publik ke format tabel Markdown | `url`: string (HTTPS), `baris_maksimal`: int (1–50) |
| **`bandingkan_data`** | **(Unggulan)** Komparasi otomatis antara Satu Data Aceh dan BPS Web API dengan validasi kesepadanan metodologis | `indikator`: string (misal: "IPM", "kemiskinan", "penduduk") |

---

## 💻 Panduan Integrasi Klien AI

### 1. Claude Desktop (Remote SSE)
Tambahkan ke file konfigurasi Claude Desktop (`claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "satu-data-aceh": {
      "url": "https://www.mcpsatudataaceh.web.id/sse"
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
Tambahkan pada konfigurasi ekstensi MCP di VS Code (`settings.json`):

```json
{
  "mcp": {
    "servers": {
      "satu-data-aceh": {
        "url": "https://www.mcpsatudataaceh.web.id/sse",
        "type": "sse"
      }
    }
  }
}
```

---

### 5. Mode Lokal (STDIO via Python)
Jika Anda ingin menjalankan server langsung di mesin lokal tanpa jaringan remote:

```json
{
  "mcpServers": {
    "satu-data-aceh-lokal": {
      "command": "python",
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
   - Mencegah perbandingan yang keliru antara data agregat total provinsi dengan data disagregasi gender atau data nasional.
4. **Deteksi Kolom Indikator & Satuan**:
   - Mengidentifikasi nama variabel numerik substantif dan satuan data (`Poin`, `Persen`, `Rupiah/Kapita/Bulan`, `Jiwa`).

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
# Menggunakan venv lokal
pytest tests
```
Semua test suite (58 tests) harus berstatus **passed**.

---

## 🏛️ Sumber Data

- **Portal Satu Data Aceh**: [https://satudata.acehprov.go.id](https://satudata.acehprov.go.id)
- **Badan Pusat Statistik Provinsi Aceh**: [https://aceh.bps.go.id](https://aceh.bps.go.id)

---

## 📄 Lisensi

Proyek ini dirilis di bawah lisensi [MIT License](LICENSE).
