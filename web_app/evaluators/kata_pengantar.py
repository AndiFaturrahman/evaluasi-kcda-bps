"""
Anatomi 5: Halaman Kata Pengantar Publikasi BPS
Memeriksa nama satker, gelar pimpinan, keselarasan nama pejabat dengan tim penyusun,
keberadaan ruang/objek tanda tangan, penanggalan rilis, dan identitas kecamatan sesuai Pedoman 2023 Bab 4.3.5.
"""
def evaluate_kata_pengantar(meta, kabupaten_str, kab_upper, kab_raw, level_id, level_en, level_en_upper):
    region = meta["region"]
    year = meta["year"]
    preface_year = meta.get("preface_year", year)
    
    kata_pengantar = []
    if meta.get("preface_idx", -1) < 0:
        kata_pengantar.append(
            'Halaman Kata Pengantar/Preface tidak ditemukan dalam publikasi. '
            'Berdasarkan Pedoman Pembuatan Publikasi BPS 2023 Bab 4.3.5 (hal. 41) dan Instrumen baris 48, '
            'lembar Kata Pengantar WAJIB dimulai pada halaman GANJIL (recto / halaman kanan).'
        )
    else:
        if meta.get("preface_is_even"):
            kata_pengantar.append(
                f'Kesalahan penempatan halaman (Kata Pengantar pada Halaman Genap): Kata Pengantar dimulai pada halaman fisik {meta["preface_is_even"]} (GENAP). '
                f'Berdasarkan Pedoman Pembuatan Publikasi BPS 2023 Bab 4.3.5 (hal. 41) dan Instrumen baris 48, '
                f'lembar Kata Pengantar WAJIB dimulai pada halaman GANJIL (recto / halaman kanan).'
            )
        if meta.get("preface_other_districts"):
            dist_list = ", ".join(meta["preface_other_districts"])
            kata_pengantar.append(
                f'Narasi Kata Pengantar/Preface menyebut nama wilayah lain ("{dist_list}"), '
                f'padahal publikasi ini adalah {level_id} {region}. Seluruh naskah narasi wajib diselaraskan dengan identitas {level_id} {region}.'
            )
        if meta.get("preface_signature_missing"):
            kata_pengantar.append(
                'Tanda tangan penanggung jawab / Kepala BPS pada lembar Kata Pengantar dan Preface tidak ada / belum disisipkan. '
                'Ruang vertikal di atas nama Kepala BPS wajib memuat goresan tanda tangan resmi pejabat penanda tangan.'
            )
        if meta.get("preface_year_mismatch"):
            y_found, exp_y = meta["preface_year_mismatch"]
            kata_pengantar.append(
                f'Kesalahan tahun pada narasi teks Kata Pengantar: Teks menyebut tahun "{y_found}", '
                f'padahal publikasi ini adalah edisi tahun {exp_y}. Koreksi seharusnya: Selaraskan tahun narasi menjadi tahun {exp_y}.'
            )
        if meta.get("preface_titimangsa_mismatch"):
            kata_pengantar.append(meta["preface_titimangsa_mismatch"])
        if meta.get("preface_has_running_title"):
            kata_pengantar.append(
                'Running title tercetak di header atas halaman Kata Pengantar. Sesuai Pedoman 2023 hal. 49 & Instrumen baris 53, '
                'halaman pendahuluan (angka Romawi) DILARANG memiliki running title.'
            )
        if meta.get("preface_roman_missing"):
            kata_pengantar.append(
                'Nomor halaman romawi tidak tercantum pada halaman Kata Pengantar dan Preface '
                '(seharusnya tercantum nomor halaman romawi di bagian footer tengah, Pedoman 2023 hal. 48 & Instrumen baris 54).'
            )
        if meta.get("preface_has_toc_leak"):
            kata_pengantar.append(
                'Terdapat sisa baris template/Daftar Isi yang bocor pada halaman Kata Pengantar: '
                'tertulis "Kata Pengantar/Preface ...................." di bawah paragraf sebelum tanda tangan.'
            )
        if meta.get("jabatan_penanda_id_singkat"):
            kata_pengantar.append(
                'Penulisan jabatan penandatangan bahasa Indonesia disingkat: tertulis "Kepala BPS Kabupaten...". '
                'Sesuai aturan baku BPS (Instrumen baris 59), penulisan tidak boleh disingkat, yang benar adalah '
                '"Kepala Badan Pusat Statistik Kabupaten...".'
            )
        if meta.get("jabatan_penanda_en_chief"):
            kata_pengantar.append(
                'Penulisan jabatan penandatangan bahasa Inggris salah: tertulis "Chief Statistician of [Regency]". '
                'Standar baku publikasi BPS daerah adalah "Head of BPS-Statistics [Regency]" (Pedoman 2023 hal. 15, Instrumen baris 59).'
            )
        if meta.get("preface_typo_spasi"):
            kata_pengantar.append(
                'Saltik spasi pada teks Kata Pengantar bahasa Indonesia: tertulis "diterbitk an" (terdapat spasi di dalam kata, perbaiki menjadi "diterbitkan").'
            )
        if meta.get("preface_typo_dash"):
            kata_pengantar.append(
                'Tanda hubung pada teks Kata Pengantar: frasa "sebesar – besarnya" menggunakan en dash dan spasi, '
                'seharusnya menggunakan tanda hubung strip tanpa spasi: "sebesar-besarnya".'
            )
        if meta.get("preface_name_not_bold"):
            kata_pengantar.append(
                'Nama penandatangan Kepala BPS dan titimangsa (tempat, bulan, tahun) pada halaman Kata Pengantar dan Preface '
                'belum dicetak tebal (bold). Sesuai Pedoman Pembuatan Publikasi BPS 2023 Bab 4.3.5 (hal. 79 & 81), '
                'titimangsa dan nama lengkap penandatangan wajib dicetak tebal.'
            )
        if meta.get("preface_has_nip"):
            kata_pengantar.append(
                'Pencantuman NIP pada penandatangan Kata Pengantar: Sesuai Pedoman Pembuatan Publikasi BPS 2023 Bab 4 hal. 83 & Instrumen Baris 61, '
                'nama jelas penandatangan dibuat dalam format tebal (bold), boleh menyertakan gelar akademik, namun TANPA mencantumkan NIP.'
            )
        for err in meta.get("preface_en_errors", []):
            kata_pengantar.append(f'Kesalahan mutu terjemahan pada Preface (bahasa Inggris): {err}.')


    return kata_pengantar
