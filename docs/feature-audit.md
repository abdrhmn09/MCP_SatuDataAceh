# Audit fitur setelah laporan ChatGPT Web

Laporan 3 November 2026 mencakup delapan tool, bukan pengujian langsung seluruh 59 operasi BPS. Autentikasi OAuth tetap dipertahankan; temuan utama menyangkut semantik dan kualitas hasil.

| Fitur/perilaku | Keputusan | Alasan |
|---|---|---|
| Pemilihan sumber utama otomatis dari tahun maksimum | Dihapus | Tahun pada respons tidak membuktikan rilis terbaru, kesepadanan cakupan, atau ketepatan metodologi. |
| Mengganti hasil fetch portal dengan BPS saat portal gagal | Dihapus | Pengguna meminta dataset tertentu; penggantian sumber berpotensi mengubah indikator dan provenance. |
| Percobaan kode tahun tetap 124/123/122 dan defaultTh snapshot | Dihapus | ID periode harus berasal dari metadata BPS. Batas pagination/periode yang diperiksa dilaporkan. |
| Menyamakan credential BPS dan SDGs | Dihapus | Kedua layanan dapat memakai credential dan izin berbeda. Uji satu endpoint bukan jaminan akses seluruh layanan. |
| search/fetch | Alur utama portal | Pencarian terstruktur, pagination, data JSON, kualitas, dan cakupan observasi. |
| bps_endpoints/bps_request | Alur utama BPS | Discovery dan pengambilan operasi eksplisit tanpa pemetaan indikator yang disembunyikan. |
| bandingkan_data | Dipertahankan sebagai audit terbatas | Berguna untuk melihat keterbatasan dua sumber; tidak lagi merekomendasikan sumber resmi paling benar/terbaru. |
| cari_katalog_data/baca_isi_csv | Kompatibilitas lama | Masih dipakai klien yang sudah terhubung; dokumentasi mengarahkan alur baru ke search/fetch. Tidak dihapus pada pembaruan kompatibel ini. |
| Token manual dan SSE | Pengaturan lanjutan | Masih diperlukan sebagian klien dan deployment Worker. OAuth Streamable HTTP menjadi tampilan utama. |
| Token SDGs | Opsional dan terpisah | Hanya diperlukan untuk operasi SDGs Access, bukan untuk statistik BPS biasa. |

## Keterbatasan yang tetap perlu diperhatikan

Status CSV `valid` berarti format dapat dibaca. Kolom indikator yang ambigu tidak dipilih sembarang. Pemeriksaan wilayah/tahun/subperiode/kategori menggunakan metadata baris yang tersedia dan dapat menghasilkan status belum pasti. Nama wilayah tidak dipaksa menjadi kode wilayah BPS, dan kesamaan angka per observasi tidak disimpulkan.

Periode BPS diambil dari metadata dengan batas permintaan agar tool tidak berjalan tanpa batas. Jika sebagian metadata tidak diperiksa, hasil tidak diberi label sebagai rilis terbaru yang tersedia. Gunakan bps_request untuk analisis dengan pemilihan variabel, periode, dan dimensi yang eksplisit.

## Verifikasi

Jalankan `python3 -m unittest discover -s tests -q`, `npm --prefix worker run typecheck`, dan `npm --prefix worker test`. Regresi laporan tersedia pada `tests/test_report_regressions.py` dan `worker/tests/report.test.ts`, termasuk unknown operation, schema batas baris, null/nonfinite, kesepadanan wilayah/periode, dan credential SDGs terpisah.
