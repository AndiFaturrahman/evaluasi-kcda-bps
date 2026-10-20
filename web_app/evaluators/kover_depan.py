"""
Anatomi 1: Kover Depan Publikasi BPS
Memeriksa penulisan judul, nomor katalog, nomor ISSN, volume, dwibahasa, font Arial Bold Italic,
dan tata letak pojok kanan atas sesuai Pedoman Pembuatan Publikasi BPS 2023 hal. 35.
"""
from .common import validate_issn_checksum

def evaluate_kover_depan(meta, kabupaten_str, kab_upper, kab_raw, level_id, level_en, level_en_upper):
    region = meta["region"]
    year = meta["year"]
    catalog_no = meta.get("catalog", "-")
    issn = meta.get("issn", "-")
    team_issn = meta.get("team_issn", "-")
    cat_roman = meta.get("catalog_roman", "-")
    cat_arab = meta.get("catalog_arab", "-")
    preface_year = meta.get("preface_year", year)
    region_up = region.upper()
    
    kover_depan = []
    # ATURAN BAKU: ABAIKAN YANG TAK KASAT MATA!
    # Jika di balik gambar kover terdapat lapisan teks vektor sisa template yang tertutup gambar,
    # teks tersebut tidak kasat mata bagi pembaca dan diabaikan dari daftar catatan defect.

    if meta.get("cover_logo_monochrome"):
        kover_depan.append(
            'Kesalahan warna logo BPS pada kover depan: Logo BPS ditampilkan monokrom/hitam-putih. '
            'Sesuai Pedoman Pembuatan Publikasi BPS 2023 hal. 35, Pedoman Identitas Visual BPS, dan Instrumen baris 21, '
            'logo BPS dan identitas penerbit wajib menggunakan aset resmi berwarna (Biru BPS #023F88, Hijau BPS #74B72E, dan Oranye BPS #FFA200).'
        )
    if meta.get("cover_logo_defects"):
        for ld in meta["cover_logo_defects"]:
            if "monokrom" in ld.lower() and meta.get("cover_logo_monochrome"):
                continue
            if ld not in kover_depan:
                kover_depan.append(ld)

    if meta.get("cover_issn_placeholder"):
        kover_depan.append(
            'Nomor ISSN pada kover depan belum dicantumkan atau masih berupa placeholder template ("ISSN XXXX -XXXX"). '
            'Publikasi berkala resmi wajib mencantumkan nomor ISSN valid tanpa tanda titik dua di pojok kanan atas kover depan di atas nomor katalog (Pedoman hal. 35 & Instrumen baris 13).'
        )
        if meta.get("cover_catalog_placeholder"):
            kover_depan.append(
                'Nomor Katalog pada kover depan masih berupa draf/template ("1102001.xxxx"). '
                'Wajib diganti dengan nomor katalog resmi publikasi bersangkutan.'
            )
        if meta.get("cover_volume_placeholder"):
            kover_depan.append(
                'Volume terbitan pada kover depan belum diisi (masih berupa template "Volume XX"). '
                'Wajib diisi dengan angka volume terbitan riil sesuai tahun publikasi.'
            )
        if meta.get("cover_agency_dual_option"):
            kover_depan.append(
                'Penulisan nama wilayah/instansi pada kover depan masih memuat opsi ganda template ("KABUPATEN/KOTA" / "REGENCY/MUNICIPALITY"). '
                f'Wajib dipilih salah satu sesuai status wilayah administratif (misalnya "{kab_upper}" / "{kab_raw} REGENCY").'
            )
    if meta.get("cover_catalog_space_colon"):
        kover_depan.append(
            f'Kesalahan spasi pada nomor katalog: Tertulis "Katalog/Catalogue : {catalog_no}" '
            f'(terdapat spasi sebelum tanda titik dua). Koreksi seharusnya: "Katalog/Catalogue: {catalog_no}".'
        )
    is_serial_pub = meta.get("is_serial", False) or (issn and issn != "-") or meta.get("catalog", "").startswith("1102001")
    if meta.get("cover_has_colon"):
        target_disp_issn = meta.get("issn_correct_from_registry")
        if not target_disp_issn:
            if issn and issn != "-" and validate_issn_checksum(issn)[0]:
                target_disp_issn = issn
            else:
                target_disp_issn = "[Nomor ISSN]"
        
        cov_txt = meta.get("cover_issn_text")
        if cov_txt:
            label_found = f'Tertulis "{cov_txt}"'
        else:
            label_found = 'Tertulis dengan tanda titik dua ("ISSN :")'

        kover_depan.append(
            f'Kesalahan format penulisan nomor ISSN pada kover depan: {label_found} (menggunakan tanda titik dua setelah kata ISSN). '
            f'Sesuai Pedoman Pembuatan Publikasi BPS 2023 hal. 35 & Instrumen baris 13, publikasi berkala yang memiliki ISSN wajib '
            f'mencantumkan tulisan "ISSN {target_disp_issn}" TANPA tanda titik dua di pojok kanan atas kover depan.'
        )
    elif is_serial_pub and not meta.get("cover_has_issn"):
        target_disp_issn = meta.get("issn_correct_from_registry") or (issn if (issn != "-" and validate_issn_checksum(issn)[0]) else "[Nomor ISSN]")
        if target_disp_issn != "[Nomor ISSN]":
            target_str = f"resmi ({target_disp_issn})"
            sample_issn = f"ISSN {target_disp_issn}"
        else:
            target_str = "(seperti publikasi berkala Kecamatan Dalam Angka)"
            sample_issn = "ISSN [Nomor ISSN]"
        kover_depan.append(
            f'Nomor ISSN tidak dicantumkan pada kover depan: Publikasi berkala yang memiliki ISSN {target_str} '
            f'wajib mencantumkan tulisan "{sample_issn}" tanpa tanda titik dua di pojok kanan atas kover depan di bawah nomor katalog (Pedoman hal. 35 & Instrumen baris 13).'
        )
    if is_serial_pub and not meta.get("cover_has_english_title", True):
        kover_depan.append(
            f'Judul terjemahan bahasa Inggris belum dicantumkan pada kover depan: '
            f'Publikasi Kecamatan Dalam Angka merupakan publikasi dwibahasa yang wajib menyertakan terjemahan judul bahasa asing '
            f'("{region_up} {level_en_upper} IN FIGURES {year}") dengan cetak miring (italic) di bawah judul bahasa Indonesia '
            f'(Pedoman Pembuatan Publikasi BPS 2023 hal. 58, Template KCDA 2026, dan Instrumen baris 8).'
        )
    elif meta.get("cover_has_english_title") and not meta.get("cover_title_is_italic", True):
        kover_depan.append(
            f'Kesalahan tipografi judul bahasa Inggris: Terjemahan judul "{region_up} {level_en_upper} IN FIGURES {year}" '
            f'pada kover depan belum dicetak miring (masih reguler/tegak). Sesuai kaidah publikasi dwibahasa BPS '
            f'(Pedoman 2023 hal. 58 & Instrumen baris 8), terjemahan judul bahasa asing wajib dicetak miring (italic).'
        )
    if meta.get("cover_publisher_not_bilingual"):
        kover_depan.append(
            'Nama satker BPS pada kover depan seharusnya mencantumkan versi bahasa Inggris ("BPS-Statistics ... Regency/Municipality") '
            'karena publikasinya dua bahasa (Pedoman Pembuatan Publikasi BPS 2023 halaman 64).'
        )
    if meta.get("cover_publisher_not_arial_bi"):
        kover_depan.append(
            'Nama BPS Penerbit pada kover depan belum menggunakan jenis huruf Arial Bold Italic sesuai Pedoman Pembuatan Publikasi BPS 2023 halaman 64.'
        )
    if meta.get("cover_catalog_pos_wrong") == "kiri":
        kover_depan.append(
            'Kesalahan tata letak nomor katalog dan ISSN pada kover depan: Klaster nomor katalog/ISSN diletakkan di sebelah kiri atas. '
            'Sesuai Pedoman Pembuatan Publikasi BPS 2023 (hal. 35) dan Instrumen Pemeriksaan baris 13, klaster nomor katalog dan ISSN '
            'WAJIB diposisikan di pojok kanan atas kover depan dengan perataan rata kanan (right-aligned).'
        )
    if meta.get("cover_katalog_issn_order_wrong"):
        kover_depan.append(
            'Urutan posisi Nomor Katalog dan ISSN pada kover depan terbalik: Nomor ISSN terpasang di atas Nomor Katalog. '
            'Sesuai Pedoman Pembuatan Publikasi BPS 2023 hal. 35 & Instrumen baris 5–6, Nomor Katalog WAJIB diposisikan '
            'di ATAS nomor ISSN pada pojok kanan atas kover depan.'
        )
    if meta.get("cover_title_has_tahun_word"):
        kover_depan.append(
            f'Judul buku pada kover depan memuat kata "Tahun" sebelum angka tahun terbit/data. '
            f'Sesuai Pedoman Pembuatan Publikasi BPS 2023 Bab 4.2 hal. 35 & Instrumen baris 8 poin 7, penulisan judul buku '
            f'tidak perlu mencantumkan kata "Tahun", melainkan langsung mencantumkan angka tahun data '
            f'(contoh baku: "{level_id} {region} Dalam Angka {year}").'
        )
    if meta.get("p2_has_leak"):
        kover_depan.append(
            'Running title atau nomor halaman tercetak pada halaman kosong setelah kover depan (halaman fisik 2). '
            'Sesuai Pedoman Pembuatan Publikasi BPS 2023 Bab 4.2 hal. 35 & Instrumen baris 16, lembar setelah kover depan '
            'merupakan halaman kosong penyelarasan tanpa running title dan tanpa nomor halaman (tidak dihitung sebagai halaman).'
        )

    return kover_depan
