"""
Anatomi 7: Penjelasan Umum Publikasi BPS
Memeriksa penempatan lembar penjelasan umum pada halaman ganjil (recto)
dan pencetakan miring istilah statistik bahasa asing (Pedoman 2023 Bab 4.3.10 & Hal. 87).
"""
def evaluate_penjelasan_umum(meta):
    region = meta.get("region", "Wilayah")
    year = meta.get("year", 2026)
    
    penjelasan_umum = []
    if meta.get("penjelasan_is_even"):
        penjelasan_umum.append(
            f'Kesalahan penempatan halaman (Penjelasan Umum pada Halaman Genap): Lembar Penjelasan Umum dimulai pada halaman fisik {meta["penjelasan_is_even"]} (GENAP). '
            f'Berdasarkan Pedoman Pembuatan Publikasi BPS 2023 Bab 4.3.10 (hal. 45) dan Instrumen baris 90, '
            f'lembar Penjelasan Umum WAJIB dimulai pada halaman GANJIL (recto / halaman kanan).'
        )
    if meta.get("penjelasan_english_not_italic"):
        penjelasan_umum.append(
            'Cetak miring istilah bahasa asing pada Penjelasan Umum: Sesuai Pedoman Pembuatan Publikasi BPS 2023 Hal. 87 & Instrumen baris 91–94, '
            'padanan istilah statistik bahasa Inggris (contoh: Not applicable, Data not available, dll.) '
            'terdeteksi belum dicetak miring (italic). Sesuai kaidah dwibahasa BPS, istilah bahasa asing WAJIB dicetak miring.'
        )


    return penjelasan_umum
