"""
Anatomi 3: Halaman Katalog Publikasi BPS
Memeriksa nomor katalog, nomor publikasi, ISSN, nomor halaman romawi dan arab,
ukuran buku (A4/B5), frekuensi terbit, dan format blok katalog sesuai Pedoman 2023 Bab 4.3.2.
"""
from .common import validate_issn_checksum

def evaluate_katalog(meta, kabupaten_str, kab_upper, kab_raw, level_id, level_en, level_en_upper):
    region = meta["region"]
    year = meta["year"]
    catalog_no = meta["catalog"]
    issn = meta["issn"]
    cat_roman = meta["catalog_roman"]
    cat_arab = meta["catalog_arab"]
    region_up = region.upper()
    
    halaman_katalog = []
    if meta.get("catalog_idx", -1) < 0:
        halaman_katalog.append(
            'Halaman Katalog tidak ditemukan dalam publikasi. '
            'Sesuai Pedoman Pembuatan Publikasi BPS 2023 Bab 4.3.2 (hal. 37) dan Instrumen baris 23, '
            'Halaman Katalog WAJIB berada tepat di balik Halaman Judul Utama pada halaman GENAP (verso / halaman kiri, umumnya halaman fisik 4).'
        )
    else:
        if meta.get("catalog_is_odd"):
            halaman_katalog.append(
                f'Kesalahan penempatan halaman (Katalog pada Halaman Ganjil): Halaman Katalog terletak pada halaman fisik {meta["catalog_is_odd"]} (GANJIL). '
                f'Berdasarkan Pedoman Pembuatan Publikasi BPS 2023 Bab 4.3.2 (hal. 37) dan Instrumen baris 23, '
                f'Halaman Katalog WAJIB berada tepat di balik Halaman Judul Utama pada halaman GENAP (verso / halaman kiri, umumnya halaman fisik 4).'
            )
        if meta.get("catalog_issn_colon_error"):
            halaman_katalog.append(
                'Penulisan ISSN yang benar pada Halaman Katalog adalah dengan menggunakan tanda titik dua setelah kata ISSN dan tanpa spasi ("ISSN:") '
                'sesuai Pedoman Pembuatan Publikasi BPS 2023 halaman 79.'
            )
        for r_lbl, v_r in meta.get("catalog_individual_roles", []):
            halaman_katalog.append(
                f'Pencantuman nama individu pada Halaman Katalog: Baris "{r_lbl}" tertulis "{v_r}". '
                f'Sesuai Pedoman Pembuatan Publikasi BPS 2023 Bab 4 hal. 78 & Instrumen Baris 29–31, komponen Penyusun Naskah, Penyunting, dan Pembuat Kover '
                f'WAJIB diisi nama unit kerja/institusi (contoh: "Badan Pusat Statistik {kabupaten_str}"), TIDAK DIPERKENANKAN mencantumkan nama-nama individu. '
                f'Nama individu hanya dicantumkan pada Halaman Tim Penyusun.'
            )
        if meta.get("catalog_volume_empty"):
            vol_txt = meta.get("catalog_volume_text") or "Volume xx"
            halaman_katalog.append(
                f'Volume publikasi pada Halaman Katalog masih kosong / berupa template: Tertulis "{vol_txt}". '
                'Wajib diisi dengan angka volume publikasi yang benar.'
            )
        if meta.get("catalog_no_empty"):
            halaman_katalog.append(
                'Nomor Katalog pada Halaman Katalog masih kosong atau berupa titik-titik ("..."). '
                'Wajib diisi dengan nomor katalog resmi BPS.'
            )
        if meta.get("catalog_issn_empty"):
            halaman_katalog.append(
                'Nomor ISSN pada Halaman Katalog belum dicantumkan atau masih berupa tanda titik-titik ("...") / placeholder. '
                'Wajib dicantumkan nomor ISSN resmi publikasi.'
            )
        elif not meta.get("catalog_has_issn_line", True) and (meta.get("is_serial") or (issn and issn != "-") or meta.get("catalog", "").startswith("1102001")):
            halaman_katalog.append(
                'Baris nomor ISSN tidak dicantumkan pada Halaman Katalog: '
                'Sesuai Pedoman Pembuatan Publikasi BPS 2023 Bab 4.3.2 (hal. 37), Template KCDA 2026, dan Instrumen baris 26, '
                'publikasi berkala (Kecamatan Dalam Angka) wajib mencantumkan baris "ISSN: [Nomor ISSN]" di bawah baris nomor katalog dan di atas baris nomor publikasi.'
            )
        if meta.get("catalog_pages_placeholder"):
            halaman_katalog.append(
                'Jumlah halaman pada baris "Jumlah Halaman/Number of Pages" masih berupa draf titik-titik ("...+... halaman/pages"). '
                'Wajib diisi dengan jumlah halaman Romawi dan Arab riil dokumen.'
            )
        if meta.get("catalog_illus_source_empty"):
            halaman_katalog.append(
                'Baris "Sumber Ilustrasi/Illustration Source" masih kosong atau hanya berisi titik-titik ("..."). '
                f'Wajib dicantumkan sumber ilustrasi/kover yang valid (misalnya "BPS {kabupaten_str}" atau nama kontributor foto).'
            )
        if meta.get("catalog_agency_dual_option"):
            halaman_katalog.append(
                'Pencantuman nama instansi BPS pada Halaman Katalog masih memuat pilihan ganda template "Kabupaten/Kota" atau "Regency/Municipality". '
                'Wajib disesuaikan dengan status wilayah kabupaten yang bersangkutan.'
            )
        if (meta.get("is_serial") or meta.get("cover_is_bilingual") or meta.get("catalog", "").startswith("1102001")):
            missing_bilingual = meta.get("catalog_bilingual_missing", [])
            if len(missing_bilingual) >= 3:
                missing_str = "; ".join(missing_bilingual)
                halaman_katalog.append(
                    f'Halaman Katalog belum disajikan dalam format dwibahasa (bilingual): '
                    f'Publikasi Kecamatan Dalam Angka merupakan publikasi dwibahasa yang wajib menyajikan judul dan seluruh label metadata katalog dalam dua bahasa (Indonesia/Inggris) '
                    f'sesuai Pedoman Pembuatan Publikasi BPS 2023 Bab 4.3.2 (hal. 37), Template KCDA 2026, dan Instrumen Pemeriksaan baris 24–33. '
                    f'Komponen yang belum memuat padanan bahasa Inggris meliputi: {missing_str}.'
                )
            elif len(missing_bilingual) > 0:
                for item_mis in missing_bilingual:
                    halaman_katalog.append(
                        f'Label/komponen "{item_mis}" pada Halaman Katalog belum dwibahasa: '
                        f'Sesuai kaidah publikasi dwibahasa BPS (Pedoman 2023 hal. 37 & Instrumen baris 24–33), '
                        f'komponen tersebut wajib memuat padanan bahasa Inggris resmi.'
                    )
        if meta.get("catalog_slash"):
            halaman_katalog.append(
                f'Kesalahan tanda baca pada baris Katalog: Tertulis "Katalog /Catalogue: {catalog_no}" '
                f'(terdapat spasi sebelum garis miring "/"). Penulisan baku ditulis rapat tanpa spasi sebelum dan sesudah garis miring ("Katalog/Catalogue: {catalog_no}").'
            )
        if meta.get("space_before_slash_label_pages"):
            halaman_katalog.append(
                'Kesalahan tanda baca pada label Jumlah Halaman: Terdapat spasi sebelum garis miring pada label "Jumlah Halaman /Number of Pages". '
                'Penulisan baku ditulis rapat tanpa spasi sebelum garis miring ("Jumlah Halaman/Number of Pages").'
            )
        if meta.get("space_before_slash_unit_pages"):
            halaman_katalog.append(
                'Kesalahan tanda baca pada baris Jumlah Halaman: Terdapat spasi sebelum tanda garis miring pada teks satuan "halaman /pages". '
                'Sesuai kaidah dwibahasa BPS, penulisan satuan baku ditulis rapat tanpa spasi sebelum dan sesudah garis miring ("halaman/pages").'
            )
        # Pengecekan spasi sebelum titik dua pada Jumlah Halaman ditiadakan karena kerning font miring (italic)
        if not meta.get("catalog_issn_format_ok", True):
            halaman_katalog.append(
                f'Penulisan label ISSN salah: tertulis tanpa titik dua atau "ISSN/ISSN: {issn}". '
                f'Sesuai pedoman baku, penulisan yang benar pada halaman katalog adalah "ISSN: {issn}" (wajib menggunakan titik dua).'
            )
        if meta.get("pub_num_empty"):
            halaman_katalog.append(
                'Nomor Publikasi belum diisi: Baris "Nomor Publikasi/Publication Number" masih berisi tanda strip ("-") atau kosong. '
                'Wajib mencantumkan nomor publikasi resmi BPS (contoh format: 72010.260xx).'
            )
        if meta.get("pub_num_wrong_year"):
            code_yr, exp_yr = meta["pub_num_wrong_year"]
            halaman_katalog.append(
                f'Nomor publikasi salah kode tahun: tertulis kode tahun "{code_yr}". '
                f'Untuk publikasi tahun {year}, kode tahun yang benar adalah "{exp_yr}".'
            )
        if meta.get("uses_hal_not_hlm"):
            halaman_katalog.append(
                'Kesalahan singkatan kata halaman pada baris Jumlah Halaman: Kata "halaman" disingkat menjadi "hal" atau "hlm". '
                'Sesuai standar Pedoman Pembuatan Publikasi BPS, wajib ditulis lengkap tanpa disingkat: "halaman/pages".'
            )
        if meta.get("catalog_pages_mismatch"):
            cat_ar, act_ar = meta["catalog_pages_mismatch"]
            halaman_katalog.append(
                f'Ketidaksinkronan jumlah halaman batang tubuh pada Halaman Katalog: Tertulis "{cat_ar}" halaman, '
                f'padahal halaman bernomor Arab terakhir pada buku adalah halaman {act_ar}. '
                f'Jumlah halaman Arab pada "Jumlah Halaman/Number of Pages" wajib diselaraskan.'
            )
        if meta.get("bps_abbreviated_id"):
            halaman_katalog.append(
                'Pelanggaran penulisan nama lembaga pada hak cipta: Tertulis "©BPS ..." atau "© BPS ...". '
                'Sesuai aturan BPS, dalam bahasa Indonesia nama lembaga dilarang disingkat. Penulisan baku adalah "©Badan Pusat Statistik".'
            )
        if meta.get("catalog_bps_abbreviations"):
            contoh_teks = meta["catalog_bps_abbreviations"][0]
            halaman_katalog.append(
                f'Penulisan nama instansi BPS pada Halaman Katalog disingkat: Tertulis "{contoh_teks}". '
                f'Sesuai kaidah Halaman Katalog BPS (Pedoman 2023 Bab 4.3.2 hal. 37 & Instrumen baris 32), '
                f'nama instansi BPS pada baris penyusun, penyunting, dan penerbit wajib ditulis lengkap "Badan Pusat Statistik", tidak boleh disingkat.'
            )
        if meta.get("bps_of_en"):
            halaman_katalog.append(
                'Penulisan nama Satker BPS dalam bahasa Inggris tidak standar: menggunakan kata "of" ("BPS-Statistics of [Regency]"). '
                'Standar baku penulisan BPS daerah menurut Pedoman 2023 hal. 65 adalah "BPS-Statistics [Regency]" (tanpa kata "of").'
            )
        if meta.get("copyright_typo_regency"):
            halaman_katalog.append(
                'Saltik pada klausul Hak Cipta bahasa Inggris: tertulis "Regenency" (kelebihan huruf "en", penulisan yang benar adalah "Regency").'
            )
        for err in meta.get("catalog_label_errors", []):
            halaman_katalog.append(f'Kesalahan tanda baca pada baris katalog: {err}')
        if meta.get("space_around_plus_pages"):
            halaman_katalog.append(
                'Kesalahan tanda baca pada baris Jumlah Halaman: Terdapat spasi di sekitar tanda tambah ("+"). '
                'Sesuai Pedoman Publikasi BPS 2023 & Instrumen baris 28 poin 6, penulisan format halaman ditulis rapat tanpa spasi sebelum dan sesudah tanda "+" (contoh: xii+90 halaman/pages).'
            )
        if meta.get("book_size_format_error"):
            halaman_katalog.append(
                f'Kesalahan format penulisan pada baris Ukuran Buku: {meta["book_size_format_error"]}'
            )
        if meta.get("copyright_space_after_symbol"):
            halaman_katalog.append(
                'Kesalahan spasi pada klausul Hak Cipta / Penerbit: Terdapat spasi setelah simbol hak cipta "©". '
                'Sesuai Pedoman Pembuatan Publikasi BPS 2023 & Instrumen baris 32 poin 4, setelah simbol hak cipta tidak perlu ada spasi ("©Badan Pusat Statistik...").'
            )
        if meta.get("catalog_roman_is_odd"):
            r_str, r_int = meta["catalog_roman_is_odd"]
            halaman_katalog.append(
                f'Jumlah halaman Romawi pada baris Jumlah Halaman bernilai ganjil: Tertulis "{r_str}" ({r_int} halaman). '
                f'Sesuai Pedoman Pembuatan Publikasi BPS 2023 Bab 4.3.2 hal. 37 & Instrumen baris 28 poin 4, '
                f'jumlah halaman Romawi HARUS GENAP. Tambahkan satu halaman kosong tanpa nomor halaman dan running title '
                f'jika bagian pendahuluan berakhir di halaman ganjil agar halaman batang tubuh 1 tetap dimulai pada halaman ganjil.'
            )
        if meta.get("catalog_pub_no_abbreviated"):
            halaman_katalog.append(
                'Penulisan "Nomor Publikasi" disingkat pada Halaman Katalog: Tertulis "No. Publikasi" atau "No Publikasi". '
                'Sesuai Pedoman Pembuatan Publikasi BPS 2023 Bab 4.3.2 & Instrumen baris 26 poin 5, penulisan "Nomor Publikasi" '
                'TIDAK BOLEH DISINGKAT (wajib ditulis lengkap "Nomor Publikasi" atau "Nomor Publikasi/Publication Number").'
            )
        if meta.get("catalog_numbering_order_wrong"):
            halaman_katalog.append(
                'Urutan penomoran publikasi pada Halaman Katalog tidak baku: '
                'Sesuai Pedoman Pembuatan Publikasi BPS 2023 Bab 4.3.2 & Instrumen baris 26 poin 2, urutan penulisan penomoran '
                'publikasi yang baku adalah Katalog terlebih dahulu, diikuti ISSN/ISBN, kemudian Nomor Publikasi.'
            )

    return halaman_katalog
