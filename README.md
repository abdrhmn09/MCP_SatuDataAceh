# MCP Satu Data Aceh

Hubungkan asisten AI dan aplikasi Anda ke katalog **Portal Satu Data Aceh** serta statistik dari **Web API BPS**. Proyek independen ini menyediakan akses baca dan membantu pengguna menelusuri sumber data yang dipakai dalam jawaban.

**[Buka MCP Satu Data Aceh](https://www.mcpsatudataaceh.web.id/)**

| Saya ingin | Mulai di sini |
| --- | --- |
| Mencoba data dari browser | [Jelajahi data](https://www.mcpsatudataaceh.web.id/#explore) |
| Menghubungkan ChatGPT, Claude, OpenCode, Antigravity, atau VS Code | [Panduan pemasangan per aplikasi](docs/panduan-pemasangan-mcp.md) |
| Menambahkan data Aceh dan BPS ke bot RAG atau agent buatan sendiri | [Panduan integrasi backend](docs/integrasi-agent-kustom.md) |
| Memahami tool, respons, dan alur OAuth | [Referensi teknis MCP](docs/referensi-mcp.md) |
| Menjalankan atau memelihara server | [Panduan deployment](docs/deployment.md) |

## Mulai menggunakan

1. [Buat akun](https://www.mcpsatudataaceh.web.id/#register), verifikasi email, lalu masuk.
2. Untuk statistik BPS, simpan API key yang Anda peroleh dari [Web API BPS](https://webapi.bps.go.id/documentation/) di menu **API key**. Pencarian dataset Portal Satu Data Aceh dapat dipakai tanpa API key BPS.
3. Di aplikasi AI, tambahkan endpoint `https://www.mcpsatudataaceh.web.id/mcp` sebagai server **Streamable HTTP**. Pilih **OAuth**, masuk saat diminta, lalu setujui akses.

Coba minta asisten mencari dataset inflasi Aceh dan menyertakan tautan sumber. Untuk bantuan login, buka [Lupa sandi](https://www.mcpsatudataaceh.web.id/#forgot-password). Akses aplikasi dapat dicabut melalui [Aplikasi terhubung](https://www.mcpsatudataaceh.web.id/#apps).

## Untuk developer bot

Backend bot dapat memakai endpoint yang sama dan mengirim header `Authorization: Bearer <TOKEN_MCP>`. Buat token melalui **Aplikasi terhubung → Token manual**. Simpan token sebagai secret pada backend bot dan kelola API key BPS melalui dashboard.

- Portal Satu Data Aceh memakai `search` untuk menemukan dataset dan `fetch` untuk membuka hasil berdasarkan ID.
- Web API BPS memakai `bps_endpoints` untuk melihat operasi dan parameter, lalu `bps_request` untuk mengambil data.

Lihat [panduan agent kustom](docs/integrasi-agent-kustom.md) dan [contoh Python](examples/custom-agent/) untuk menguji koneksi, mengelola token, dan menggabungkan sumber data publik dengan RAG internal.

## Pengembangan

Gunakan Python 3.11 atau lebih baru. Jalankan perintah berikut dari direktori repositori dalam lingkungan virtual.

```bash
python -m pip install -e .
python -m unittest discover -s tests -q
```

- [`src/`](src/) berisi server Python, tool MCP, adapter data, akun, dan OAuth.
- [`public/`](public/) berisi sumber aset situs. Salin perubahan aset ke [`src/static/`](src/static/) agar paket Python dan Nginx menyajikan versi yang sama. CI memeriksa kesesuaian keduanya.
- [`tests/`](tests/) berisi pengujian dengan data dan akun sintetis. [`deploy/`](deploy/) berisi konfigurasi Nginx dan skrip rilis VPS.

Baca [audit fitur](docs/feature-audit.md) untuk batas data dan keputusan kompatibilitas. Gateway Cloudflare dikelola di [repositori Worker terpisah](https://github.com/abdrhmn09/MCP_SatuDataAceh_Worker). Proyek ini memakai [lisensi MIT](LICENSE).
