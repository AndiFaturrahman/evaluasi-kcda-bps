"""
Anatomi 9: Layout Isi, Batang Tubuh, Pembatas Bab, & Tipografi
Memeriksa tata letak pembatas bab ganjil, ulasan narasi kosong, gambar dummy kamera,
lorem ipsum, running title, format tabel statistik, catatan kaki, superskrip km2, dan saltik global.
"""
def evaluate_layout_isi(meta, kabupaten_str, kab_upper, kab_raw, level_id, level_en, level_en_upper):
    region = meta["region"]
    year = meta["year"]
    region_up = region.upper()
    dummy_figs = meta.get("dummy_figures", [])
    
    layout_isi = []
    if meta.get("divider_even_pages"):
        div_strs = ", ".join(f"{b_lbl} pada hal {p} (GENAP)" for b_lbl, p in meta["divider_even_pages"])
        layout_isi.append(
            f'Kesalahan penempatan pembatas bab (Pembatas Bab pada Halaman Genap): Terdeteksi lembar pembatas bab pada halaman genap: {div_strs}. '
            f'Sesuai Pedoman Pembuatan Publikasi BPS 2023 Bab 4.4 (hal. 53) dan Instrumen baris 119, lembar pembatas bab WAJIB selalu diletakkan '
            f'pada halaman GANJIL (recto / halaman sebelah kanan).'
        )
    if meta.get("chapter_opening_has_rt"):
        ch_rt_strs = ", ".join(f"{b_lbl} pada hal fisik {p}" for b_lbl, p in meta["chapter_opening_has_rt"])
        layout_isi.append(
            f'Running title tercetak pada halaman pertama bab ({ch_rt_strs}): '
            f'Sesuai Pedoman Pembuatan Publikasi BPS 2023 Bab 4.4 (hal. 57) & Instrumen baris 131, '
            f'halaman pertama setiap bab (awal bab yang memuat judul bab) DILARANG memuat running title (judul kepala).'
        )
    if meta.get("lorem_ipsum_pages"):
        pg_strs = [f"hal {lbl} (fisik hal {p})" for p, lbl in meta["lorem_ipsum_pages"][:8]]
        layout_isi.append(
            f'Ulasan statistik pada batang tubuh masih berupa teks dummy template Latin ("Lorem ipsum dolor sit amet..." / "Duis autem vel eum..."): '
            f'Terdeteksi pada {", ".join(pg_strs)}. Seluruh teks narasi ulasan Bab 1, Bab 2 s.d. Bab 7 wajib diganti dengan analisis deskriptif fenomena data riil {level_id} {region}.'
        )
    if meta.get("yyyyy_running_title_pages"):
        pg_strs = [f"hal {lbl} (fisik hal {p})" for p, lbl in meta["yyyyy_running_title_pages"][:8]]
        layout_isi.append(
            f'Running title di halaman ganjil/genap batang tubuh masih memuat teks template "YYYYY" ("YYYYY IN FIGURES" / "YYYYY DISTRICT IN FIGURES"): '
            f'Terdeteksi pada {", ".join(pg_strs)}. Running title wajib diganti dengan nama wilayah publikasi ("{region_up}").'
        )
    if meta.get("empty_peta_wilayah"):
        layout_isi.append(
            f'Gambar 1 (Peta Wilayah {level_id} / Map of {region} {level_en}) pada bab geografi masih kosong atau belum disisipkan peta spasial riil. '
            f'Wajib disisipkan peta orientasi batas wilayah.'
        )
    if meta.get("empty_grafik_jarak"):
        layout_isi.append(
            'Gambar 2 (Grafik Jarak ke Ibukota / Distance to Capital) belum menyajikan diagram visual data riil (sumber data masih tertulis "...."). '
            'Wajib dilengkapi dengan grafik visual riil dan sumber data resmi.'
        )
    if meta.get("xxx_figures"):
        xxx_figs_str = ", ".join([f"Gambar {f_num} pada hal {lbl}" for f_num, p, lbl in meta["xxx_figures"][:8]])
        layout_isi.append(
            f'Judul gambar grafik di Bab 2 s.d. Bab 7 belum dicantumkan dan masih berupa placeholder template ("xxx"): '
            f'Terdeteksi pada {xxx_figs_str}. Jika tidak menyajikan grafik riil, seluruh lembar placeholder gambar tersebut wajib dihapus dari naskah buku.'
        )
    if meta.get("missing_chapter_dividers"):
        ch_str = ", ".join(f"Bab {b}" for b in meta["missing_chapter_dividers"])
        layout_isi.append(
            f'Lembar pembatas bab (chapter divider) tidak ditemukan pada {ch_str}: '
            f'Sesuai Pedoman Publikasi BPS 2023 Bab 4.4 hal. 53 & Instrumen baris 117–118, setiap bab baru (Bab 1 s.d. Bab 7) wajib didahului oleh lembar pembatas bab berwarna.'
        )
    if dummy_figs:
        pg_list = sorted(set(str(df[1]) for df in dummy_figs))[:10]
        layout_isi.append(
            f'Pencantuman visual gambar dummy/placeholder ikon kamera pada halaman batang tubuh ({", ".join(pg_list)}): '
            f'Visual grafik/peta belum di-insert dan masih menyajikan visual placeholder template. '
            f'Dilarang merilis publikasi yang masih memuat visual dummy template.'
        )
    for jump in meta.get("page_number_jumps", []):
        layout_isi.append(
            f'Urutan nomor halaman tidak sesuai: Pada halaman fisik {jump["phys_curr"]} tercantum nomor halaman {jump["num_curr"]}, '
            f'padahal urutan seharusnya adalah halaman {jump["expected_num"]} '
            f'(terjadi loncatan penomoran dari halaman {jump["num_prev"]} pada halaman fisik {jump["phys_prev"]}).'
        )
    for tf in meta.get("table_findings", []):
        if tf not in layout_isi:
            layout_isi.append(tf)

    if meta.get("table_findings") and not any("PERATAAN TABEL STATISTIK" in x for x in layout_isi):
        layout_isi.append(
            '[STANDAR PERATAAN TABEL STATISTIK] Penyelarasan perataan angka dalam tabel statistik: '
            'Angka numerik pada sel data tabel wajib rata kanan (right aligned) agar nilai tempat desimal/satuan sejajar. '
            'Kepala kolom (header), satuan, dan simbol khusus (seperti tanda dash "–" atau "~0") wajib rata tengah (center aligned) (Pedoman BPS 2023 Bab 4 hal. 68).'
        )

    if meta.get("divider_has_page_num"):
        layout_isi.append(
            'Nomor halaman fisik tercetak pada lembar pembatas bab. '
            'Sesuai Pedoman Publikasi BPS 2023 hal. 53 & Instrumen baris 124, '
            'lembar pembatas bab dilarang memuat nomor halaman fisik dan running title.'
        )
    if meta.get("divider_has_running_title"):
        layout_isi.append(
            'Running title tercetak pada lembar pembatas bab. '
            'Sesuai Pedoman Publikasi BPS 2023 hal. 53 & Instrumen baris 124, '
            'lembar pembatas bab dilarang mencantumkan running title.'
        )

    if meta.get("even_start_chapters"):
        ch_str = ", ".join(f"Bab {b} pada hal {p} (GENAP)" for b, p in meta["even_start_chapters"])
        layout_isi.append(
            f'Pelanggaran aturan awal bab (Awal Bab wajib di Halaman Ganjil): Sesuai Pedoman 2023 hal. 53 & Instrumen baris 119–120, '
            f'setiap bab wajib dimulai pada halaman baru yaitu halaman GANJIL (halaman kanan) setelah pembatas bab. '
            f'Pada publikasi ini, {ch_str} akibat ketiadaan halaman kosong penyelarasan di balik pembatas bab.'
        )
    for phys_p, prt_p, bab_info in meta.get("empty_ulasan_chapters", []):
        layout_isi.append(
            f'Ulasan {bab_info} (hal {prt_p}, fisik hal {phys_p}) KOSONG TOTAL: Halaman hanya memuat header '
            f'tanpa narasi ulasan statistik sama sekali. Bab ulasan wajib menyajikan deskripsi tematik '
            f'yang menguraikan fenomena perkembangan data di kecamatan.'
        )
    if meta.get("rt_odd_wrong") or meta.get("rt_even_wrong"):
        wrong_pg_list = sorted(set(meta.get("rt_odd_wrong", []) + meta.get("rt_even_wrong", [])))[:10]
        wrong_str = ", ".join(f"hal {p}" for p in wrong_pg_list)
        layout_isi.append(
            f'Kesalahan format running title pada halaman batang tubuh ({wrong_str}): Sesuai Pedoman BPS 2023 hal. 49 & Instrumen baris 132, '
            f'halaman GANJIL (kanan) wajib memuat judul BAB aktif, dan halaman GENAP (kiri) wajib memuat judul publikasi '
            f'bahasa Indonesia.'
        )
    for p_phys, p_lbl, txt_found, exp_y in meta.get("wrong_year_refs", []):
        if int(p_phys) > 20: # Halaman isi
            layout_isi.append(
                f'Referensi tahun salah terdeteksi otomatis pada batang tubuh: Halaman {p_lbl}: tertulis "{txt_found}". '
                f'Seluruh referensi tahun wajib diselaraskan ke tahun {exp_y}.'
            )
            break
    for p_lbl, wrong_w, correct_w in meta.get("global_typos", [])[:10]:
        layout_isi.append(
            f'Saltik terdeteksi otomatis pada halaman {p_lbl}: Tertulis "{wrong_w}", penulisan yang benar adalah "{correct_w}".'
        )
    for p_num, p_lbl, fig_title in meta.get("fig_has_tahun", []):
        layout_isi.append(
            f'Gambar pada halaman {p_lbl} (hal fisik {p_num}): Judul gambar memuat kata "Tahun" sebelum angka tahun (\'{fig_title}\'). '
            f'Sesuai Pedoman Pembuatan Publikasi BPS 2023 hal. 101 & Instrumen Baris 169, judul gambar tidak perlu menampilkan kata "Tahun", '
            f'tetapi cukup diberikan tanda koma sebelum keterangan tahun (contoh: "..., 2024").'
        )


    return layout_isi
