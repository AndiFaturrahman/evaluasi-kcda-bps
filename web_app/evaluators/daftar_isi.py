"""
Anatomi 6 & 8: Daftar Isi, Daftar Tabel, Daftar Gambar, dan Daftar Lampiran
Memeriksa struktur hierarki bab, penempatan halaman ganjil (recto), keberadaan entri dummy ("xxx"),
syarat minimal 3 gambar riil, dan format dwibahasa sesuai Pedoman 2023 Bab 4.3.6–4.3.9.
"""
from .common import validate_issn_checksum

def evaluate_daftar_isi(meta):
    region = meta.get("region", "Wilayah")
    year = meta.get("year", 2026)
    issn = meta.get("issn", "-")
    catalog_no = meta.get("catalog", "-")
    
    daftar_isi = []
    if meta.get("toc_idx", -1) < 0:
        daftar_isi.append(
            'Halaman Daftar Isi (Contents) tidak ditemukan dalam publikasi. '
            'Berdasarkan Pedoman Pembuatan Publikasi BPS 2023 Bab 4.3.6 (hal. 42) dan Instrumen baris 66, '
            'Daftar Isi WAJIB dimulai pada halaman GANJIL (recto / halaman kanan).'
        )
    else:
        if meta.get("toc_is_even"):
            daftar_isi.append(
                f'Kesalahan penempatan halaman (Daftar Isi pada Halaman Genap): Daftar Isi dimulai pada halaman fisik {meta["toc_is_even"]} (GENAP). '
                f'Berdasarkan Pedoman Pembuatan Publikasi BPS 2023 Bab 4.3.6 (hal. 42) dan Instrumen baris 66, '
                f'Daftar Isi WAJIB dimulai pada halaman GANJIL (recto / halaman kanan).'
            )
        if meta.get("toc_volume_empty"):
            daftar_isi.append(
                'Volume terbitan pada header halaman Daftar Isi belum dicantumkan (masih berupa template "Volume xx"). '
                'Wajib diselaraskan dengan angka volume publikasi yang valid.'
            )
        if meta.get("toc_bookmark_error"):
            daftar_isi.append(
                'Terdapat kesalahan tautan nomor halaman pada Daftar Isi: Terdeteksi teks "Error! Bookmark not defined." '
                'pada rujukan halaman Preface / bab lainnya. Seluruh nomor halaman pada Daftar Isi wajib diperbarui (Update Field) dan dipastikan menunjuk ke nomor halaman yang benar.'
            )
        if meta.get("toc_issn_placeholder"):
            daftar_isi.append(
                'Nomor ISSN di pojok kanan atas halaman Daftar Isi masih berupa draf template ("ISSN XXXX -XXXX") / belum dicantumkan nomor resmi valid. '
                'Wajib mencantumkan nomor ISSN resmi publikasi tanpa tanda titik dua (Instrumen baris 69).'
            )
        elif meta.get("toc_issn_missing") and (meta.get("is_serial") or (issn and issn != "-") or meta.get("catalog", "").startswith("1102001")):
            disp_issn_toc = meta.get("issn_correct_from_registry") or (issn if (issn != "-" and validate_issn_checksum(issn)[0]) else "[Nomor ISSN]")
            sample_issn = f"ISSN {disp_issn_toc}" if disp_issn_toc != "[Nomor ISSN]" else "ISSN [Nomor ISSN]"
            daftar_isi.append(
                f'Nomor ISSN tidak dicantumkan di pojok kanan atas halaman Daftar Isi: '
                f'Publikasi berkala yang memiliki ISSN wajib mencantumkan "{sample_issn}" tanpa tanda titik dua (Instrumen baris 69).'
            )
        for err in meta.get("toc_errors", []):
            daftar_isi.append(f'Ketidaksinkronan rujukan nomor halaman pada Daftar Isi: {err}.')
        if meta.get("toc_preface_not_italic"):
            daftar_isi.append(
                'Kesalahan tipografi istilah bahasa asing pada Daftar Isi: Entri "Preface" atau istilah bahasa Inggris lainnya '
                'belum dicetak miring (masih reguler/tegak). Sesuai kaidah dwibahasa BPS, istilah bahasa asing wajib dicetak miring (italic).'
            )
        if meta.get("toc_figures_has_dots"):
            daftar_isi.append(
                'Placeholder titik-titik pada judul gambar di Daftar Isi: Judul entri gambar masih berupa tanda titik-titik ("..."). '
                'Wajib dilengkapi dengan judul substantif gambar atau baris entri disesuaikan.'
            )
        if meta.get("toc_has_running_title"):
            daftar_isi.append(
                'Running title tercetak di header atas halaman Daftar Isi. Sesuai Pedoman 2023 hal. 49 & Instrumen baris 75, '
                'halaman pendahuluan (angka Romawi) dilarang mencantumkan running title.'
            )
        if meta.get("toc_chapters_point_to_dividers"):
            div_str = ", ".join(f"Bab {b} ke hal {p}" for b, p in meta["toc_chapters_point_to_dividers"])
            daftar_isi.append(
                f'Rujukan nomor halaman bab di Daftar Isi keliru merujuk ke halaman pembatas bab ({div_str}). '
                f'Sesuai Pedoman BPS 2023, seluruh rujukan nomor halaman bab wajib merujuk ke halaman pertama materi isi bab, bukan ke halaman pembatas bab.'
            )
        if meta.get("toc_bilingual_slash_error"):
            daftar_isi.append(
                'Penulisan entri dwibahasa pada Daftar Isi belum menggunakan tanda garis miring (slash) dan cetak miring: '
                'contoh "Kata Pengantar/Preface" dan "Daftar Isi/Contents", dengan padanan bahasa Inggris dicetak miring (italic) '
                'sesuai Pedoman Pembuatan Publikasi BPS 2023 Bab 4.3.6.'
            )
        if meta.get("toc_subchapter_has_trailing_dot"):
            sample_dots = meta["toc_subchapter_has_trailing_dot"][:5]
            dots_str = ", ".join(f"'{s[0]}' pada subbab {s[2]}" for s in sample_dots)
            daftar_isi.append(
                f'Nomor subbab pada Daftar Isi diakhiri tanda titik: Ditemukan {dots_str}. '
                f'Sesuai Pedoman Pembuatan Publikasi BPS 2023 Bab 4.3.6 & Instrumen baris 74, '
                f'setelah nomor subbab tidak boleh ada tanda titik (contoh baku: "1.1 {sample_dots[0][2]}", bukan "{sample_dots[0][0]} {sample_dots[0][2]}").'
            )

    return daftar_isi

def evaluate_daftar_tabel_gambar(meta):
    region = meta.get("region", "Wilayah")
    year = meta.get("year", 2026)
    dummy_figs = meta.get("dummy_figures", [])
    
    daftar_tabel_gambar = []
    if meta.get("uses_daftar_grafik"):
        daftar_tabel_gambar.append(
            'Penggunaan istilah "Daftar Grafik" tidak sesuai standar: '
            'Sesuai Pedoman Pembuatan Publikasi BPS 2023 Bab 4.3.9 hal. 44 & Instrumen baris 94, '
            'publikasi BPS WAJIB menggunakan istilah "Daftar Gambar" (atau "DAFTAR GAMBAR/LIST OF FIGURES") '
            'meskipun seluruh isinya adalah grafik/diagram.'
        )
    if meta.get("toc_table_is_even"):
        daftar_tabel_gambar.append(
            f'Kesalahan penempatan halaman (Daftar Tabel pada Halaman Genap): Lembar Daftar Tabel dimulai pada halaman fisik {meta["toc_table_is_even"]} (GENAP). '
            f'Berdasarkan Pedoman Pembuatan Publikasi BPS 2023 Bab 4.3.8 (hal. 44) dan Instrumen baris 81, '
            f'lembar Daftar Tabel WAJIB dimulai pada halaman GANJIL (recto / halaman kanan).'
        )
    if meta.get("toc_figure_is_even"):
        daftar_tabel_gambar.append(
            f'Kesalahan penempatan halaman (Daftar Gambar pada Halaman Genap): Lembar Daftar Gambar dimulai pada halaman fisik {meta["toc_figure_is_even"]} (GENAP). '
            f'Berdasarkan Pedoman Pembuatan Publikasi BPS 2023 Bab 4.3.9 (hal. 44) dan Instrumen baris 86, '
            f'lembar Daftar Gambar WAJIB dimulai pada halaman GANJIL (recto / halaman kanan).'
        )
    if meta.get("daftar_gambar_unnecessary"):
        daftar_tabel_gambar.append(
            'Publikasi hanya memiliki kurang dari 3 gambar riil. Merujuk pada Pedoman Pembuatan Publikasi BPS 2023 Bab 4.3.9 poin 3 (hal. 44) '
            '& Instrumen baris 87, lembar Daftar Gambar hanya disajikan jika terdapat minimal 3 gambar riil dalam publikasi. '
            'Karena publikasi ini belum memiliki minimal 3 gambar riil, maka lembar halaman Daftar Gambar wajib ditiadakan/dihapus dari buku.'
        )
    if meta.get("daftar_gambar_has_xxx"):
        daftar_tabel_gambar.append(
            'Daftar Gambar masih memuat entri dummy/placeholder template bertuliskan "xxx" pada rujukan judul Gambar 3 sampai 14. '
            'Seluruh entri dummy template wajib dihapus dari naskah publikasi.'
        )
    dummy_figs = meta.get("dummy_figures", [])
    if dummy_figs:
        fig_nums = [df[0] for df in dummy_figs]
        daftar_tabel_gambar.append(
            f'Kesalahan visual gambar dummy/placeholder di seluruh bab: Ditemukan {len(dummy_figs)} lembar gambar '
            f'(Gambar {", ".join(fig_nums[:8])}) yang masih memuat kotak placeholder ikon kamera / elipsis bawaan template. '
            f'Wajib dimasukkan visual gambar/peta riil beserta sumber valid, atau seluruh halaman gambar placeholder dihapus dari buku.'
        )
    if meta.get("daftar_tabel_running_title"):
        daftar_tabel_gambar.append(
            'Running title tercetak di header/footer halaman Daftar Tabel. Sesuai Pedoman 2023 hal. 49, '
            'halaman pendahuluan (angka Romawi) dilarang mencantumkan running title.'
        )
    if meta.get("daftar_gambar_placeholder"):
        daftar_tabel_gambar.append(
            'Judul gambar pada Daftar Gambar masih berupa placeholder titik-titik "...". '
            'Judul seluruh grafik dan infografis wajib didefinisikan secara substantif.'
        )
    if meta.get("toc_table_has_trailing_dot"):
        daftar_tabel_gambar.append(
            'Nomor tabel pada lembar Daftar Tabel diakhiri tanda titik: '
            'Sesuai Pedoman Pembuatan Publikasi BPS 2023 Bab 4.3.8 hal. 44 & Instrumen baris 83, '
            'nomor tabel pada Daftar Tabel TIDAK PERLU diakhiri tanda titik (contoh baku: "Tabel 1.1 Judul", bukan "Tabel 1.1. Judul").'
        )
    if meta.get("toc_figure_has_trailing_dot"):
        daftar_tabel_gambar.append(
            'Nomor gambar pada lembar Daftar Gambar diakhiri tanda titik: '
            'Sesuai Pedoman Pembuatan Publikasi BPS 2023 Bab 4.3.9 hal. 44 & Instrumen baris 92, '
            'nomor gambar pada Daftar Gambar TIDAK PERLU diakhiri tanda titik (contoh baku: "Gambar 1 Judul", bukan "Gambar 1. Judul").'
        )
    if meta.get("uses_daftar_peta"):
        daftar_tabel_gambar.append(
            'Ditemukan lembar Daftar Peta pada bagian pendahuluan: '
            'Berdasarkan Pedoman Pembuatan Publikasi BPS 2023 Bab 4.3 & Instrumen baris 180, '
            'peta merupakan bagian dari gambar dan wajib diberikan nomor serta judul Gambar (bukan Peta), '
            'serta tidak diperkenankan membuat halaman lembar "Daftar Peta" tersendiri (seluruh peta wajib dihimpun ke dalam Daftar Gambar).'
        )

    return daftar_tabel_gambar

