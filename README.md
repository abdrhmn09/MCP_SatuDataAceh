# MCP Satu Data Aceh

Server MCP independen untuk Portal Satu Data Aceh dan [Web API BPS](https://webapi.bps.go.id/documentation/). Menyediakan 8 tool dan 59 operasi BPS sesuai snapshot spesifikasi resmi. Ini bukan situs resmi BPS.

## Alur pengguna

1. Daftar akun dengan email dan password minimal 12 karakter.
2. Simpan **kode pemulihan** yang hanya ditampilkan sekali. Verifikasi email melalui tautan yang dikirim sebelum login. Tidak ada email reset password otomatis.
3. Setelah email terverifikasi, login dan simpan API key BPS pada dashboard. Token SDGs terpisah dapat disimpan jika diperlukan.
4. Buat **token akses MCP** untuk setiap klien. Token hanya ditampilkan sekali, dengan masa berlaku 1–90 hari (default 30).
5. Pasang header koneksi klien: `Authorization: Bearer TOKEN_MCP_ANDA`.
6. Server mengenali akun, mendekripsi key milik akun itu untuk permintaan BPS, dan menyamarkan credential pada respons.

Password menggunakan scrypt (N=131072, r=8, p=1, salt acak). API key dienkripsi AES-256-GCM dengan nonce acak dan associated data yang mengikat ciphertext ke pengguna/layanan. Kunci enkripsi utama berasal dari environment, terpisah dari database. Session/token MCP dan kode pemulihan hanya disimpan sebagai hash SHA-256 dari secret acak berentropi tinggi. Email dan metadata akun disimpan sebagai metadata biasa; seluruh berkas SQLite **bukan** database terenkripsi.

Dashboard dapat mengganti/menghapus key, membuat/mencabut token, mengganti password, dan memulihkan akun menggunakan kode pemulihan. Ganti/reset password mencabut seluruh sesi dan token. Reset juga mengganti kode pemulihan. Jika password **dan** kode pemulihan hilang, tidak ada reset mandiri. Tidak ada akses baca ulang key BPS atau token yang pernah dibuat dari dashboard.

## Perubahan dari versi sebelumnya

**Remote MCP sekarang wajib menggunakan token akun.** API key BPS langsung pada `Authorization`/`X-BPS-API-Key` tidak lagi mengautentikasi akses remote. Pengguna lama perlu daftar, simpan key, lalu ganti header klien dengan token MCP. Tidak ada migrasi credential yang sebelumnya hanya berada di browser/header karena credential itu memang tidak disimpan.

Cookie login browser tidak dapat digunakan sebagai token MCP. Browser explorer memakai sesi HttpOnly dan CSRF, sedangkan `/mcp`, `/sse`, dan `/messages/` mewajibkan Bearer token MCP. Kepemilikan session transport diperiksa. Pencabutan dan kedaluwarsa diperiksa pada request berikutnya; permintaan upstream yang sudah berjalan tidak otomatis dibatalkan. Penghapusan key membuat tool BPS gagal sampai key baru disimpan; tool katalog Aceh tetap dapat digunakan oleh token akun yang valid.

Ini adalah autentikasi **Bearer manual**, bukan implementasi OAuth/SSO. Gunakan klien MCP yang mendukung header manual. Untuk SSE, kirim token pada GET `/sse` **dan** POST `/messages/`. Browser login tidak otomatis mengonfigurasi koneksi klien AI.

## Deployment VPS Python

Gunakan Python 3.11+ dan Nginx HTTPS. Instal dependensi:

```bash
python3 -m pip install -e .
cp .env.example .env
```

**Buat master key sekali**, simpan hasilnya sebagai `ACCOUNTS_ENCRYPTION_KEY` dalam `.env` atau secret manager. Jangan commit atau mencetaknya ke log produksi:

```bash
python3 -c "import base64,secrets; print(base64.b64encode(secrets.token_bytes(32)).decode())"
```

Konfigurasi penting:

```dotenv
MCP_TRANSPORT=sse
MCP_HOST=127.0.0.1
MCP_PORT=8000
ACCOUNTS_ENCRYPTION_KEY=ISI_DENGAN_MASTER_KEY_YANG_DIBUAT_SENDIRI
ACCOUNTS_DB_PATH=/lokasi/persisten/accounts.sqlite3
ACCOUNTS_PUBLIC_ORIGIN=https://www.mcpsatudataaceh.web.id
ACCOUNTS_ALLOWED_ORIGINS=https://mcpsatudataaceh.web.id
ACCOUNTS_DEV_HTTP=0
MCP_ALLOWED_HOSTS=www.mcpsatudataaceh.web.id,mcpsatudataaceh.web.id
MCP_ALLOWED_ORIGINS=https://www.mcpsatudataaceh.web.id,https://mcpsatudataaceh.web.id,https://mcpplaygroundonline.com
```

`ACCOUNTS_PUBLIC_ORIGIN`/`ACCOUNTS_ALLOWED_ORIGINS` adalah origin halaman **dashboard**, tidak perlu memasukkan playground. `MCP_ALLOWED_ORIGINS` mengizinkan klien MCP browser. Sesuaikan hostname dan direktori. Jalankan `python3 -m src.server` dari proyek; service systemd harus membaca environment/WorkingDirectory yang sesuai. Server gagal startup bila master key tidak ada/tidak sesuai dengan database yang sudah ada.

Untuk Docker Compose, isi `.env`, lalu:

```bash
docker compose up -d --build
```

`compose.yaml` menyimpan database di named volume `account-data`, dengan port hanya pada loopback VPS. Jangan gunakan `docker compose down -v` kecuali ingin menghapus data. Image berjalan non-root. Nginx meneruskan trafik HTTPS ke `127.0.0.1:8000`.

Contoh konfigurasi lengkap ada di [deploy/nginx.conf](deploy/nginx.conf), termasuk route akun, explorer, SSE, Streamable HTTP, CORS dan header. Untuk landing page Nginx statis:

```bash
sudo install -m 644 public/index.html /var/www/mcpsatudataaceh.web.id/index.html
sudo install -m 644 deploy/nginx.conf /etc/nginx/sites-available/mcpsatudataaceh.web.id
sudo nginx -t && sudo systemctl reload nginx
```

Restart/recreate aplikasi setelah mengganti kode atau environment. SSE memakai `/sse`; pilih `MCP_TRANSPORT=streamable-http` untuk `/mcp`. Satu proses Python menjalankan transport yang dipilih, bukan keduanya sekaligus. `/health` hanya liveness dan status cache, bukan bukti upstream BPS tersedia.

Template `render.yaml` sekarang membutuhkan disk persisten dan plan yang mendukung disk (starter). Ini dapat menimbulkan biaya bila Anda memilih deploy melalui Render; tidak ada deployment otomatis dari pekerjaan lokal. Jangan menaruh database akun pada filesystem sementara layanan gratis.

## Verifikasi email Gmail

SMTP berjalan pada layanan Python kanonis, termasuk bila dashboard diakses melalui Worker. Isi secret berikut pada `.env` **di VPS** atau secret manager; file `.env` lokal tidak dikirim melalui Git:

```dotenv
SMTP_HOST=smtp.gmail.com
SMTP_PORT=465
SMTP_USERNAME=sender@example.com
SMTP_FROM=sender@example.com
SMTP_PASSWORD=PASSWORD_APLIKASI_GMAIL_ANDA
SMTP_DAILY_LIMIT=100
```

Gunakan password aplikasi Gmail, bukan password login biasa. Port 465 memakai implicit TLS; port 587 memakai STARTTLS wajib dengan pemeriksaan sertifikat. Tidak ada mode SMTP plaintext. `SMTP_FROM` sebaiknya sama dengan akun SMTP atau alias yang sudah diizinkan penyedia. Password SMTP hanya disimpan pada konfigurasi rahasia, tidak pada database akun, kode, respons, atau log. Alternatif yang disarankan adalah `SMTP_PASSWORD_FILE=/lokasi/rahasia/gmail-app-password` agar `.env` hanya memuat path. Berkas tersebut harus berizin 0600 (direktori 0700) dan dapat dibaca akun service. Jika kedua opsi diisi, berkas rahasia diprioritaskan. Pada Docker, mount berkas ke container dan setel path container; jangan menggunakan path host yang tidak ter-mount. Berkas di `/tmp` hanya cocok untuk konfigurasi lokal sementara, bukan penyimpanan production yang tahan reboot.

Alur baru: daftar → simpan kode pemulihan → buka email verifikasi → tekan **Verifikasi email** → login. Token verifikasi acak hanya disimpan sebagai hash, berlaku satu jam, dan seluruh tautan untuk akun itu dibatalkan setelah satu tautan dipakai. Token berada pada fragment URL (`#verify=...`), dihapus dari address bar oleh halaman, lalu dikirim dengan POST setelah konfirmasi agar tidak masuk access log atau terpakai hanya karena pemindai email membuka tautan.

Jika SMTP gagal, akun tetap pending dan kode pemulihan tetap diberikan. Tunggu satu menit lalu gunakan **Kirim ulang verifikasi** dengan email dan password yang benar. Resend dibatasi satu per menit, tiga per jam per akun, dan budget global `SMTP_DAILY_LIMIT` (default 100/hari; ini batas aplikasi, bukan kuota resmi Gmail). Periksa folder spam. Penerimaan SMTP belum menjamin pesan tiba di inbox.

Database lama dimigrasikan otomatis: email ditandai belum terverifikasi dan sesi/token lama dicabut. Pengguna lama harus meminta kirim ulang verifikasi, membuktikan kepemilikan email, lalu login dan membuat token MCP baru. Credential BPS terenkripsi tetap tersimpan. Master key divalidasi sebelum migrasi yang mengubah status akun. Backup DB dan master key sebelum upgrade.

`ACCOUNTS_PUBLIC_ORIGIN` harus berisi origin HTTPS publik yang benar; tautan tidak dibentuk dari Host request. Jangan menggunakan IP lokal/URL preview untuk email produksi. Untuk Worker, tautan tetap menuju origin Python kanonis; status verifikasi dibagikan melalui database kanonis. Pastikan kedua origin memakai versi frontend terbaru. SMTP pada `.env` lokal belum mengonfigurasi SMTP di VPS.

## Cloudflare Worker

Worker tetap stateless; akun/SQLite/vault dikelola oleh **layanan Python kanonis**. Worker harus dihubungkan ke origin Python HTTPS yang berbeda, bukan ke URL Worker itu sendiri:

```text
ACCOUNTS_SERVICE_URL=https://www.mcpsatudataaceh.web.id
ACCOUNTS_SERVICE_SECRET=SECRET_JEMBATAN_ACAK_MINIMAL_32_KARAKTER
```

Simpan secret melalui `wrangler secret put ACCOUNTS_SERVICE_SECRET` dan setel secret identik pada environment Python. Tambahkan origin publik Worker ke `ACCOUNTS_ALLOWED_ORIGINS` Python agar login melalui gateway diterima. Worker memverifikasi token/sesi setiap request dengan `/internal/accounts/resolve`, yang membutuhkan shared secret. Key hasil resolusi hanya dipakai pada scope request, tidak ditulis ke environment global/database Worker. Jaga secret jembatan dan origin Python; Worker adalah bagian tepercaya dari infrastruktur yang memproses key plaintext di memori.

Route akun diproksikan ke Python; cookie HttpOnly dikirim oleh browser pada origin Worker. Cegah pencatatan cookie/header/token pada proxy/tracing. Tanpa layanan akun terkonfigurasi/tersedia, Worker gagal tertutup, bukan menggunakan key operator. Endpoint MCP Worker: `/mcp`. Landing page disajikan dari `public/` via Assets.

```bash
cd worker
npm ci
npm run dev
```

## Penyimpanan, backup, dan rotasi

- Gunakan volume persisten dengan akses terbatas ke akun service. File database dibuat mode 0600.
- Backup database menggunakan SQLite backup API atau saat aplikasi dihentikan, lalu backup master key secara **terpisah**. Perlakukan database (email/hash) dan master key sebagai informasi sensitif.
- Kehilangan master key menyebabkan key BPS tersimpan tidak dapat didekripsi. Jangan membuat key baru setiap restart.
- Rotasi master key: hentikan trafik/aplikasi dan gateway, backup DB dan key lama, setel `ACCOUNTS_DB_PATH`, `ACCOUNTS_ENCRYPTION_KEY` lama dan `ACCOUNTS_NEW_ENCRYPTION_KEY` baru pada environment, jalankan `python3 scripts/rotate_account_key.py`, lalu ubah secret server ke key baru sebelum restart. Seluruh sesi browser dibatalkan. Token MCP tetap berlaku sampai dicabut/kedaluwarsa.
- Rate limit login/daftar/pemulihan tersimpan di SQLite (30 percobaan/IP dan 10/identitas per 15 menit). Hashing dibatasi dua pekerjaan paralel per proses. Rate limit tool masih berada di memori proses/isolate dan belum terdistribusi.
- Gunakan HTTPS produksi. `ACCOUNTS_DEV_HTTP=1` hanya untuk preview loopback; tidak boleh bind publik. Origin dashboard harus dicocokkan dengan port preview. Tidak ada analytics atau penyimpanan credential di localStorage.

## Tools dan akses BPS

| Tool | Fungsi |
| --- | --- |
| `search` | Cari katalog Aceh; opsional `wilayah`, `produsen`, `limit` 1–50 dan `offset`; respons `total`/`next_offset`. |
| `fetch` | Preview observasi dengan sumber, satuan, dan rentang tahun data. |
| `cari_katalog_data` | Katalog naratif dan tautan CSV. |
| `baca_isi_csv` | Baca URL CSV publik HTTPS, maksimal 50 baris preview. |
| `bandingkan_data` | Tinjau kesepadanan dua sumber untuk indikator kurasi; tidak menghitung selisih pasangan observasi. |
| `bps_endpoints` | Katalog 59 operasi; isi `operation` untuk skema parameter. Tidak membutuhkan key BPS, tetapi koneksi remote tetap membutuhkan token MCP. |
| `bps_request` | Jalankan operasi GET BPS dengan parameter allowlist yang divalidasi. |
| `bps_check_key` | Uji key tersimpan pada `bps` atau `sdgs`. |

Cakupan operasi: domain, subjek, variabel/dimensi, periode, data dinamis, tabel statis/CSA, siaran pers, publikasi, indikator strategis, infografis, berita, glosarium, perdagangan, klasifikasi, sensus, Yearbook Dataset, SDGs/SDDS dan SDGs Access. Ketersediaan tetap bergantung pada data/API/key/kuota BPS. File PDF/unduhan publikasi mengikuti tautan yang disediakan upstream.

Contoh argumen tool (tanpa credential):

```json
{"operation":"listVariables","parameters":{"domain":"1100","page":1}}
```

Temukan kode `var` via `listVariables`, `th` via `listPeriods`, dan dimensi lewat operasi referensi. Kode `th` bukan tahun kalender. Gunakan `getData` sesuai skema operasi; domain nasional `0000`, Aceh `1100`. Ikuti pagination BPS secara eksplisit. Batas respons BPS/CSV 5 MiB, katalog 32 MiB, HTML 2 MiB. Registry bersama: `src/bps_operations.json`; generator `scripts/update_bps_registry.py` menggunakan YAML spesifikasi resmi yang diunduh dan dependensi development PyYAML.

Pemetaan indikator, sinonim dan kamus satuan disimpan dalam JSON bersama untuk Python/Worker. Tahun publikasi dipisahkan dari tahun observasi. Cache kedaluwarsa/local fallback ditandai; retry katalog setelah kegagalan memakai jeda 30 detik. Key BPS yang pernah ter-commit harus tetap dicabut melalui akun BPS; menghapusnya dari kode tidak mencabut key lama.

## STDIO dan pengujian

STDIO lokal tetap menggunakan `BPS_API_KEY` dari environment pemilik proses, tanpa login HTTP. Jangan mengekspos STDIO melalui adapter publik yang melewati middleware akun. Semua deployment remote harus menggunakan entrypoint resmi `python3 -m src.server`/`satu-data-aceh` agar middleware autentikasi terpasang.

```bash
python3 -m unittest discover -s tests -v
cd worker
npm run typecheck
npm test
```

Tes memakai database/credential sintetis dan mock BPS, bukan key pengguna. `npm run test:live` terpisah dan memerlukan key di environment. UI di `public/index.html` dan salinan paket `src/static/index.html` harus identik. Verifikasi email tersedia; OAuth otomatis, reset password lewat email, dan MFA belum tersedia.
