"""
Anatomi 4: Halaman Tim Penyusun Publikasi BPS
Memeriksa susunan tim pengarah, penanggung jawab, penyunting, pengolah data, penata letak,
serta kaidah tata bahasa dwibahasa (jamak dengan akhiran 's' vs tunggal) sesuai Pedoman 2023 hal. 81.
"""
from .common import JABATAN_SALAH_JAMAK, validate_issn_checksum

def evaluate_tim_penyusun(meta, kabupaten_str, kab_upper, kab_raw, level_id, level_en, level_en_upper):
    region = meta["region"]
    year = meta["year"]
    team_issn = meta.get("team_issn")
    
    tim_penyusun = []
    if meta.get("team_idx", -1) < 0:
        tim_penyusun.append(
            'Halaman Tim Penyusun tidak ditemukan dalam publikasi. '
            'Berdasarkan Pedoman Pembuatan Publikasi BPS 2023 Bab 4.3.3 (hal. 39) dan Instrumen baris 36, '
            'Halaman Tim Penyusun WAJIB disajikan pada lembar tersendiri yang dimulai pada halaman GANJIL (recto / halaman kanan, umumnya halaman fisik 5).'
        )
    else:
        if meta.get("team_is_even"):
            tim_penyusun.append(
                f'Kesalahan penempatan halaman (Tim Penyusun pada Halaman Genap): Lembar Tim Penyusun dimulai pada halaman fisik {meta["team_is_even"]} (GENAP). '
                f'Berdasarkan Pedoman Pembuatan Publikasi BPS 2023 Bab 4.3.3 (hal. 39) dan Instrumen baris 36, '
                f'Halaman Tim Penyusun WAJIB dimulai pada halaman GANJIL (recto / halaman kanan, umumnya halaman fisik 5 setelah halaman katalog).'
            )
        if meta.get("team_merged_with_catalog"):
            tim_penyusun.append(
                f'Pelanggaran pemisahan lembar susunan tim: Halaman Tim Penyusun digabung pada lembar yang sama dengan Halaman Katalog (halaman fisik {meta["team_merged_with_catalog"]}). '
                f'Sesuai Pedoman Pembuatan Publikasi BPS 2023 Bab 4.3 & Instrumen baris 36, Halaman Tim Penyusun WAJIB disajikan pada lembar tersendiri '
                f'yang terpisah dari Halaman Katalog.'
            )
        if meta.get("team_is_template"):
            tim_penyusun.append(
                'Halaman Tim Penyusun masih berupa format template master yang belum diubah: '
                'Memuat teks instruksi template ("nama kepala BPS Kako tanpa gelar", "xxxxx • xxxxx", "Volume xx", atau "ISSN XXXX -XXXX"). '
                'Seluruh nama pembina, penanggung jawab, editor, penulis, pengolah data, dan penata letak wajib diisi personil riil BPS Kabupaten.'
            )
        if meta.get("team_title_nonstandard"):
            tim_penyusun.append(
                'Judul halaman bahasa Inggris tidak standar: tertulis "TIM PENYUSUN/TEAM MEMBERS". '
                'Standar resmi dwibahasa BPS adalah "TIM PENYUSUN/COMPILERS" (Pedoman hal. 81, Instrumen baris 37).'
            )
        if meta.get("team_issn_has_colon"):
            tim_penyusun.append(
                f'Nomor ISSN di pojok kanan atas halaman Tim Penyusun menggunakan titik dua: tertulis "ISSN: {team_issn}". '
                f'Wajib dicantumkan tanpa titik dua: "ISSN {team_issn}".'
            )
        elif meta.get("team_issn_missing"):
            tim_penyusun.append(
                f'Nomor ISSN tidak dicantumkan di pojok kanan atas halaman Tim Penyusun: '
                f'Publikasi berkala yang memiliki ISSN wajib mencantumkan "ISSN {team_issn}" di pojok kanan atas tanpa tanda titik dua (Pedoman hal. 35 & Instrumen baris 39).'
            )
        for item in meta.get("jabatan_errors", []):
            if len(item) == 3:
                wrong, correct, cnt = item
                tim_penyusun.append(
                    f'Jabatan {wrong} dalam bahasa Inggris keliru bentuk jamak padahal personilnya hanya satu orang: tertulis "{wrong}", '
                    f'seharusnya bentuk tunggal standar BPS yaitu "{correct}".'
                )
            else:
                wrong, correct = item
                tim_penyusun.append(
                    f'Jabatan {wrong} dalam bahasa Inggris keliru: tertulis "{wrong}", '
                    f'seharusnya "{correct}".'
                )
        for tip in meta.get("jabatan_tips", []):
            tim_penyusun.append(f'[SARAN PEDOMAN TIM PENYUSUN] {tip}')
        if meta.get("team_writers_merged"):
            tim_penyusun.append(
                'Jabatan Penulis Naskah dan Pengolah Data digabung: Sesuai Pedoman BPS 2023 (Instrumen baris 42), '
                'wajib dipisahkan menjadi "Penulis Naskah/Writer" dan "Pengolah Data/Data Processor".'
            )
        if meta.get("degree_mismatch"):
            t_name, p_name = meta["degree_mismatch"]
            tim_penyusun.append(
                f'Inkonsistensi pencantuman gelar: Nama Pengarah/Penanggung Jawab pada Tim Penyusun ditulis tanpa gelar ("{t_name}"), '
                f'sedangkan pada Kata Pengantar nama Kepala BPS ditulis lengkap dengan gelar ("{p_name}"). '
                f'Penulisan gelar wajib konsisten di seluruh bagian publikasi (Instrumen baris 44 & 61).'
            )
        if meta.get("team_has_nip"):
            tim_penyusun.append(
                'Pencantuman NIP pada Halaman Tim Penyusun: Sesuai Pedoman Pembuatan Publikasi BPS 2023 Bab 4 hal. 80 & Instrumen Baris 41–42, '
                'susunan anggota tim penyusun ditulis tanpa mencantumkan NIP.'
            )


    return tim_penyusun
