# 🧼 Cleaning Schedule Produksi

Aplikasi web untuk mengelola jadwal pembersihan mesin & area produksi.

## Fitur
- **Dashboard** — ringkasan jadwal hari ini, statistik penyelesaian 7 hari, keterlambatan, aktivitas terakhir
- **Jadwal** — CRUD jadwal cleaning, filter tanggal/mesin/status, ubah status (▶ mulai / ✅ selesai)
- **Generate Otomatis** — buat jadwal berulang dari frekuensi harian setiap mesin aktif
- **Kalender** — tampilan bulanan dengan warna status
- **Mesin & Area** — kelola aset, frekuensi, standar waktu, aktif/nonaktif
- **Laporan** — rekap penyelesaian per mesin, ekspor CSV

## Cara Menjalankan
```bash
pip install -r requirements.txt
python app.py
```
Buka http://localhost:5000

## Catatan
- Database SQLite (`cleaning_schedule.db`) dibuat otomatis + diisi data contoh saat pertama dijalankan.
- Status jadwal otomatis menjadi **Terlambat** jika waktunya lewat dan belum selesai.