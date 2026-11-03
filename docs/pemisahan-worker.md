# Repositori Worker mandiri

Gateway Cloudflare berada di repositori lokal `MCP_SatuDataAceh_Worker/` dengan Git, lockfile, CI dan konfigurasi Wrangler sendiri. Checkout tersebut bisa dipindahkan sebagai satu direktori. Jalankan semua perintah Node dari root Worker.

```bash
npm ci
npm run typecheck
npm test
npx wrangler deploy --dry-run
```

Proyek Python menjadi sumber utama untuk empat berkas JSON di `src/`, fixture kesepadanan, dan aset di `public/`. Saat Worker membutuhkan pembaruan aset atau aturan, jalankan skrip ini dari root Worker, tinjau diff snapshot, lalu uji Worker.

```bash
python3 scripts/sync-shared.py /path/ke/MCP_SatuDataAceh
```

Worker tetap membutuhkan `ACCOUNTS_SERVICE_URL` yang menunjuk ke origin HTTPS Python dan `ACCOUNTS_SERVICE_SECRET` dengan nilai yang sama di kedua layanan. Bila dashboard Worker dipakai, daftarkan origin publik Worker pada `ACCOUNTS_ALLOWED_ORIGINS` Python. Database SQLite dan kunci vault berada pada layanan Python. Klien OAuth memakai endpoint Python `https://www.mcpsatudataaceh.web.id/mcp`.

Saat mengalihkan deployment Cloudflare yang sudah ada, pertahankan nama Worker, domain, dan konfigurasi secret. Arahkan pipeline ke repositori Worker, lalu verifikasi `/health`, katalog BPS, login dashboard, dan panggilan MCP dengan token manual.
