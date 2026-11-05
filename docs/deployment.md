# Deployment dan pemeliharaan MCP Satu Data Aceh

Panduan ini untuk operator server. Untuk memakai server yang sudah tersedia, ikuti [panduan pengguna dan aplikasi](panduan-pemasangan-mcp.md).

## Menyiapkan layanan Python

Gunakan Python 3.11 atau lebih baru dan salin [`.env.example`](../.env.example) ke `.env` ketika membuat instalasi baru.

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e .
cp .env.example .env
```

Buat master key sekali untuk instalasi baru dan simpan hasilnya sebagai `ACCOUNTS_ENCRYPTION_KEY` dalam konfigurasi privat atau secret manager.

```bash
python3 -c "import base64,secrets; print(base64.b64encode(secrets.token_bytes(32)).decode())"
```

| Pengaturan | Kegunaan |
| --- | --- |
| `ACCOUNTS_DB_PATH` | Lokasi SQLite di penyimpanan persisten yang bisa ditulis oleh akun layanan. |
| `ACCOUNTS_ENCRYPTION_KEY` | Master key vault. Pertahankan nilai yang cocok dengan database saat restart atau pemulihan. |
| `ACCOUNTS_PUBLIC_ORIGIN` | Origin HTTPS utama tanpa path untuk tautan email dan discovery OAuth. |
| `ACCOUNTS_ALLOWED_ORIGINS` | Origin dashboard tambahan yang diizinkan, jika ada. |
| `MCP_ALLOWED_HOSTS`, `MCP_ALLOWED_ORIGINS` | Host dan origin yang diizinkan untuk transport MCP. Sesuaikan dengan Nginx dan klien browser yang digunakan. |
| `MCP_TRANSPORT` | `both` mengaktifkan Streamable HTTP dan SSE. Gunakan `streamable-http` jika hanya menyediakan `/mcp`. |
| `MCP_HOST`, `MCP_PORT` | Di VPS, gunakan loopback seperti `127.0.0.1:8000` di belakang Nginx HTTPS. |
| `OAUTH_CIMD_HOSTS` | Daftar host metadata klien OAuth tepercaya. Lihat [aturan discovery](referensi-mcp.md#oauth-dan-discovery). |
| `ACCOUNTS_DEV_HTTP` | Tetapkan `0` pada produksi. Mode pengembangan HTTP terbatas pada loopback. |

Untuk systemd, atur direktori kerja dan environment file sesuai checkout produksi. Jalankan layanan melalui `.venv/bin/python -m src.server` atau entrypoint `satu-data-aceh` agar middleware akun terpasang. Gunakan [konfigurasi Nginx](../deploy/nginx.conf) sebagai contoh routing dashboard, API, dan transport MCP. Periksa konfigurasi dengan `sudo nginx -t` sebelum memuatnya.

Pada pemasangan pertama, salin isi [`public/`](../public/) ke direktori `root` yang ditetapkan di konfigurasi Nginx. Untuk pembaruan berikutnya, gunakan skrip rilis di bawah agar pemasangan backend dan aset terurut.

Untuk Docker, isi konfigurasi lalu jalankan `docker compose up -d --build`. [Compose](../compose.yaml) memetakan port ke loopback host dan menyimpan akun di volume `account-data`. Pertahankan volume saat memperbarui container. [Template Render](../render.yaml) memakai paket yang mendukung disk persisten.

## Rilis ke VPS yang sudah berjalan

Skrip [rilis VPS](../deploy/release-vps.sh) ditujukan untuk checkout produksi systemd dengan Nginx pada domain proyek. Dari checkout yang bersih, ambil commit rilis dan gunakan SHA lengkap yang akan dipasang.

```bash
git fetch origin main
sudo -v
GIT_PAGER=cat bash deploy/release-vps.sh SHA_COMMIT_LENGKAP
```

Skrip mencadangkan database SQLite dan aset web, memperbarui backend, memasang aset, lalu memeriksa HTTPS dan discovery OAuth. Jika langkah rilis gagal, skrip memulihkan kode dan aset sebelumnya. Cadangan database tetap tersedia untuk pemulihan yang ditinjau secara terpisah. Jika checkout lama belum memuat skrip, ambil skrip dari commit rilis sebelum menjalankannya dari direktori checkout.

Periksa `/health` untuk status proses dan cache katalog. Untuk memastikan layanan eksternal, lakukan pencarian portal atau uji operasi BPS dengan akun uji. `/health` sendiri mengukur kesiapan proses.

## Email akun

Konfigurasikan `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, dan `SMTP_FROM` pada layanan Python. Gunakan `SMTP_PASSWORD` atau `SMTP_PASSWORD_FILE` untuk rahasia SMTP. Jika keduanya disetel, berkas diprioritaskan. Beri izin baca kepada akun layanan saja. Pada Docker, mount berkas dan gunakan path di dalam container.

Port 465 memakai TLS langsung dan port 587 memakai STARTTLS wajib. Untuk Gmail, gunakan sandi aplikasi. Pilih alamat pengirim yang diizinkan penyedia dan setel `SMTP_DAILY_LIMIT` untuk batas pengiriman aplikasi.

Jika verifikasi gagal dikirim, pengguna dapat memakai **Kirim ulang verifikasi** setelah jeda. Periksa log SMTP, batas pengiriman, folder spam, dan kecocokan `ACCOUNTS_PUBLIC_ORIGIN`. Tautan akun selalu dibentuk dari origin yang dikonfigurasi.

## Cadangan dan rotasi

- Cadangkan SQLite dengan API backup atau saat layanan berhenti. Cadangkan master key secara terpisah dan batasi akses ke keduanya.
- Rotasi master key saat trafik dan gateway berhenti. Cadangkan database dan key lama, lalu jalankan [skrip rotasi](../scripts/rotate_account_key.py) dengan `ACCOUNTS_DB_PATH`, `ACCOUNTS_ENCRYPTION_KEY` lama, dan `ACCOUNTS_NEW_ENCRYPTION_KEY` baru. Perbarui secret aplikasi sebelum memulai layanan. Rotasi membatalkan sesi browser.
- Untuk database lama yang belum memakai verifikasi email, migrasi mengharuskan pengguna memverifikasi akun kembali. Cadangkan database dan pertahankan master key sebelum migrasi.
- Jika gateway Worker masih digunakan, ikuti [panduan pemisahan dan sinkronisasi Worker](pemisahan-worker.md).
