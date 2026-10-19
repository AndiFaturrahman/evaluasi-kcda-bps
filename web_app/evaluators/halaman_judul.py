"""
Anatomi 2: Halaman Judul Utama (HJU) Publikasi BPS
Memeriksa keselarasan judul terhadap kover depan, penempatan pada halaman ganjil (recto),
nomor halaman blind folio (tanpa nomor tercetak), dan logo BPS sesuai Pedoman 2023 Bab 4.3.1.
"""
from .common import validate_issn_checksum

def evaluate_halaman_judul(meta, kabupaten_str, kab_upper, kab_raw, level_id, level_en, level_en_upper):
    region = meta["region"]
    year = meta["year"]
    catalog_no = meta.get("catalog", "-")
    issn = meta.get("issn", "-")
    team_issn = meta.get("team_issn", "-")
    cat_roman = meta.get("catalog_roman", "-")
    cat_arab = meta.get("catalog_arab", "-")
    preface_year = meta.get("preface_year", year)
    region_up = region.upper()
    
    halaman_judul = []
    if meta.get("total_pages", 0) <= 2 or meta.get("hju_idx", -1) < 0:
        halaman_judul.append(
            'Halaman Judul Utama tidak ditemukan dalam publikasi. '
            'Berdasarkan Pedoman Pembuatan Publikasi BPS 2023 Bab 4.3.1 (hal. 36) dan Instrumen baris 15, '
            'Halaman Judul Utama WAJIB diletakkan pada halaman GANJIL (recto / halaman kanan, umumnya halaman fisik 3).'
        )
    else:
        if meta.get("p3_is_template") and not (meta.get("p3_has_bg_illustration") or meta.get("p3_has_image")):
            halaman_judul.append(
                f'Halaman Judul Utama masih berupa format template master yang belum disesuaikan: '
                f'Terdeteksi placeholder nomor katalog ("1102001.xxxx"), nomor ISSN ("ISSN XXXX -XXXX"), volume ("Volume XX"), atau pilihan ganda ("KABUPATEN/KOTA"). '
                f'Seluruh identitas buku wajib disesuaikan dengan data resmi {level_id} {region}.'
            )
        if meta.get("p3_typo_kecamatan"):
            halaman_judul.append(
                f'Saltik spasi pada penulisan kata "{level_id.upper()}" di Halaman Judul Utama: Tertulis "{level_id.upper()[:-1]} {level_id.upper()[-1]}" '
                f'(terdapat spasi sebelum huruf terakhir). Perbaiki menjadi "{level_id.upper()}".'
            )
        if meta.get("p3_has_bg_illustration", False):
            halaman_judul.append(
                'Pelanggaran format latar belakang Halaman Judul Utama: Memuat gambar/foto latar belakang ilustrasi / pemandangan alam (duplikasi visual kover depan). '
                'Berdasarkan Pedoman Pembuatan Publikasi BPS 2023 Bab 4.3.1 (hal. 36), Template KCDA 2026 halaman 3, '
                'dan Instrumen Pemeriksaan Publikasi baris 17, Halaman Judul Utama (halaman fisik 3 / Romawi i) WAJIB berlatar putih bersih tanpa ilustrasi.'
            )
        if meta.get("p3_logo_monochrome", False):
            halaman_judul.append(
                'Kesalahan warna logo BPS: Logo BPS dan identitas BPS Penerbit pada Halaman Judul Utama ditampilkan monokrom/grayscale. '
                'Sesuai Pedoman Pembuatan Publikasi BPS 2023 Bab 4.3.1 (hal. 36) & Instrumen Pemeriksaan baris 21, '
                'logo dan nama BPS penerbit pada Halaman Judul Utama wajib ditampilkan berwarna (biru dan hijau BPS).'
            )
        is_serial_pub = meta.get("is_serial", False) or (issn and issn != "-") or meta.get("catalog", "").startswith("1102001")
        if is_serial_pub:
            target_disp_hju = meta.get("issn_correct_from_registry")
            if not target_disp_hju:
                if issn and issn != "-" and validate_issn_checksum(issn)[0]:
                    target_disp_hju = issn
                else:
                    target_disp_hju = "[Nomor ISSN]"

            if meta.get("p3_issn_has_colon"):
                p3_txt = meta.get("p3_issn_text")
                label_p3 = f'tertulis "{p3_txt}"' if p3_txt else 'tertulis dengan tanda titik dua ("ISSN :")'
                halaman_judul.append(
                    f'Kesalahan format penulisan nomor ISSN pada Halaman Judul Utama: {label_p3} (menggunakan tanda titik dua setelah kata ISSN). '
                    f'Sesuai Pedoman 2023 Bab 4.3.1 hal. 36 & Instrumen baris 19, penulisan nomor ISSN pada Halaman Judul Utama wajib ditulis "ISSN {target_disp_hju}" tanpa tanda titik dua.'
                )
            elif not meta.get("p3_has_issn", False):
                if target_disp_hju != "[Nomor ISSN]":
                    target_str = f"resmi ({target_disp_hju})"
                    sample_issn = f"ISSN {target_disp_hju}"
                else:
                    target_str = "(seperti publikasi berkala Kecamatan Dalam Angka)"
                    sample_issn = "ISSN [Nomor ISSN]"
                halaman_judul.append(
                    f'Nomor ISSN tidak dicantumkan di pojok kanan atas Halaman Judul Utama: '
                    f'Publikasi berkala yang memiliki ISSN {target_str} wajib mencantumkan tulisan "{sample_issn}" '
                    f'di pojok kanan atas di bawah baris nomor katalog tanpa tanda titik dua (Pedoman 2023 hal. 35 & Instrumen baris 19).'
                )
        if meta.get("hju_catalog_space_colon"):
            halaman_judul.append(
                f'Kesalahan spasi pada nomor katalog Halaman Judul Utama: Tertulis "Katalog/Catalogue : {catalog_no}" '
                f'(terdapat spasi sebelum tanda titik dua). Seharusnya ditulis tanpa spasi "Katalog/Catalogue: {catalog_no}".'
            )
        if not meta.get("hju_title_is_italic", True):
            halaman_judul.append(
                f'Kesalahan tipografi judul bahasa Inggris pada Halaman Judul Utama: Terjemahan judul "{region_up} {level_en_upper} IN FIGURES {year}" '
                f'belum dicetak miring (masih reguler/tegak). Sesuai Pedoman Publikasi BPS 2023 Bab 4.3.1 (hal. 36) & Instrumen baris 18, '
                f'terjemahan judul bahasa asing wajib dicetak miring (italic).'
            )
        if meta.get("p3_has_rt"):
            halaman_judul.append(
                'Running title atau nomor halaman fisik tercetak pada Halaman Judul Utama. '
                'Sesuai Pedoman BPS 2023 hal. 49 & Instrumen baris 22, Halaman Judul Utama dilarang mencantumkan running title atau nomor halaman fisik.'
            )
        if meta.get("cover_publisher_not_bilingual"):
            halaman_judul.append(
                'Nama satker BPS pada Halaman Judul Utama seharusnya mencantumkan versi bahasa Inggris ("BPS-Statistics ... Regency/Municipality") '
                'karena publikasinya dua bahasa (Pedoman Pembuatan Publikasi BPS 2023 halaman 64).'
            )
        if meta.get("hju_is_even"):
            halaman_judul.append(
                f'Kesalahan penempatan halaman (HJU pada Halaman Genap): Halaman Judul Utama terletak pada halaman fisik {meta["hju_is_even"]} (GENAP). '
                f'Berdasarkan Pedoman Pembuatan Publikasi BPS 2023 Bab 4.3.1 (hal. 36) dan Instrumen baris 15, '
                f'Halaman Judul Utama WAJIB diletakkan pada halaman GANJIL (recto / halaman kanan, umumnya halaman fisik 3 setelah halaman kosong kover).'
            )
        if meta.get("hju_catalog_pos_wrong") == "kiri":
            halaman_judul.append(
                'Kesalahan tata letak nomor katalog dan ISSN pada Halaman Judul Utama: Klaster nomor katalog/ISSN diletakkan di sebelah kiri atas. '
                'Sesuai Pedoman Pembuatan Publikasi BPS 2023 Bab 4.3.1 (hal. 36) dan Instrumen baris 18, klaster nomor katalog dan ISSN '
                'WAJIB diletakkan di pojok kanan atas halaman dengan perataan rata kanan (right-aligned).'
            )


    return halaman_judul
