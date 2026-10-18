"""
Anatomi 11: Kover Belakang Publikasi BPS
Memeriksa posisi barcode pojok kanan bawah, slogan Data Mencerdaskan Bangsa,
kluster logo BerAKHLAK dan #BanggaMelayaniBangsa, nama satker dwibahasa BPS-Statistics,
dan alamat resmi satker sesuai Pedoman Pembuatan Publikasi BPS 2023 hal. 64.
"""
def evaluate_kover_belakang(meta):
    region = meta.get("region", "Wilayah")
    year = meta.get("year", 2026)
    
    kover_belakang = list(meta.get("kover_belakang_errors", []))
    if meta.get("back_cover_barcode_pos_wrong") == "kiri":
        if not any("barcode pada kover belakang" in x.lower() for x in kover_belakang):
            kover_belakang.append(
                'Kesalahan tata letak barcode pada kover belakang: Barcode ISBN/ISSN/Nomor Publikasi diletakkan di sebelah kiri bawah. '
                'Sesuai Pedoman Pembuatan Publikasi BPS 2023 (hal. 64) dan Template Baku KCDA 2026, barcode WAJIB diletakkan di pojok kanan bawah kover belakang.'
            )


    return kover_belakang
