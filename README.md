# MCP Satu Data Aceh

MCP server untuk mencari dataset pada Portal Satu Data Aceh dan menampilkan sebagian isi CSV.

Katalog `data.json` portal saat ini berisi 4.018 dataset dengan distribution HTML (`accessURL`). Katalog tersebut tidak menyediakan `downloadURL` CSV secara langsung. Saat pencarian menemukan dataset, server mencoba mencari link `.csv` pada halaman HTML tersebut dan menggunakan `accessURL` sebagai fallback jika link CSV tidak ditemukan.

## Instalasi

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e .
```

## Menjalankan

Dari root project:

```bash
python -m src.server
```

Setelah instalasi editable, command berikut juga tersedia:

```bash
satu-data-aceh
```

## Konfigurasi

Opsional, sebelum menjalankan server:

```bash
export SATU_DATA_ACEH_CATALOG_URL="https://satudata.acehprov.go.id/data.json"
export SATU_DATA_ACEH_CACHE_TTL=3600
export SATU_DATA_ACEH_DATA_YEAR=2025
```

`SATU_DATA_ACEH_CACHE_TTL` memiliki nilai minimum 60 detik. Jika nilainya tidak valid, server menggunakan default 3600 detik.
`SATU_DATA_ACEH_DATA_YEAR` digunakan sebagai fallback ketika metadata dataset tidak memuat tahun data. Default-nya `2025`.

Server menggunakan transport MCP default dari `FastMCP`. Tambahkan perintah tersebut pada konfigurasi MCP client yang digunakan.

Untuk deployment remote tanpa autentikasi:

```bash
export MCP_TRANSPORT=sse
export MCP_HOST=0.0.0.0
export MCP_PORT=8000
export MCP_RATE_LIMIT_PER_MINUTE=60
satu-data-aceh
```

Endpoint SSE akan tersedia di `/sse` dan pemeriksaan kesehatan di `/health`. Pastikan hosting menyediakan HTTPS sebelum menghubungkannya ke ChatGPT.

Konfigurasi MCP lokal tetap menggunakan STDIO:

```json
{
	"mcpServers": {
		"satu-data-aceh": {
			"command": "/path/ke/project/.venv/bin/python",
			"args": ["-m", "src.server"],
			"cwd": "/path/ke/project"
		}
	}
}
```

Untuk ChatGPT, gunakan URL remote setelah deployment:

```text
https://domain-anda.example/sse
```

Mode remote pada project ini tidak memakai autentikasi dan hanya boleh digunakan untuk data publik pada lingkungan yang aksesnya dibatasi oleh hosting atau jaringan. Jangan menambahkan data privat sebelum autentikasi diterapkan.

Rate limiting bawaan berlaku per proses dan membatasi semua tool publik sesuai `MCP_RATE_LIMIT_PER_MINUTE`. Untuk deployment multi-instance, gunakan rate limiter pada reverse proxy atau platform hosting juga.

### Deploy dengan Docker

```bash
docker build -t satu-data-aceh-mcp .
docker run --rm -p 8000:8000 satu-data-aceh-mcp
```

### Deploy dengan Render

File `render.yaml` sudah tersedia. Hubungkan repository ke Render sebagai Blueprint. Render akan memakai `Dockerfile`, health check `/health`, dan menjalankan SSE pada port `8000`.

## Tool

- `cari_katalog_data(kata_kunci)`: mencari maksimal lima dataset berdasarkan judul, deskripsi, keyword, penerbit, atau identifier. Untuk distribution HTML, server mencoba menemukan link CSV dari halaman dataset.
- `baca_isi_csv(url, baris_maksimal=20)`: membaca maksimal 50 baris dari CSV HTTPS berukuran maksimal 5 MB.
- `search(query)`: output terstruktur kompatibel dengan integrasi remote ChatGPT.
- `fetch(id)`: mengambil isi ringkas dataset berdasarkan `identifier` dari `search`.

URL CSV lokal, HTTP biasa, alamat private, dan alamat loopback ditolak. Gunakan URL CSV yang berasal dari hasil pencarian katalog. Jika hasil pencarian hanya berisi `accessURL` HTML, buka halaman tersebut untuk mendapatkan data atau link unduhan yang benar.

## Test

```bash
python -m unittest discover -s tests -v
```

Test tidak memerlukan koneksi ke portal karena validasi input dijalankan offline.
