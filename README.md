# MCP Satu Data Aceh

MCP Satu Data Aceh membantu AI mencari dan membaca data publik dari Portal Satu Data Aceh.

Dengan MCP ini, Anda dapat meminta AI untuk mencari dataset berdasarkan topik, menemukan data dari instansi tertentu, membaca beberapa baris awal dataset, dan membantu menjelaskan isi tabel.

## URL MCP

Gunakan URL berikut untuk layanan AI yang mendukung remote MCP:

```text
https://satu-data-aceh-mcp.mcpsatudataaceh.workers.dev/mcp
```

Server ini hanya menyediakan data publik dan tidak meminta data pribadi pengguna.

## Cara Menggunakan

Contoh pertanyaan:

```text
Cari dataset tentang kemiskinan di Aceh.
```

```text
Cari dataset kualitas air laut dan tampilkan lima baris pertama.
```

```text
Cari data penduduk berdasarkan kabupaten/kota di Aceh.
```

AI akan menggunakan MCP untuk mencari dataset, kemudian membaca data apabila URL CSV tersedia.

Jika data Satu Data Aceh hanya berisi metadata atau header tanpa angka, MCP dapat mencoba mengambil data dari BPS untuk topik yang sudah dipetakan, seperti kemiskinan. Hasil akan mencantumkan sumber data yang digunakan. Fallback BPS hanya aktif jika pengelola server sudah memasang API key BPS.

MCP memeriksa isi sumber sebelum menampilkan hasil. Jika sumber hanya berisi header, kosong, atau mengembalikan halaman HTML, hasil akan ditandai sebagai data yang belum tersedia dan tidak dianggap sebagai angka resmi.

## Pemasangan di ChatGPT

Ketersediaan fitur remote MCP bergantung pada akun dan pengaturan workspace ChatGPT.

1. Buka **Settings**.
2. Aktifkan **Developer mode** jika tersedia.
3. Buka menu **Apps**, **Connectors**, atau **MCP**.
4. Pilih opsi untuk menambahkan server baru.
5. Masukkan URL:

	 ```text
	 https://satu-data-aceh-mcp.mcpsatudataaceh.workers.dev/mcp
	 ```

6. Simpan koneksi dan mulai percakapan baru.

Uji dengan pertanyaan:

```text
Cari dataset kesehatan di Aceh.
```

Jika diminta persetujuan penggunaan tool, pilih **Allow** atau **Approve**.

## Pemasangan di Claude Desktop

Claude Desktop umumnya menggunakan MCP lokal melalui STDIO. Tambahkan konfigurasi berikut pada file konfigurasi Claude Desktop:

```json
{
	"mcpServers": {
		"satu-data-aceh": {
			"command": "/media/abdur/Data1/KKP/MCP_SatuDataAceh/.venv/bin/python",
			"args": ["-m", "src.server"],
			"cwd": "/media/abdur/Data1/KKP/MCP_SatuDataAceh"
		}
	}
}
```

Sesuaikan path jika project berada di folder lain. Setelah menyimpan konfigurasi, buka kembali Claude Desktop. Jika versi Claude Anda mendukung remote MCP, gunakan URL pada bagian **URL MCP**.

## Pemasangan di VS Code atau GitHub Copilot

1. Buka pengaturan MCP pada VS Code.
2. Tambahkan server lokal dengan konfigurasi:

	 ```json
	 {
		 "name": "satu-data-aceh",
		 "command": "/media/abdur/Data1/KKP/MCP_SatuDataAceh/.venv/bin/python",
		 "args": ["-m", "src.server"],
		 "cwd": "/media/abdur/Data1/KKP/MCP_SatuDataAceh"
	 }
	 ```

3. Aktifkan server MCP.
4. Buka Copilot Chat dan coba:

	 ```text
	 Cari dataset pendidikan di Aceh.
	 ```

Jika VS Code menyediakan koneksi remote MCP, gunakan URL pada bagian **URL MCP**.

## Pemasangan di Cursor

1. Buka **Settings** lalu pilih **MCP** atau **MCP Servers**.
2. Tambahkan konfigurasi berikut:

	 ```json
	 {
		 "mcpServers": {
			 "satu-data-aceh": {
				 "command": "/media/abdur/Data1/KKP/MCP_SatuDataAceh/.venv/bin/python",
				 "args": ["-m", "src.server"],
				 "cwd": "/media/abdur/Data1/KKP/MCP_SatuDataAceh"
			 }
		 }
	 }
	 ```

3. Simpan dan aktifkan server.

Jika Cursor menyediakan pilihan **SSE** atau **Streamable HTTP**, gunakan URL remote MCP.

## Client AI Lain

Untuk client AI yang mendukung remote MCP, gunakan:

```text
https://satu-data-aceh-mcp.mcpsatudataaceh.workers.dev/mcp
```

Pilih transport **Streamable HTTP** jika diminta. Untuk client yang hanya mendukung MCP lokal, gunakan konfigurasi STDIO berikut:

```json
{
	"command": "/media/abdur/Data1/KKP/MCP_SatuDataAceh/.venv/bin/python",
	"args": ["-m", "src.server"],
	"cwd": "/media/abdur/Data1/KKP/MCP_SatuDataAceh"
}
```

## Jika Tidak Berhasil Terhubung

Pastikan:

- URL menggunakan `https://`;
- URL berakhir dengan `/mcp`;
- tidak menambahkan port seperti `:8000`, `:8787`, atau `:443`;
- client mendukung remote MCP atau Streamable HTTP;
- untuk pemasangan lokal, file `.venv/bin/python` tersedia;
- server MCP sudah diaktifkan pada pengaturan client.

Uji server:

```text
https://satu-data-aceh-mcp.mcpsatudataaceh.workers.dev/health
```

Hasil yang benar:

```json
{
	"status": "ok",
	"service": "satu-data-aceh-mcp-worker"
}
```

## Batasan

- Data berasal dari Portal Satu Data Aceh.
- Beberapa dataset dapat memiliki metadata, tetapi belum memiliki observasi untuk periode terbaru. Dalam kondisi ini MCP akan menampilkan status sumber dan periode yang tersedia.
- Angka dari BPS hanya dapat dianggap sebagai hasil resmi jika tersedia tautan halaman atau file BPS yang dapat diverifikasi. MCP tidak menggunakan API BPS yang membutuhkan token.
- Hasil pencarian dibatasi agar respons tetap ringkas.
- Pembacaan CSV menampilkan sebagian data, bukan seluruh dataset.
- Server tidak menggunakan autentikasi dan hanya ditujukan untuk data publik.
- Fallback BPS membutuhkan API key yang dipasang oleh pengelola server, bukan oleh pengguna MCP.
- Ketersediaan remote MCP dapat berbeda berdasarkan akun, versi aplikasi, dan kebijakan provider AI.

## Sumber Data

```text
https://satudata.acehprov.go.id
```
