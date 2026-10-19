"""
Evaluator Kepatuhan Dwibahasa Publikasi BPS (Bilingual Compliance Auditor)
Memeriksa kepatuhan dwibahasa (Bahasa Indonesia dan Bahasa Inggris) pada SELURUH halaman
dan komponen anatomi publikasi sesuai Pedoman Pembuatan Publikasi BPS 2023 & Instrumen Pemeriksaan:
1. Kover Depan: Judul dwibahasa (Inggris dicetak miring), Satker dwibahasa (BPS-Statistics).
2. Halaman Judul Utama (HJU): Judul dwibahasa, Satker dwibahasa.
3. Halaman Katalog: Judul dwibahasa, 11 metadata label dwibahasa, klausul hak cipta dwibahasa.
4. Halaman Tim Penyusun: Judul "TIM PENYUSUN/COMPILERS", 6 peran dwibahasa.
5. Halaman Kata Pengantar: Teks terjemahan bahasa Inggris (lembar Preface atau format 2 kolom), jabatan penandatangan dwibahasa.
6. Halaman Daftar Isi: Judul "DAFTAR ISI/CONTENTS", header kolom "Halaman/Page", judul-judul bab dwibahasa.
7. Daftar Tabel & Daftar Gambar: Judul "DAFTAR TABEL/LIST OF TABLES", header "Tabel/Table", "Gambar/Figure".
8. Penjelasan Umum/Teknis: Judul "PENJELASAN TEKNIS/TECHNICAL NOTES", teks dwibahasa.
9. Pembatas Bab: Judul bab dwibahasa ("BAB 1 GEOGRAFI DAN IKLIM / CHAPTER 1 GEOGRAPHY AND CLIMATE").
10. Batang Tubuh (Tabel & Grafik): Judul tabel dwibahasa ("Tabel ... / Table ..."), Sumber/Source, Catatan/Note.
11. Kover Belakang: Slogan dwibahasa ("DATA MENCERDASKAN BANGSA / DATA EMPOWERS THE NATION"), Satker dwibahasa (BPS-Statistics).
"""
import re

def audit_bilingual_compliance(meta, raw_res):
    """
    Melakukan audit kepatuhan format dwibahasa (bilingual) di SELURUH bagian anatomi publikasi.
    Menyuntikkan temuan langsung ke seksi terkait pada raw_res.
    """
    is_serial = (
        meta.get("is_serial")
        or meta.get("cover_is_bilingual")
        or meta.get("catalog", "").startswith("1102001")
        or "DALAM ANGKA" in meta.get("title", "").upper()
    )
    if not is_serial:
        return

    region = meta.get("region", "Wilayah")
    year = meta.get("year", "2026")
    region_up = region.upper()
    pub_level = meta.get("pub_level", "kecamatan")
    level_en = "Municipality" if pub_level == "kota" else "Regency" if pub_level == "kabupaten" else "District"
    level_en_upper = level_en.upper()

    bilingual_findings = []

    # ─────────────────────────────────────────────────────────────────────────
    # 1. KOVER DEPAN
    # ─────────────────────────────────────────────────────────────────────────
    cov_defects = raw_res.get("Kover depan: -", [])
    if not meta.get("cover_has_english_title", True):
        msg = (
            f'Judul terjemahan bahasa Inggris belum dicantumkan pada kover depan: '
            f'Publikasi Kecamatan Dalam Angka merupakan publikasi dwibahasa yang wajib menyertakan terjemahan judul bahasa asing '
            f'("{region_up} {level_en_upper} IN FIGURES {year}") dengan cetak miring (italic) di bawah judul bahasa Indonesia '
            f'(Pedoman Pembuatan Publikasi BPS 2023 hal. 58, Template KCDA 2026, dan Instrumen baris 8).'
        )
        if not any("terjemahan bahasa inggris" in x.lower() for x in cov_defects):
            cov_defects.append(msg)
            bilingual_findings.append(("Kover Depan", msg))

    if meta.get("cover_publisher_not_bilingual"):
        msg = (
            'Nama satker BPS pada kover depan belum mencantumkan versi bahasa Inggris ("BPS-Statistics ... Regency/Municipality") '
            'karena publikasinya dua bahasa (Pedoman Pembuatan Publikasi BPS 2023 halaman 64).'
        )
        if not any("satker bps pada kover depan" in x.lower() for x in cov_defects):
            cov_defects.append(msg)
            bilingual_findings.append(("Kover Depan", msg))

    # ─────────────────────────────────────────────────────────────────────────
    # 2. HALAMAN JUDUL UTAMA (HJU)
    # ─────────────────────────────────────────────────────────────────────────
    hju_defects = raw_res.get("Halaman Judul Utama: -", [])
    if not meta.get("hju_has_english_title", True):
        msg = (
            f'Judul terjemahan bahasa Inggris belum dicantumkan pada Halaman Judul Utama: '
            f'Publikasi dwibahasa wajib menyertakan terjemahan judul bahasa asing ("{region_up} {level_en_upper} IN FIGURES {year}") '
            f'yang dicetak miring (italic) di bawah judul bahasa Indonesia (Pedoman 2023 Bab 4.3.1 hal. 36 & Instrumen baris 18).'
        )
        if not any("terjemahan bahasa inggris" in x.lower() for x in hju_defects):
            hju_defects.append(msg)
            bilingual_findings.append(("Halaman Judul Utama", msg))

    if meta.get("cover_publisher_not_bilingual"):
        msg = (
            'Nama satker BPS pada Halaman Judul Utama belum mencantumkan versi bahasa Inggris ("BPS-Statistics ...") '
            'karena publikasinya dua bahasa (Pedoman Pembuatan Publikasi BPS 2023 halaman 64).'
        )
        if not any("satker bps pada halaman judul utama" in x.lower() for x in hju_defects):
            hju_defects.append(msg)
            bilingual_findings.append(("Halaman Judul Utama", msg))

    # ─────────────────────────────────────────────────────────────────────────
    # 3. HALAMAN KATALOG
    # ─────────────────────────────────────────────────────────────────────────
    kat_defects = raw_res.get("Halaman katalog: -", [])
    missing_bilingual = meta.get("catalog_bilingual_missing", [])
    if len(missing_bilingual) >= 3:
        missing_str = "; ".join(missing_bilingual)
        msg = (
            f'Halaman Katalog belum disajikan dalam format dwibahasa (bilingual): '
            f'Publikasi Kecamatan Dalam Angka merupakan publikasi dwibahasa yang wajib menyajikan judul dan seluruh label metadata katalog dalam dua bahasa (Indonesia/Inggris) '
            f'sesuai Pedoman Pembuatan Publikasi BPS 2023 Bab 4.3.2 (hal. 37), Template KCDA 2026, dan Instrumen Pemeriksaan baris 24–33. '
            f'Komponen yang belum memuat padanan bahasa Inggris meliputi: {missing_str}.'
        )
        if not any("format dwibahasa" in x.lower() for x in kat_defects):
            kat_defects.append(msg)
            bilingual_findings.append(("Halaman Katalog", msg))
    elif len(missing_bilingual) > 0:
        for item_mis in missing_bilingual:
            msg = (
                f'Label/komponen "{item_mis}" pada Halaman Katalog belum dwibahasa: '
                f'Sesuai kaidah publikasi dwibahasa BPS (Pedoman 2023 hal. 37 & Instrumen baris 24–33), '
                f'komponen tersebut wajib memuat padanan bahasa Inggris resmi.'
            )
            if not any(item_mis.lower() in x.lower() for x in kat_defects):
                kat_defects.append(msg)
                bilingual_findings.append(("Halaman Katalog", msg))

    # ─────────────────────────────────────────────────────────────────────────
    # 4. HALAMAN TIM PENYUSUN
    # ─────────────────────────────────────────────────────────────────────────
    team_defects = raw_res.get("Halaman Tim Penyusun: -", [])
    team_text = meta.get("team_text", "")
    if team_text:
        # Cek judul lembar Tim Penyusun
        has_compilers = bool(re.search(r'COMPILERS|TEAM\s+MEMBERS', team_text, re.I))
        if not has_compilers and "TIM PENYUSUN" in team_text.upper():
            msg = (
                'Judul lembar Tim Penyusun belum dwibahasa: Tertulis hanya "TIM PENYUSUN" tanpa padanan bahasa Inggris. '
                'Sesuai Pedoman Pembuatan Publikasi BPS 2023 (hal. 81) & Instrumen baris 37, publikasi dwibahasa wajib menggunakan judul "TIM PENYUSUN/COMPILERS".'
            )
            if not any("judul lembar tim penyusun" in x.lower() for x in team_defects):
                team_defects.append(msg)
                bilingual_findings.append(("Tim Penyusun", msg))

        # Cek label peran/jabatan tim dwibahasa
        missing_roles_en = []
        role_checks = [
            ("Pengarah", "Director"),
            ("Penanggung Jawab", "Person"),
            ("Penyunting", "Editor"),
            ("Pengolah Data", "Data Processor"),
            ("Penata Letak", "Layouter"),
            ("Penerjemah", "Translator"),
        ]
        for id_r, en_r in role_checks:
            if re.search(rf'\b{id_r}\b', team_text, re.I) and not re.search(rf'\b{en_r}\b', team_text, re.I):
                missing_roles_en.append(f"{id_r}/{en_r}")

        if len(missing_roles_en) >= 2:
            roles_str = ", ".join(missing_roles_en)
            msg = (
                f'Sebutan peran pada Halaman Tim Penyusun belum dwibahasa: '
                f'Ditemukan peran tim yang hanya ditulis dalam bahasa Indonesia tanpa padanan bahasa Inggris: {roles_str}. '
                f'Sesuai Pedoman Pembuatan Publikasi BPS 2023 Bab 4.3.3 & Instrumen baris 38, sebutan peran tim publikasi dwibahasa wajib ditulis lengkap (Indonesia/Inggris).'
            )
            if not any("sebutan peran" in x.lower() for x in team_defects):
                team_defects.append(msg)
                bilingual_findings.append(("Tim Penyusun", msg))

    # ─────────────────────────────────────────────────────────────────────────
    # 5. KATA PENGANTAR (PREFACE)
    # ─────────────────────────────────────────────────────────────────────────
    preface_defects = raw_res.get("Kata pengantar: -", [])
    has_preface_en = meta.get("has_preface_en", False)
    comb_preface = (meta.get("preface_text", "") + " " + meta.get("preface_en_text", "")).upper()
    if not has_preface_en and "PREFACE" not in comb_preface:
        msg = (
            'Teks Kata Pengantar bahasa Inggris (Preface) belum dicantumkan: '
            'Publikasi Kecamatan Dalam Angka merupakan publikasi dwibahasa yang wajib menyajikan Kata Pengantar dalam format dua bahasa '
            '(halaman Preface tersendiri atau format 2 kolom Indonesia-Inggris) sesuai Pedoman Pembuatan Publikasi BPS 2023 Bab 4.3.4 (hal. 39) & Instrumen baris 42.'
        )
        if not any("kata pengantar bahasa inggris" in x.lower() for x in preface_defects):
            preface_defects.append(msg)
            bilingual_findings.append(("Kata Pengantar", msg))

    # ─────────────────────────────────────────────────────────────────────────
    # 6. DAFTAR ISI (CONTENTS)
    # ─────────────────────────────────────────────────────────────────────────
    toc_defects = raw_res.get("Daftar Isi: -", [])
    toc_text = meta.get("toc_text", "")
    if toc_text:
        # Cek judul lembar Daftar Isi
        has_contents = bool(re.search(r'CONTENTS|TABLE\s+OF\s+CONTENTS', toc_text, re.I))
        if not has_contents and "DAFTAR ISI" in toc_text.upper():
            msg = (
                'Judul lembar Daftar Isi belum dwibahasa: Tertulis hanya "DAFTAR ISI" tanpa padanan bahasa Inggris. '
                'Sesuai Pedoman Pembuatan Publikasi BPS 2023 Bab 4.3.6 (hal. 41) & Instrumen baris 61, publikasi dwibahasa wajib menggunakan judul "DAFTAR ISI/CONTENTS".'
            )
            if not any("judul lembar daftar isi" in x.lower() for x in toc_defects):
                toc_defects.append(msg)
                bilingual_findings.append(("Daftar Isi", msg))

        # Cek header kolom Halaman/Page
        if re.search(r'\bHalaman\b', toc_text, re.I) and not re.search(r'\bPage\b', toc_text, re.I):
            msg = (
                'Header kolom halaman pada Daftar Isi belum dwibahasa: Tertulis hanya "Halaman" tanpa padanan bahasa Inggris. '
                'Sesuai standar publikasi dwibahasa BPS, header kolom wajib ditulis "Halaman/Page".'
            )
            if not any("header kolom halaman pada daftar isi" in x.lower() for x in toc_defects):
                toc_defects.append(msg)
                bilingual_findings.append(("Daftar Isi", msg))

        # Cek terjemahan bab di daftar isi
        has_ch_id = bool(re.search(r'GEOGRAFI\s+DAN\s+IKLIM', toc_text, re.I))
        has_ch_en = bool(re.search(r'GEOGRAPHY\s+AND\s+CLIMATE', toc_text, re.I))
        if has_ch_id and not has_ch_en:
            msg = (
                'Judul bab pada Daftar Isi belum dwibahasa: Judul-judul bab utama (Bab 1 s.d. Bab 7) belum memuat terjemahan bahasa Inggris resmi '
                '(contoh baku: "1. GEOGRAFI DAN IKLIM/GEOGRAPHY AND CLIMATE") sesuai kaidah publikasi dwibahasa BPS (Pedoman 2023 Bab 4.3.6).'
            )
            if not any("judul bab pada daftar isi" in x.lower() for x in toc_defects):
                toc_defects.append(msg)
                bilingual_findings.append(("Daftar Isi", msg))

    # ─────────────────────────────────────────────────────────────────────────
    # 7. DAFTAR TABEL & DAFTAR GAMBAR
    # ─────────────────────────────────────────────────────────────────────────
    list_defects = raw_res.get("Daftar Tabel/Gambar/Grafik/Lampiran:", [])
    toc_tbl_txt = meta.get("toc_table_text", "")
    if toc_tbl_txt:
        if "DAFTAR TABEL" in toc_tbl_txt.upper() and "LIST OF TABLES" not in toc_tbl_txt.upper() and "/" not in toc_tbl_txt[:60]:
            msg = (
                'Judul lembar Daftar Tabel belum dwibahasa: Tertulis hanya "DAFTAR TABEL" tanpa padanan bahasa Inggris. '
                'Sesuai Pedoman 2023 Bab 4.3.8 & Instrumen baris 79, publikasi dwibahasa wajib menggunakan judul "DAFTAR TABEL/LIST OF TABLES".'
            )
            if not any("judul lembar daftar tabel" in x.lower() for x in list_defects):
                list_defects.append(msg)
                bilingual_findings.append(("Daftar Tabel", msg))

    toc_fig_txt = meta.get("toc_figure_text", "")
    if toc_fig_txt:
        if "DAFTAR GAMBAR" in toc_fig_txt.upper() and "LIST OF FIGURES" not in toc_fig_txt.upper() and "/" not in toc_fig_txt[:60]:
            msg = (
                'Judul lembar Daftar Gambar belum dwibahasa: Tertulis hanya "DAFTAR GAMBAR" tanpa padanan bahasa Inggris. '
                'Sesuai Pedoman 2023 Bab 4.3.9 & Instrumen baris 84, publikasi dwibahasa wajib menggunakan judul "DAFTAR GAMBAR/LIST OF FIGURES".'
            )
            if not any("judul lembar daftar gambar" in x.lower() for x in list_defects):
                list_defects.append(msg)
                bilingual_findings.append(("Daftar Gambar", msg))

    # ─────────────────────────────────────────────────────────────────────────
    # 8. PENJELASAN TEKNIS / UMUM
    # ─────────────────────────────────────────────────────────────────────────
    penj_defects = raw_res.get("Penjelasan Umum:", [])
    penj_txt = meta.get("penjelasan_text", "")
    if penj_txt:
        if ("PENJELASAN TEKNIS" in penj_txt.upper() or "PENJELASAN UMUM" in penj_txt.upper()) and "TECHNICAL NOTES" not in penj_txt.upper() and "/" not in penj_txt[:60]:
            msg = (
                'Judul lembar Penjelasan Teknis belum dwibahasa: Tertulis hanya "PENJELASAN TEKNIS" tanpa padanan bahasa Inggris. '
                'Sesuai Pedoman 2023 Bab 4.3.10 & Instrumen baris 90, publikasi dwibahasa wajib menggunakan judul "PENJELASAN TEKNIS/TECHNICAL NOTES".'
            )
            if not any("judul lembar penjelasan teknis" in x.lower() for x in penj_defects):
                penj_defects.append(msg)
                bilingual_findings.append(("Penjelasan Teknis", msg))

    # ─────────────────────────────────────────────────────────────────────────
    # 9. BATANG TUBUH (TABEL, GRAFIK & PEMBATAS BAB)
    # ─────────────────────────────────────────────────────────────────────────
    layout_defects = raw_res.get("Layout Isi:", [])
    sample_tables = meta.get("sample_tables", [])
    if sample_tables:
        non_bilingual_tables = [t for t in sample_tables if not t.get("is_bilingual")]
        if len(sample_tables) >= 5 and (len(non_bilingual_tables) / len(sample_tables)) >= 0.5:
            msg = (
                'Judul dan sumber tabel data pada batang tubuh belum disajikan dalam dwibahasa: '
                f'Terdeteksi {len(non_bilingual_tables)} dari {len(sample_tables)} sampel tabel hanya menyajikan judul/keterangan dalam bahasa Indonesia tanpa padanan bahasa Inggris. '
                'Sesuai Pedoman Pembuatan Publikasi BPS 2023 Bab 4.4 hal. 55 & Instrumen baris 136, judul tabel wajib memuat terjemahan ("Tabel ... / Table ...") '
                'serta keterangan sumber dwibahasa ("Sumber/Source:").'
            )
            if not any("tabel data pada batang tubuh" in x.lower() for x in layout_defects):
                layout_defects.append(msg)
                bilingual_findings.append(("Layout Isi", msg))

    # Pembatas bab
    divider_texts = meta.get("divider_texts", [])
    if divider_texts:
        non_bi_div = [d for d in divider_texts if "CHAPTER" not in d.upper() and "/" not in d]
        if len(non_bi_div) >= 3:
            msg = (
                'Judul bab pada lembar pembatas bab belum disajikan dalam dwibahasa: '
                'Lembar pembatas bab hanya memuat judul bab bahasa Indonesia tanpa terjemahan bahasa Inggris resmi. '
                'Sesuai Pedoman 2023 Bab 4.4 hal. 53, pembatas bab pada publikasi dwibahasa wajib menyertakan padanan bahasa Inggris (contoh: "BAB 1 GEOGRAFI DAN IKLIM / CHAPTER 1 GEOGRAPHY AND CLIMATE").'
            )
            if not any("pembatas bab belum disajikan dalam dwibahasa" in x.lower() for x in layout_defects):
                layout_defects.append(msg)
                bilingual_findings.append(("Layout Isi", msg))

    # ─────────────────────────────────────────────────────────────────────────
    # 10. KOVER BELAKANG
    # ─────────────────────────────────────────────────────────────────────────
    kb_defects = raw_res.get("Kover belakang: -", [])
    last_page_text = meta.get("last_page_text", "")
    if last_page_text:
        has_slogan_id = "DATA MENCERDASKAN" in last_page_text.upper()
        has_slogan_en = "DATA EMPOWERS" in last_page_text.upper()
        if has_slogan_id and not has_slogan_en:
            msg = (
                'Slogan pada kover belakang belum disajikan dalam format dwibahasa: Tertulis hanya "DATA MENCERDASKAN BANGSA". '
                'Sesuai Pedoman Pembuatan Publikasi BPS 2023 (hal. 64 & hal. 2008), publikasi dwibahasa wajib menyertakan slogan versi bahasa Inggris: "DATA EMPOWERS THE NATION".'
            )
            if not any("slogan pada kover belakang belum" in x.lower() for x in kb_defects):
                kb_defects.append(msg)
                bilingual_findings.append(("Kover Belakang", msg))

        has_bps_id_kb = "BADAN PUSAT STATISTIK" in last_page_text.upper()
        has_bps_en_kb = "BPS-STATISTICS" in last_page_text.upper()
        if has_bps_id_kb and not has_bps_en_kb:
            msg = (
                'Nama satker BPS pada kover belakang belum menyertakan versi bahasa Inggris ("BPS-Statistics ..."). '
                'Sesuai Pedoman Pembuatan Publikasi BPS 2023 (hal. 64), publikasi dwibahasa wajib mencantumkan nama BPS dalam dwibahasa.'
            )
            if not any("satker bps pada kover belakang belum" in x.lower() for x in kb_defects):
                kb_defects.append(msg)
                bilingual_findings.append(("Kover Belakang", msg))

    # Simpan ringkasan audit dwibahasa ke meta
    meta["bilingual_audit"] = {
        "is_bilingual_publication": True,
        "total_bilingual_findings": len(bilingual_findings),
        "findings_by_section": bilingual_findings
    }
