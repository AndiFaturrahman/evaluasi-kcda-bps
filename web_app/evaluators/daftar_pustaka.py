"""
Anatomi 10: Daftar Pustaka Publikasi BPS
Memeriksa keberadaan daftar pustaka pada publikasi hasil kajian statistik,
penempatan halaman ganjil, dan pembersihan residu template master sesuai Pedoman 2023 Bab 4.5.
"""
def evaluate_daftar_pustaka(meta):
    region = meta.get("region", "Wilayah")
    year = meta.get("year", 2026)
    
    daftar_pustaka = []
    if meta.get("biblio_is_even"):
        daftar_pustaka.append(
            f'Kesalahan penempatan halaman (Daftar Pustaka pada Halaman Genap): Lembar Daftar Pustaka dimulai pada halaman fisik {meta["biblio_is_even"]} (GENAP). '
            f'Berdasarkan Pedoman Pembuatan Publikasi BPS 2023 Bab 4.5 & Instrumen baris 182, '
            f'lembar Daftar Pustaka WAJIB dimulai pada halaman GANJIL (recto / halaman kanan).'
        )
    if not meta.get("has_daftar_pustaka"):
        daftar_pustaka.append(
            'Daftar Pustaka SAMA SEKALI TIDAK ADA di dalam buku (dokumen langsung berakhir tanpa lembar daftar pustaka). '
            'Pada publikasi hasil kegiatan dan kajian statistik BPS, Daftar Pustaka bersifat WAJIB dicantumkan (Instrumen baris 181).'
        )
    if meta.get("biblio_has_template_dots"):
        daftar_pustaka.append(
            'Daftar Pustaka masih memuat teks sisa draft/placeholder template master (titik-titik "............................"). '
            'Seluruh entri daftar pustaka wajib diisi referensi resmi publikasi riil atau dibersihkan dari titik-titik template.'
        )


    return daftar_pustaka
