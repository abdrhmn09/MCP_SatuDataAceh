# Integrasi bot dan agen AI dengan MCP Satu Data Aceh

MCP Satu Data Aceh dapat digunakan sebagai sumber data publik untuk bot RAG dan agen AI. Backend aplikasi menggunakan RAG untuk menelusuri dokumen internal dan MCP untuk mengakses katalog Aceh atau statistik BPS. Koneksi ke layanan publik dikonfigurasi dari backend aplikasi.

## Penyiapan akses

1. Daftarkan akun dengan email yang dapat dikelola tim penanggung jawab bot, lalu verifikasi email. Untuk produksi, gunakan akun yang dikelola instansi atau tim. Pisahkan akun jika aplikasi harus memakai kredensial BPS yang berbeda.
2. Jika aplikasi memerlukan statistik BPS, simpan kunci Web API BPS melalui menu **API key**. Penelusuran Portal Satu Data Aceh dapat dilakukan dengan token MCP. Gunakan token SDGs Access khusus untuk operasi SDGs Access.
3. Buka **Aplikasi terhubung → Token manual**. Beri nama token sesuai aplikasi dan lingkungan, misalnya `bot-pelayanan-produksi`. Simpan token di penyimpanan rahasia backend. Gunakan token terpisah untuk setiap aplikasi dan lingkungan agar akses dapat dicabut secara independen.

Server memakai token untuk mengenali akun dan mengambil kredensial BPS yang tersimpan. Token berbeda dari akun yang sama tetap memakai kredensial akun tersebut. Gunakan akun terpisah bila perlu mengisolasi kredensial antarinstansi atau antara pengembangan dan produksi.

## Konfigurasi koneksi

| Pengaturan | Nilai |
|---|---|
| Nama koneksi | `satu-data-aceh` |
| Transport MCP | Streamable HTTP |
| URL server | `https://www.mcpsatudataaceh.web.id/mcp` |
| Header autentikasi | `Authorization: Bearer <TOKEN_MCP>` |

Gunakan nilai tersebut pada konektor MCP yang mendukung header autentikasi. Pada aplikasi tanpa konektor bawaan, gunakan SDK MCP di backend. Untuk akses berdasarkan akun pengguna, gunakan **OAuth Authorization Code dengan PKCE**. Untuk aplikasi yang berjalan otomatis menggunakan akun layanan, gunakan token manual akun pengelola aplikasi.

Simpan token di backend atau penyimpanan rahasia platform. Hindari menyertakannya dalam JavaScript peramban, instruksi model, atau log. Kelola kunci API BPS melalui dasbor MCP.

## Contoh integrasi Python

Salin folder [`examples/custom-agent`](../examples/custom-agent/) ke proyek bot. Dari folder tersebut, gunakan Python 3.11 atau lebih baru dalam lingkungan virtual.

```bash
python -m pip install -r requirements.txt
```

Salin `.env.example` menjadi `.env` dan isi `SDA_MCP_TOKEN`. Sebagai alternatif, tetapkan token melalui variabel lingkungan. URL publik digunakan ketika `SDA_MCP_URL` kosong. Jalankan perintah berikut untuk memeriksa koneksi.

```bash
python sda_mcp.py
```

Skrip memeriksa daftar alat MCP, menelusuri Portal Satu Data Aceh, lalu memanggil operasi BPS `listDomains` dengan `type=prov`. Untuk memeriksa akses portal saja, jalankan `python sda_mcp.py --portal-only`. Hasil uji BPS berlaku untuk operasi sampel yang diperiksa.

Setelah koneksi berhasil, fungsi `connect_mcp()` dapat digunakan langsung dari backend bot. SDK mengurus negosiasi protokol dan pengiriman header untuk setiap permintaan.

```python
from sda_mcp import call_data, connect_mcp

async def cari_dataset_aceh(topik: str) -> dict:
    async with connect_mcp() as client:
        return await call_data(client, "search", {"query": topik, "limit": 5})
```

Jika backend mengimpor fungsi, sediakan variabel lingkungan melalui konfigurasi aplikasi. Saat dijalankan dari terminal, skrip memuat `.env` dari direktori skrip.

## Pemilihan sumber data

| Pertanyaan pengguna | Sumber dan tindakan |
|---|---|
| Isi SOP atau surat edaran instansi | Cari dokumen melalui RAG internal. |
| Dataset publik dari Portal Satu Data Aceh | Panggil `search` dan gunakan ID hasilnya pada `fetch` bila isi dataset diperlukan. |
| Statistik dari BPS | Gunakan `bps_endpoints` untuk memeriksa parameter. Panggil `bps_request` dengan operasi, wilayah, dan periode yang sesuai. Periksa nilai `ok` pada hasil BPS. |
| Pertanyaan yang membutuhkan beberapa sumber | Gabungkan hasil RAG dan MCP di backend. Pertahankan rujukan, wilayah, periode, dan satuan untuk setiap sumber. |

Tetapkan alat yang tersedia bagi model melalui backend. Untuk penelusuran dasar, gunakan `search`, `fetch`, `bps_endpoints`, dan `bps_request`. Kirim hanya kata kunci atau parameter statistik yang diperlukan untuk mengakses data publik. Simpan dokumen internal dan konteks percakapan lainnya di backend aplikasi.

## Pengelolaan token

| Kondisi | Tindakan |
|---|---|
| HTTP 401 saat tersambung | Periksa header Bearer, token yang dipasang, dan apakah token kedaluwarsa atau dicabut. |
| Portal berhasil dan BPS melaporkan `missing_credential` | Simpan API key BPS pada akun yang membuat token bot. |
| BPS melaporkan `credential_rejected` atau `data_unavailable` | Periksa izin key atau cakupan parameter dan data pada dashboard. |

Token manual berlaku 1–90 hari sesuai pengaturan saat dibuat. Sebelum masa berlaku berakhir, buat token pengganti, perbarui konfigurasi rahasia aplikasi, periksa koneksi, lalu cabut token sebelumnya. Catat penanggung jawab, aplikasi, lingkungan, dan tanggal kedaluwarsa tanpa menyertakan nilai token.

Rujukan [MCP Python SDK untuk Streamable HTTP](https://py.sdk.modelcontextprotocol.io/client/transports/) dan [panduan pemasangan MCP Satu Data Aceh](panduan-pemasangan-mcp.md).
