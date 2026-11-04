# Panduan pemasangan MCP Satu Data Aceh

Mulai dengan **server jarak jauh melalui OAuth**. Server sudah berjalan di VPS, sehingga Anda cukup menambahkan URL MCP ke klien dan masuk. Bagian STDIO ditujukan untuk pengguna yang ingin menjalankan server sendiri.

| Aplikasi | Mode yang bisa dipilih | Konfigurasi |
|---|---|---|
| ChatGPT Web | Server jarak jauh dengan OAuth | Tambahkan server MCP kustom |
| Claude Web / Desktop | Server jarak jauh dengan OAuth | Tambahkan custom connector |
| Claude Desktop | Server lokal dengan STDIO | `claude_desktop_config.json` |
| Google Antigravity | Server jarak jauh atau STDIO | `mcp_config.json` dengan `mcpServers` |
| VS Code | Server jarak jauh atau STDIO | `.vscode/mcp.json` dengan `servers` |

## Server jarak jauh dengan OAuth

Gunakan URL **`https://www.mcpsatudataaceh.web.id/mcp`**. Buat akun di situs MCP dan verifikasi email. Untuk mengakses data BPS, simpan API key Web API BPS melalui menu **API key**. Dataset portal Aceh dapat dicari melalui akun tanpa key BPS. Setelah klien membuka halaman persetujuan, periksa nama aplikasi dan callback, lalu izinkan akses. Izin dapat dicabut melalui **Aplikasi terhubung**.

### ChatGPT Web

1. Buka pengelolaan **Plugins** di ChatGPT Web. Pilih **+ → Add custom MCP server** jika workspace Anda menyediakan opsi tersebut.
2. Isi nama **Satu Data Aceh**, masukkan URL MCP di atas, dan pilih **OAuth**. Gunakan penemuan klien otomatis melalui CIMD atau DCR jika tersedia.
3. Tinjau konfirmasi, pilih **Create as a plugin**, lalu ikuti proses masuk ketika diminta. Aktifkan plugin pada percakapan yang akan memakai data Aceh.

Rujukan [OpenAI Docs – Add custom MCP server](https://developers.openai.com/api/docs/guides/custom-mcp-server).

### Claude Web dan Claude Desktop

1. Buka **Customize → Connectors**, lalu pilih **+ Add → Add custom connector**. Untuk akun organisasi, pengelola workspace mungkin perlu menambahkan konektor lebih dahulu.
2. Masukkan nama **Satu Data Aceh** dan URL MCP. Gunakan alur login dan registrasi otomatis bila opsi tersebut tersedia.
3. Pilih **Connect** untuk menyelesaikan persetujuan. Aktifkan konektor di percakapan yang akan memakainya.

Rujukan [Claude Help Center – Custom connectors](https://support.claude.com/en/articles/11175166-get-started-with-custom-connectors-using-remote-mcp).

### Google Antigravity

Di Antigravity IDE, buka menu panel agent **… → MCP Servers → Manage MCP Servers → View raw config**. Tambahkan entri ini ke peta `mcpServers` yang sudah ada.

```json
{
  "mcpServers": {
    "satu-data-aceh": {
      "serverUrl": "https://www.mcpsatudataaceh.web.id/mcp"
    }
  }
}
```

Pilih **Authenticate** bila tersedia dan ikuti langkah login. Jika klien memerlukan header manual, buat token melalui dashboard **Token manual** dan tambahkan `"headers": {"Authorization": "Bearer TOKEN_MCP_ANDA"}` pada entri server. Ganti placeholder di konfigurasi pribadi dengan token MCP akun Anda. Simpan konfigurasi berisi token di luar Git.

Rujukan [Google Antigravity – MCP](https://antigravity.google/docs/mcp).

### VS Code

Tambahkan entri ke `.vscode/mcp.json`, lalu jalankan server melalui **MCP: List Servers** dan ikuti permintaan login jika muncul.

```json
{
  "servers": {
    "satu-data-aceh": {
      "type": "http",
      "url": "https://www.mcpsatudataaceh.web.id/mcp"
    }
  }
}
```

Rujukan [VS Code – MCP configuration](https://code.visualstudio.com/docs/agents/reference/mcp-configuration).

## Pengaturan lanjutan untuk server lokal dengan STDIO

Instal Python 3.11 atau lebih baru dan siapkan salinan repositori. Jalankan perintah berikut dari folder proyek.

### Windows dengan PowerShell

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
```

Perintah pertama membuat file `.venv\Scripts\python.exe` di komputer Anda. Gunakan file tersebut sebagai `command` pada konfigurasi klien.

### macOS dan Linux dengan terminal

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e .
```

Untuk data BPS, buat file `.env` pribadi di folder proyek yang sama dengan `pyproject.toml`. Server membaca file tersebut saat mulai. Isi `BPS_API_KEY` untuk Web API BPS dan `BPS_SDGS_TOKEN` untuk SDGs Access jika diperlukan.

### Claude Desktop dan Antigravity

Gunakan konfigurasi berikut di `claude_desktop_config.json` untuk Claude Desktop atau di `mcp_config.json` untuk Antigravity. Gabungkan entri dengan server yang sudah ada.

```json
{
  "mcpServers": {
    "satu-data-aceh-local": {
      "command": "/path/ke/MCP_SatuDataAceh/.venv/bin/python",
      "args": ["-m", "src.main"],
      "env": {
        "MCP_TRANSPORT": "stdio"
      }
    }
  }
}
```

Ganti `command` dengan path absolut Python di lingkungan virtual. Pada Windows, contoh path JSON adalah `C:/Projects/MCP_SatuDataAceh/.venv/Scripts/python.exe`. Di Claude Desktop, file konfigurasi berada di direktori aplikasi `Claude` dalam `~/Library/Application Support` (macOS) atau `%APPDATA%` (Windows). Tutup aplikasi sepenuhnya dan buka kembali setelah mengedit. Di Antigravity, muat ulang server melalui pengelola MCP.

Untuk VS Code, gunakan kunci `servers` sebagai pengganti `mcpServers` dan tambahkan `"type": "stdio"` ke entri yang sama.

Rujukan [MCP Python SDK – Connect to a real host](https://py.sdk.modelcontextprotocol.io/get-started/real-host/), [Google Antigravity – MCP](https://antigravity.google/docs/mcp), dan [VS Code – MCP configuration](https://code.visualstudio.com/docs/agents/reference/mcp-configuration).

## Uji koneksi

1. Tanyakan **“Cari dataset inflasi Aceh dengan tool `search` dan tampilkan ID serta tautannya.”** Periksa bahwa klien memanggil tool MCP.
2. Untuk BPS, minta klien menjalankan `bps_request` dengan `operation: "listDomains"` dan `parameters: {"type":"prov"}`. Periksa bahwa hasil berisi domain Aceh `1100`.
3. Jika pencarian portal berhasil tetapi BPS gagal, cek API key di dashboard untuk OAuth atau di `.env` untuk STDIO. Jika seluruh tool absen, cek status koneksi di aplikasi. Untuk STDIO, periksa path Python, hasil instalasi, dan log proses.
