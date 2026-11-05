# Menghubungkan bot atau AI agent ke MCP Satu Data Aceh

Bot RAG instansi dapat memakai MCP Satu Data Aceh sebagai sumber data eksternal. Backend bot tetap mencari dokumen internal melalui RAG dan memakai MCP untuk mencari dataset publik Aceh atau mengambil statistik BPS. Seluruh pengaturan koneksi ada di backend bot. Developer tidak perlu memasang atau memodifikasi server MCP.

## Siapkan akses dari dashboard

1. Daftarkan akun dengan email yang dapat dikelola tim penanggung jawab bot, lalu verifikasi email. Untuk produksi, gunakan akun yang dikelola instansi atau tim. Pisahkan akun jika aplikasi harus memakai kredensial BPS yang berbeda.
2. Simpan API key Web API BPS di menu **API key** akun tersebut jika bot memerlukan BPS. Pencarian Portal Satu Data Aceh dapat dipakai dengan token MCP tanpa key BPS. Token SDGs Access hanya diperlukan untuk operasi SDGs.
3. Buka **Aplikasi terhubung → Token manual**. Buat token dengan nama yang menunjukkan aplikasi dan lingkungan, misalnya `bot-pelayanan-produksi`. Simpan token yang tampil ke penyimpanan rahasia backend. Buat token berbeda untuk tiap bot dan lingkungan agar masing-masing dapat dicabut.

Server memakai token untuk mengenali akun dan mengambil kredensial BPS yang tersimpan. Token berbeda dari akun yang sama tetap memakai kredensial akun tersebut. Gunakan akun terpisah bila perlu mengisolasi kredensial antarinstansi atau antara pengembangan dan produksi.

## Isi pengaturan koneksi di backend bot

| Pengaturan | Nilai |
|---|---|
| Nama koneksi | `satu-data-aceh` |
| Transport MCP | Streamable HTTP |
| URL server | `https://www.mcpsatudataaceh.web.id/mcp` |
| Header autentikasi | `Authorization: Bearer <TOKEN_MCP>` |

Jika platform agent sudah memiliki konektor MCP yang mendukung header, isi tabel di atas dari pengaturan platform. Jika framework belum memiliki konektor MCP, pasang SDK MCP pada proyek bot dan gunakan URL serta header yang sama. Untuk aplikasi yang setiap penggunanya perlu memakai akun atau key BPS masing-masing, gunakan **OAuth Authorization Code dengan PKCE** agar pengguna menyetujui akses dengan akunnya sendiri. Bot layanan yang berjalan otomatis dapat memakai token manual milik akun pengelola bot.

Tempatkan token hanya di backend atau penyimpanan rahasia platform. Jauhkan token dari JavaScript browser, prompt model, dan log. API key BPS cukup dikelola melalui dashboard MCP.

## Contoh Python yang bisa langsung diuji

Salin folder [`examples/custom-agent`](../examples/custom-agent/) ke proyek bot. Dari folder tersebut, gunakan Python 3.11 atau lebih baru dalam lingkungan virtual.

```bash
python -m pip install -r requirements.txt
```

Salin `.env.example` menjadi `.env` dan isi `SDA_MCP_TOKEN`, atau injeksikan token melalui environment saat menjalankan proses. Contoh otomatis menggunakan URL publik bila `SDA_MCP_URL` kosong. Setelah itu jalankan perintah berikut.

```bash
python sda_mcp.py
```

Skrip memeriksa daftar tool, mencoba pencarian Portal Satu Data Aceh, lalu memanggil operasi BPS `listDomains` dengan `type=prov`. Jika bot hanya menggunakan portal, jalankan `python sda_mcp.py --portal-only`. Lolos uji BPS berarti operasi sampel merespons dengan kredensial akun tersebut.

Setelah koneksi berhasil, fungsi `connect_mcp()` dapat digunakan langsung dari backend bot. SDK mengurus negosiasi protokol dan pengiriman header untuk setiap permintaan.

```python
from sda_mcp import call_data, connect_mcp

async def cari_dataset_aceh(topik: str) -> dict:
    async with connect_mcp() as client:
        return await call_data(client, "search", {"query": topik, "limit": 5})
```

Untuk fungsi yang diimpor backend, sediakan variabel lingkungan dari deployment atau pemuat konfigurasi bot. Pemanggilan skrip dari terminal memuat `.env` contoh secara otomatis.

## Arahkan permintaan ke sumber yang sesuai

| Pertanyaan pengguna | Alur bot |
|---|---|
| Isi SOP atau surat edaran instansi | Cari dokumen melalui RAG internal. |
| Dataset publik dari Portal Satu Data Aceh | Panggil `search` dan gunakan ID hasilnya pada `fetch` bila isi dataset diperlukan. |
| Statistik dari BPS | Gunakan `bps_endpoints` untuk memeriksa parameter. Panggil `bps_request` dengan operasi, wilayah, dan periode yang sesuai. Periksa nilai `ok` pada hasil BPS. |
| Pertanyaan yang membutuhkan beberapa sumber | Gabungkan hasil RAG dan MCP di backend. Pertahankan rujukan, wilayah, periode, dan satuan untuk setiap sumber. |

Mulai dengan memberi agent akses ke `search`, `fetch`, `bps_endpoints`, dan `bps_request`. Backend yang menentukan tool yang tersedia untuk model. Kirim kata kunci atau parameter statistik yang diperlukan untuk pengambilan data publik. Simpan dokumen internal dan konteks percakapan yang tidak diperlukan di backend bot.

## Operasikan token per bot

| Gejala | Yang diperiksa |
|---|---|
| HTTP 401 saat tersambung | Periksa header Bearer, token yang dipasang, dan apakah token kedaluwarsa atau dicabut. |
| Portal berhasil dan BPS melaporkan `missing_credential` | Simpan API key BPS pada akun yang membuat token bot. |
| BPS melaporkan `credential_rejected` atau `data_unavailable` | Periksa izin key atau cakupan parameter dan data pada dashboard. |

Token manual berlaku 1–90 hari sesuai pengaturan saat dibuat. Sebelum token habis, buat token baru, ganti secret pada deployment bot, jalankan skrip uji, lalu cabut token lama. Catat penanggung jawab, aplikasi, lingkungan, dan tanggal kedaluwarsa. Simpan catatan tanpa nilai token.

Rujukan [MCP Python SDK untuk Streamable HTTP](https://py.sdk.modelcontextprotocol.io/client/transports/) dan [panduan pemasangan MCP Satu Data Aceh](panduan-pemasangan-mcp.md).
