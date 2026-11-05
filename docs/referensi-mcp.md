# Referensi teknis MCP Satu Data Aceh

Lihat [panduan pemasangan](panduan-pemasangan-mcp.md) untuk konfigurasi klien dan [panduan integrasi aplikasi](integrasi-agent-kustom.md) untuk koneksi dari backend.

## Alat MCP dan sumber data

| Alat MCP | Fungsi |
| --- | --- |
| `search` | Mencari dataset berdasarkan kata kunci katalog Aceh. Mendukung penyaringan metadata dan penelusuran per halaman. |
| `fetch` | Membuka dataset berdasarkan ID. Mengembalikan rujukan sumber, pratinjau CSV, dan metadata kualitas. |
| `bps_endpoints` | Menampilkan daftar operasi BPS atau skema parameter suatu operasi. |
| `bps_request` | Menjalankan operasi baca BPS dengan parameter yang divalidasi. |
| `bps_check_key` | Menguji kredensial akun dengan satu operasi sampel pada layanan BPS atau SDGs. |
| `bandingkan_data` | Meninjau kesepadanan sumber untuk indikator yang dipetakan. |
| `cari_katalog_data`, `baca_isi_csv` | Menampilkan hasil pencarian dan pratinjau CSV dalam format teks. Untuk hasil terstruktur, gunakan `search` dan `fetch`. |

### Portal Satu Data Aceh

Gunakan `search` untuk memperoleh ID dataset dan URL sumber. Parameter opsional mencakup `wilayah`, `produsen`, `limit`, dan `offset`. Penyaringan wilayah berlaku pada metadata katalog. Periksa `metadata.coverage` dari `fetch` untuk mengetahui cakupan wilayah pada baris CSV.

Pratinjau `fetch` mencakup hingga 50 baris dari dataset yang dipilih. Data terstruktur memuat nama kolom, baris, jumlah baris, dan penanda pemotongan. Nilai kosong atau tidak hingga disajikan sebagai `null`. Status CSV `valid` menunjukkan bahwa format berkas dapat dibaca.

### Web API BPS dan SDGs

Registri mencakup 59 operasi GET, termasuk data statistik, publikasi, sensus, perdagangan, klasifikasi, dan SDGs Access. Ketersediaan tiap operasi bergantung pada parameter, hak akses, dan layanan BPS. Gunakan `bps_endpoints` untuk melihat skema sebelum memanggil `bps_request`.

```json
{"operation":"listVariables","parameters":{"domain":"1100","page":1}}
```

Kode domain Aceh adalah `1100` dan kode domain nasional adalah `0000`. Ambil kode variabel melalui `listVariables` dan ID periode melalui `listPeriods` sebelum memanggil `getData`. Ikuti penelusuran per halaman dan periksa `ok` serta `error` pada hasil. Gunakan ID periode yang diterbitkan BPS.

Kunci API BPS dan token SDGs Access dikelola secara terpisah. Untuk server lokal STDIO, tetapkan `BPS_API_KEY` dan, bila diperlukan, `BPS_SDGS_TOKEN` pada lingkungan proses. Untuk layanan jarak jauh, simpan kredensial melalui dasbor akun.

Di menu **API key**, **Uji koneksi BPS** menguji satu sampel tiap operasi secara bertahap. Operasi yang belum memiliki kredensial ditandai **Belum diuji**. Pengguna dapat memfilter status, menyalin laporan, dan membatalkan pengujian. Pengujian dapat dijalankan satu kali per akun setiap sepuluh menit.

Registri tersedia di [`src/bps_operations.json`](../src/bps_operations.json). [Skrip pembaruan registri](../scripts/update_bps_registry.py) menggunakan spesifikasi YAML BPS dan PyYAML.

### Kesepadanan antarsumber

`bandingkan_data` menilai kesepadanan berdasarkan metadata yang tersedia, termasuk konsep, satuan, wilayah, periode, subperiode, dan kategori. Konflik metadata, misalnya antara inflasi bulanan dan tahunan, dapat menyebabkan kesepadanan berstatus belum terverifikasi. Untuk analisis per observasi, periksa definisi indikator, cakupan, dan nilai pada masing-masing sumber.

Jika pemeriksaan metadata periode belum lengkap, gunakan `listPeriods` dan `getData` dengan periode dan dimensi yang diperlukan untuk menelusuri data BPS secara langsung.

## OAuth dan discovery

- `GET /.well-known/oauth-protected-resource/mcp` menerbitkan metadata resource.
- `GET /.well-known/oauth-authorization-server` menerbitkan metadata otorisasi.
- `GET /authorize` dan `POST /token` menjalankan OAuth Authorization Code dengan PKCE S256 dan scope `data:read`. `POST /register` menangani Dynamic Client Registration (DCR). `POST /revoke` mencabut akses.
- `POST /api/oauth/consent` memakai sesi web, pemeriksaan origin, dan CSRF.

Kirim `resource` yang cocok persis dengan URL `/mcp` atau `/sse` pada origin utama saat otorisasi dan pertukaran token. Callback mengikuti URI terdaftar. Untuk metadata yang menyatakan aplikasi native, port callback HTTP pada alamat IP loopback dapat berbeda selama komponen lainnya cocok. Respons callback menyertakan `iss`.

Client ID Metadata Document (CIMD) diambil melalui HTTPS dari host pada `OAUTH_CIMD_HOSTS`, dengan nilai default `chatgpt.com,claude.ai,opencode.ai`. Dokumen dibatasi 16 KiB dan disimpan satu jam. Server memeriksa ID klien serta menolak redirect pada pengambilan metadata. Klien lain dapat memakai DCR. Untuk OpenCode di VPS yang memakai daftar host eksplisit, sertakan `opencode.ai`.

Access token OAuth berlaku 15 menit. Grant dan refresh token berlaku paling lama 30 hari sejak persetujuan. Refresh token berotasi dan pemakaian ulang token lama mencabut grant. Kode otorisasi berlaku dua menit dan dapat ditukar sekali.

Untuk bot tanpa alur login interaktif, [token MCP manual](integrasi-agent-kustom.md) dapat dipakai pada header Bearer. Untuk transport SSE lama, sertakan header pada `GET /sse` dan `POST /messages/`.

## Akun dan penyimpanan

Dashboard menggunakan cookie HttpOnly dan CSRF untuk tindakan yang memakai sesi. Transport MCP menggunakan token akses. Sandi di-hash menggunakan scrypt. Kredensial BPS dienkripsi menggunakan AES-256-GCM dengan master key yang disimpan di konfigurasi server. Database SQLite menyimpan metadata akun seperti email dalam bentuk biasa serta hash token dan sesi.

API dashboard berada di bawah `/api/account/`. Rute `forgot-password` dan `reset-password` menangani pemulihan. Rute `delete-request` dan `delete-confirm` mengatur penghapusan akun. Rute `sessions` menampilkan dan mencabut sesi. Tindakan akun memakai pemeriksaan origin dan, jika memakai sesi, header `X-CSRF-Token`.

Reset atau ganti sandi mencabut sesi web, token manual, grant OAuth, dan sesi transport MCP. Tautan verifikasi dan tindakan akun memerlukan konfirmasi sebelum perubahan diterapkan. Penghapusan akun menghapus salinan API key di database aktif. Kredensial yang diterbitkan BPS tetap dikelola di BPS.
