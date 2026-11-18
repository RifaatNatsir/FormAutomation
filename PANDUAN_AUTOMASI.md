# Automasi ulasan PLN Mobile

## Cara paling mudah: klik file BAT

Klik dua kali **`MULAI_AUTOMASI.bat`** di folder proyek ini. File BAT memakai skrip Python dan folder gambar yang ada di sebelahnya; jangan dipindahkan sendiri ke folder lain.

1. Ketik nomor part yang ditampilkan, misalnya `4` untuk Part 4, atau ketik `semua` untuk memilih semua part.
2. Daftar nomor foto, nama reviewer, dan status akan muncul.
3. Masukkan pilihan seperti `2-7, 10-15, 18, 19-25`, atau ketik `semua`.
4. Seluruh data pilihan disiapkan dan disimpan terlebih dahulu.
5. Pilih **1** untuk mengisi dan mengirim batch, **2** untuk mengisi satu foto tanpa mengirim, **3** untuk melihat status, **4** untuk mencatat hasil pemeriksaan manual, atau **5** untuk mengganti pilihan foto.

Pilihan **0** keluar dari program. Antrean yang sudah disiapkan dan progres tetap tersimpan. Nomor tidak valid akan diminta ulang. Pemeriksaan manual pada menu 4 berlaku untuk semua foto yang sedang dipilih; pilih nomor tertentu dulu bila hanya ingin memperbarui satu foto.

Saat mulai pengisian, menu otomatis menghubungkan Agent Browser dan membuka tab formulir baru. Chrome biasa harus sudah terbuka, login Google, dan mengaktifkan Remote Debugging di `chrome://inspect/#remote-debugging`. Pilih **Allow** jika Chrome meminta izin koneksi.

Menu mempertahankan retry unggah maksimal 3 percobaan dan melewati foto berstatus `terkirim` atau `perlu_cek`. Python 3 dan Agent Browser yang sudah terpasang tetap digunakan.

## Perintah terminal (opsional)

Jalankan perintah PowerShell dari folder proyek ini. Satu proses bot mengerjakan foto secara berurutan.

## Pilih foto dan siapkan data

```powershell
python isi_form_ulasan.py --part 1 --nomor "2-7, 10-15, 18, 19-25" --siapkan
```

Contoh ini memilih **20 foto Part 1**. Nomor yang berulang hanya dimasukkan sekali dan diproses menurut urutan nomor. Rentang nomor mengikuti jumlah kartu pada masing-masing part. Gunakan `--part 5` untuk Part 5 atau `--part semua` untuk memilih nomor tersebut dari seluruh part yang tersedia.

Skrip memeriksa seluruh data dan gambar pilihan sebelum membuka browser. Hasilnya:

- `antrean_ulasan_form.json`: seluruh data formulir, lokasi gambar, serta unit UP3 acak untuk pilihan tersebut.
- `progres_ulasan_form.json`: status per foto, nama reviewer, unit UP3, jumlah percobaan, waktu, dan pesan error. ID seperti `part-1/02` membedakan foto dari part berbeda. Waktu pada file progres menggunakan UTC.

Unit UP3 acak disimpan agar tetap sama ketika proses dilanjutkan. UNIT selalu `1. MAKASSAR SELATAN` dan petugas selalu `H. T.`.

## Hubungkan Chrome dan jalankan batch

Gunakan Chrome biasa yang sudah login Google dan aktifkan Remote Debugging di `chrome://inspect/#remote-debugging`. Hubungkan sesi Agent Browser, pilih Allow jika Chrome memintanya:

```powershell
agent-browser --session pln-form --auto-connect tab list
```

Jika perlu, pilih tab formulir dari daftar dengan `agent-browser --session pln-form tab t1` (ganti `t1` sesuai ID tab formulir).

Untuk mengisi **dan mengirim** semua foto pilihan:

```powershell
python isi_form_ulasan.py --part 1 --nomor "2-7, 10-15, 18, 19-25" --kirim
```

Perintah ini juga otomatis menyiapkan dan menyimpan **seluruh antrean lebih dahulu**, jadi `--siapkan` terpisah bersifat opsional. Setiap foto baru dimulai setelah respons foto sebelumnya berhasil dikonfirmasi atau pengisiannya gagal.

Tanpa `--kirim`, semua data tetap disiapkan, tetapi bot hanya mengisi satu foto yang belum terkirim, lalu berhenti di tombol Kirim. Bot tidak membuka ulasan berikutnya agar formulir yang belum dikirim tidak tertimpa.

Jalankan satu proses bot pada satu waktu dan biarkan tab formulir dikerjakan bot selama proses berlangsung.

## Status dan melanjutkan proses

Jika nomor foto yang sama kini berisi ulasan berbeda (nama, teks, rating, atau tanggal berubah), bot membuat versi progres baru. Versi lama tetap disimpan beserta status pengirimannya. ID versi baru memakai akhiran `@...` pada file progres. Menjalankan ulang versi yang sama tetap melewati respons yang sudah terkirim; mengembalikan data lama juga mengembalikan status versi lama. Pemindahan lokasi atau ekspor ulang PNG saja tidak mereset status versi yang sudah memiliki identitas data.

```powershell
python isi_form_ulasan.py --part 1 --nomor "2-7, 10-15, 18, 19-25" --status
```

| Status | Arti |
| --- | --- |
| `belum_diproses` | Belum masuk catatan bot. |
| `disiapkan` | Data dan gambar sudah divalidasi, browser belum mengisinya. |
| `diproses` | Pengisian sedang berjalan atau terhenti sebelum pengiriman. |
| `siap_kirim` | Isian lengkap, belum menekan Kirim. |
| `mengirim` | Status dicatat sebelum menekan Kirim, menunggu konfirmasi. |
| `terkirim` | Google Forms sudah menampilkan konfirmasi, atau Anda telah mengonfirmasi secara manual. |
| `gagal` | Gagal sebelum pengiriman; pesan error tersimpan. |
| `perlu_cek` | Pengiriman mungkin berhasil, tetapi konfirmasi tidak didapatkan. |

Jalankan ulang perintah batch yang sama untuk melanjutkan. Foto `terkirim` dilewati. Foto yang belum dikirim atau gagal sebelum pengiriman boleh dicoba kembali. File progres diperbarui setiap kali status berubah; jangan menghapusnya jika ingin mempertahankan riwayat dan menghindari pengiriman ulang.

Alur pemilih gambar/Jelajah dan unggah mendapat **maksimal 3 percobaan total per foto per proses**. Bot menunggu penyelesaian unggahan dan pemasangan lampiran hingga 120 detik per percobaan, sambil memeriksa statusnya, bukan sekadar menunggu nama file selama 25 detik.

Pada tampilan Google Picker tertentu, file selesai diunggah ke Drive tetapi belum masuk ke formulir. Bot kini memilih file unggahan tersebut di tab **Terbaru**, lalu menekan **Sisipkan 1 item**. File dipilih berdasarkan ID hasil unggahan, nama, dan ukuran yang sesuai; salinan lama dengan nama sama tidak dipilih. Jika file sudah berhasil diunggah, retry hanya mengulang pemilihan/penyisipannya, tanpa mengunggah salinan baru.

Pencocokan ID memakai atribut `data-id` kartu file, bukan informasi thumbnail. File baru tetap dapat dipilih walaupun thumbnail belum dimuat atau belum tersedia.

Keberhasilan baru diakui setelah nama file dan tombol **Buka file** muncul pada lampiran formulir. Bila ketiga percobaan tetap gagal, foto ditandai `gagal` dan batch melanjutkan foto berikutnya. Pesan error menyebutkan tahap yang bermasalah.

Jika konfirmasi **Kirim** tidak terlihat, foto ditandai `perlu_cek` dan batch melanjutkan foto berikutnya. Saat batch dijalankan ulang, bot melewati foto itu sampai pengguna mencatat hasil pemeriksaan manual. Ini juga berlaku jika formulir memakai pesan konfirmasi khusus yang berbeda dari pesan standar Indonesia/Inggris.

Setelah memeriksa bukti pengiriman, catat hasilnya untuk nomor terkait:

```powershell
# Jika sudah terkirim (termasuk pengiriman manual lewat browser):
python isi_form_ulasan.py --part 1 --nomor "18" --konfirmasi terkirim

# Jika sudah dipastikan belum terkirim, izinkan percobaan berikutnya:
python isi_form_ulasan.py --part 1 --nomor "18" --konfirmasi belum_terkirim
```

Perintah konfirmasi hanya memperbarui catatan, tanpa membuka atau mengirim formulir. Status yang sudah `terkirim` tidak dapat direset melalui `--konfirmasi belum_terkirim`. Riwayat dari pengisian sebelum fitur progres dibuat tidak ditebak oleh bot; konfirmasikan manual jika sebelumnya sudah dikirim.

## Pemeriksaan lokal

```powershell
python -m unittest -q test_isi_form_ulasan.py
```

Pengujian menggunakan browser simulasi untuk alur batch, retry, pemulihan progres, dan pencegahan kirim ulang. Pengujian tidak mengirim respons Google Forms sungguhan.

Sumber HTML dibaca dari folder proyek atau `Gambar Ulasan PLN Mobile`. Gambar dicari di `Gambar Ulasan PLN Mobile/Part N`, lalu `Hasil Ekspor/Part N` (lokasi lama, hanya sebagai cadangan) jika tidak ditemukan di lokasi pertama. Status Part 3 memakai ID `part-3/NN`, terpisah dari riwayat part lainnya.

## Struktur folder yang digunakan semua skrip

Simpan satu HTML sumber per part di folder `HTML` dengan nama berakhiran `Part N.html`, dengan `N` berupa nomor positif, misalnya `Rekap Reviews PLN Mobile - 100 Ulasan Part 5.html`. BAT dan exporter mendeteksi part yang tersedia saat dijalankan. Jumlah ulasan mengikuti kartu di dalam HTML. Format kelas HTML lama (`review-card`, `name`, `stars`, `date`, `review-text`) dan format ringkas (`rc`, `nm`, `st`, `dt`, `tx`) didukung.

```text
FormAutomation/
  MULAI_AUTOMASI.bat
  requirements.txt
  project_paths.py
  Gambar Ulasan PLN Mobile/
    HTML/        # HTML sumber untuk semua part
    Part 1/      # PNG Part 1
    Part 2/      # PNG Part 2
    Part 3/      # PNG Part 3
  Hasil Ekspor/  # ZIP hasil ekspor
```

Lokasi folder dihitung dari lokasi skrip, bukan folder terminal saat ini. Jangan mengganti nama PNG secara manual karena nomor dan username harus cocok dengan HTML. Folder foto memakai spasi: `Part 1`, bukan `Part1`.

Instalasi dan dependensi lengkap tersedia di `requirements.txt`. Untuk instalasi pertama:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m playwright install chromium
npm install -g agent-browser
agent-browser install
.\MULAI_AUTOMASI.bat
```

BAT otomatis memakai Python di `.venv` bila ada. Chrome biasa tetap diperlukan untuk login Google dan Remote Debugging. Browser Playwright hanya dipakai untuk ekspor gambar, terpisah dari login Google.

Jika PNG belum tersedia setelah clone dari GitHub, menu BAT menawarkan pembuatan gambar dari seluruh HTML. Bisa juga menjalankan exporter langsung:

```powershell
.\.venv\Scripts\python.exe export_reviews.py
.\.venv\Scripts\python.exe export_reviews.py "Gambar Ulasan PLN Mobile/HTML/Rekap Google Reviews PLN Mobile - 48 Ulasan Part 3.html"
```

Tanpa `--output`, PNG otomatis disimpan ke folder `Part N` yang dibaca bot; ZIP berada di `Hasil Ekspor`. `--output` tersedia untuk ekspor ke folder lain, tetapi folder khusus itu bukan lokasi foto otomatis bot.

Riwayat progres tetap di folder utama dan dikecualikan dari Git. Hash riwayat lama dimigrasikan saat data dipersiapkan, hanya apabila isi ulasan serta byte PNG tetap sama; status terkirim tidak direset karena pemindahan folder.
