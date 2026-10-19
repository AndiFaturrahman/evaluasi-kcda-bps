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
    if meta.get("has_daftar_pustaka"):
        if not meta.get("biblio_has_rt", True):
            daftar_pustaka.append(
                'Running title tidak tercantum pada Halaman Daftar Pustaka. '
                'Sesuai Pedoman Pembuatan Publikasi BPS 2023 Bab 4.5 & Instrumen baris 189, '
                'halaman daftar pustaka wajib memuat running title (judul kepala).'
            )
        if not meta.get("biblio_has_arabic_page", True):
            daftar_pustaka.append(
                'Nomor halaman Arab tidak tercantum pada Halaman Daftar Pustaka. '
                'Sesuai Pedoman Pembuatan Publikasi BPS 2023 Bab 4.5 & Instrumen baris 189, '
                'halaman daftar pustaka wajib diberikan nomor halaman berangka Arab berkelanjutan dari batang tubuh.'
            )

    if meta.get("indeks_is_even"):
        daftar_pustaka.append(
            f'Kesalahan penempatan halaman (Indeks pada Halaman Genap): Bagian Indeks dimulai pada halaman fisik {meta["indeks_is_even"]} (GENAP). '
            f'Berdasarkan Pedoman Pembuatan Publikasi BPS 2023 Bab 4.6 & Instrumen baris 190, '
            f'lembar Indeks WAJIB dimulai pada halaman GANJIL (recto / halaman kanan).'
        )

    if meta.get("glosarium_is_even"):
        daftar_pustaka.append(
            f'Kesalahan penempatan halaman (Glosarium pada Halaman Genap): Bagian Daftar Istilah/Glosarium dimulai pada halaman fisik {meta["glosarium_is_even"]} (GENAP). '
            f'Berdasarkan Pedoman Pembuatan Publikasi BPS 2023 Bab 4.7 & Instrumen baris 194, '
            f'lembar Daftar Istilah/Glosarium WAJIB dimulai pada halaman GANJIL (recto / halaman kanan).'
        )

    if meta.get("lampiran_is_even"):
        daftar_pustaka.append(
            f'Kesalahan penempatan halaman (Lampiran pada Halaman Genap): Bagian Lampiran dimulai pada halaman fisik {meta["lampiran_is_even"]} (GENAP). '
            f'Berdasarkan Pedoman Pembuatan Publikasi BPS 2023 Bab 4.8 & Instrumen baris 198, '
            f'lembar Lampiran WAJIB dimulai pada halaman GANJIL (recto / halaman kanan).'
        )

    return daftar_pustaka

