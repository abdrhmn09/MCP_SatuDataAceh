# Pemasangan dan pemeliharaan server MCP Satu Data Aceh

Panduan ini untuk operator server. Untuk memakai server yang sudah tersedia, ikuti [panduan pengguna dan aplikasi](panduan-pemasangan-mcp.md).

## Menyiapkan layanan Python

Gunakan Python 3.11 atau lebih baru dan salin [`.env.example`](../.env.example) ke `.env` ketika membuat instalasi baru.

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e .
cp .env.example .env
```

Buat kunci enkripsi utama untuk instalasi baru. Simpan hasilnya sebagai `ACCOUNTS_ENCRYPTION_KEY` dalam konfigurasi privat atau layanan pengelolaan rahasia.

```bash
python3 -c "import base64,secrets; print(base64.b64encode(secrets.token_bytes(32)).decode())"
```

| Pengaturan | Kegunaan |
| --- | --- |
| `ACCOUNTS_DB_PATH` | Lokasi SQLite di penyimpanan persisten yang bisa ditulis oleh akun layanan. |
| `ACCOUNTS_ENCRYPTION_KEY` | Kunci enkripsi utama. Gunakan nilai yang sesuai dengan basis data saat memulai ulang atau memulihkan layanan. |
| `ACCOUNTS_PUBLIC_ORIGIN` | Origin HTTPS utama tanpa path untuk tautan email dan discovery OAuth. |
| `ACCOUNTS_ALLOWED_ORIGINS` | Origin dashboard tambahan yang diizinkan, jika ada. |
| `MCP_ALLOWED_HOSTS`, `MCP_ALLOWED_ORIGINS` | Host dan origin yang diizinkan untuk transport MCP. Sesuaikan dengan Nginx dan klien browser yang digunakan. |
| `MCP_TRANSPORT` | `both` mengaktifkan Streamable HTTP dan SSE. Gunakan `streamable-http` jika hanya menyediakan `/mcp`. |
| `MCP_HOST`, `MCP_PORT` | Di VPS, gunakan loopback seperti `127.0.0.1:8000` di belakang Nginx HTTPS. |
| `OAUTH_CIMD_HOSTS` | Daftar host metadata klien OAuth tepercaya. Lihat [aturan discovery](referensi-mcp.md#oauth-dan-discovery). |
| `ACCOUNTS_DEV_HTTP` | Tetapkan `0` pada produksi. Mode pengembangan HTTP terbatas pada loopback. |

Untuk systemd, tetapkan direktori kerja dan berkas lingkungan sesuai direktori instalasi produksi. Jalankan layanan melalui `.venv/bin/python -m src.server` atau `satu-data-aceh` agar middleware autentikasi akun aktif. Gunakan [konfigurasi Nginx](../deploy/nginx.conf) sebagai rujukan untuk dasbor, API, dan transport MCP. Periksa konfigurasi dengan `sudo nginx -t` sebelum memuatnya.

Pada pemasangan pertama, salin isi [`public/`](../public/) ke direktori `root` yang ditetapkan di konfigurasi Nginx. Untuk pembaruan berikutnya, gunakan skrip rilis di bawah agar pemasangan backend dan aset terurut.

Untuk Docker, isi konfigurasi lalu jalankan `docker compose up -d --build`. [Compose](../compose.yaml) memetakan port ke loopback host dan menyimpan data akun di volume `account-data`. Pertahankan volume saat memperbarui kontainer. [Templat Render](../render.yaml) menggunakan paket yang mendukung disk persisten.

## Rilis ke VPS yang sudah berjalan

Skrip [rilis VPS](../deploy/release-vps.sh) digunakan untuk instalasi produksi systemd dengan Nginx pada domain proyek. Jalankan dari direktori repositori produksi dengan pohon kerja bersih. Gunakan SHA lengkap commit rilis.

```bash
git fetch origin main
sudo -v
GIT_PAGER=cat bash deploy/release-vps.sh SHA_COMMIT_LENGKAP
```

Skrip mencadangkan basis data SQLite dan aset web, memperbarui backend, memasang aset, lalu memeriksa HTTPS dan metadata OAuth. Jika rilis gagal, skrip memulihkan kode dan aset ke versi sebelumnya. Pemulihan basis data dilakukan secara terpisah dari cadangan.

Periksa `/health` untuk status proses dan cache katalog. Untuk memastikan layanan eksternal, lakukan pencarian portal atau uji operasi BPS dengan akun uji. `/health` sendiri mengukur kesiapan proses.

## Email akun

Konfigurasikan `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, dan `SMTP_FROM` pada layanan Python. Gunakan `SMTP_PASSWORD` atau `SMTP_PASSWORD_FILE` untuk kredensial SMTP. Jika keduanya ditetapkan, layanan memprioritaskan berkas. Berikan izin baca hanya kepada akun layanan. Pada Docker, pasang berkas sebagai volume dan gunakan lokasinya di dalam kontainer.

Port 465 memakai TLS langsung dan port 587 memakai STARTTLS wajib. Untuk Gmail, gunakan sandi aplikasi. Pilih alamat pengirim yang diizinkan penyedia dan setel `SMTP_DAILY_LIMIT` untuk batas pengiriman aplikasi.

Jika verifikasi gagal dikirim, pengguna dapat memakai **Kirim ulang verifikasi** setelah jeda. Periksa log SMTP, batas pengiriman, folder spam, dan kecocokan `ACCOUNTS_PUBLIC_ORIGIN`. Tautan akun selalu dibentuk dari origin yang dikonfigurasi.

## Cadangan dan rotasi

- Cadangkan SQLite dengan API pencadangan atau saat layanan berhenti. Simpan cadangan kunci enkripsi secara terpisah dan batasi akses ke keduanya.
- Lakukan rotasi kunci saat layanan berhenti. Cadangkan basis data dan kunci yang sedang digunakan, lalu jalankan [skrip rotasi](../scripts/rotate_account_key.py) dengan `ACCOUNTS_DB_PATH`, `ACCOUNTS_ENCRYPTION_KEY` lama, dan `ACCOUNTS_NEW_ENCRYPTION_KEY` baru. Perbarui kunci pada konfigurasi sebelum memulai layanan. Rotasi membatalkan sesi peramban.
