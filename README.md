# MCP Satu Data Aceh

MCP Satu Data Aceh menyediakan akses baca ke katalog **Portal Satu Data Aceh** dan statistik dari **Web API BPS** bagi asisten AI dan aplikasi. Hasil penelusuran menyertakan rujukan agar pengguna dapat memeriksa sumber data.

**[Buka MCP Satu Data Aceh](https://www.mcpsatudataaceh.web.id/)**

| Kebutuhan | Panduan |
| --- | --- |
| Penelusuran data melalui peramban | [Jelajahi data](https://www.mcpsatudataaceh.web.id/#explore) |
| Koneksi aplikasi AI | [Panduan pemasangan per aplikasi](docs/panduan-pemasangan-mcp.md) |
| Integrasi bot RAG atau agen AI | [Panduan integrasi backend](docs/integrasi-agent-kustom.md) |
| Spesifikasi alat MCP, respons, dan OAuth | [Referensi teknis](docs/referensi-mcp.md) |
| Pemasangan dan pemeliharaan server | [Panduan operasional](docs/deployment.md) |

## Mulai menggunakan

1. [Buat akun](https://www.mcpsatudataaceh.web.id/#register), verifikasi email, lalu masuk.
2. Untuk mengakses statistik BPS, simpan kunci dari [Web API BPS](https://webapi.bps.go.id/documentation/) melalui menu **API key**. Katalog Portal Satu Data Aceh dapat digunakan setelah akun terverifikasi.
3. Di aplikasi AI, tambahkan endpoint `https://www.mcpsatudataaceh.web.id/mcp` sebagai server **Streamable HTTP**. Pilih **OAuth**, lalu masuk dan setujui akses.

Untuk memeriksa koneksi, minta asisten mencari dataset inflasi Aceh dan menyertakan tautan sumber. Pulihkan akses akun melalui [Lupa sandi](https://www.mcpsatudataaceh.web.id/#forgot-password) dan kelola izin melalui [Aplikasi terhubung](https://www.mcpsatudataaceh.web.id/#apps).

## Integrasi aplikasi

Backend aplikasi dapat menggunakan endpoint yang sama dengan header `Authorization: Bearer <TOKEN_MCP>`. Buat token melalui **Aplikasi terhubung → Token manual** dan simpan di penyimpanan rahasia backend.

- Portal Satu Data Aceh memakai `search` untuk menemukan dataset dan `fetch` untuk membuka hasil berdasarkan ID.
- Web API BPS memakai `bps_endpoints` untuk melihat operasi dan parameter, lalu `bps_request` untuk mengambil data.

Contoh integrasi dan pemeriksaan koneksi tersedia dalam [klien Python](examples/custom-agent/).

## Instalasi lokal dan pengujian

Gunakan Python 3.11 atau lebih baru. Jalankan perintah berikut dari direktori repositori dalam lingkungan virtual.

```bash
python -m pip install -e .
python -m unittest discover -s tests -q
```

- [`src/`](src/) berisi server Python, alat MCP, adapter data, pengelolaan akun, dan OAuth.
- [`public/`](public/) berisi sumber aset situs. Salin perubahan aset ke [`src/static/`](src/static/) agar paket Python dan Nginx menyajikan versi yang sama. CI memeriksa kesesuaian keduanya.
- [`tests/`](tests/) berisi pengujian dengan data dan akun sintetis. [`deploy/`](deploy/) berisi konfigurasi Nginx dan skrip rilis VPS.

