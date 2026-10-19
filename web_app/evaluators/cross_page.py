"""
Audit Konsistensi Lintas Halaman & Integritas Dokumen Publikasi BPS
Memeriksa konsistensi nomor ISSN antar-halaman, nomor halaman Romawi pendahuluan,
deteksi kelalaian ganti kover (District Identity Mismatch), deteksi upload template mentah (Raw Template),
penggabungan hasil Computer Vision, dan rekomendasi estetika BPS.
"""
from .common import get_aesthetic_and_standard_suggestions

def _to_roman_uncached(n):
    val = [1000, 900, 500, 400, 100, 90, 50, 40, 10, 9, 5, 4, 1]
    syb = ["m", "cm", "d", "cd", "c", "xc", "l", "xl", "x", "ix", "v", "iv", "i"]
    r = ''
    i = 0
    while n > 0:
        for _ in range(n // val[i]):
            r += syb[i]
            n -= val[i]
        i += 1
    return r

def apply_cross_page_checks(meta, defects_dict):
    region = meta["region"]
    year = meta["year"]
    pub_level = meta.get("pub_level", "kecamatan")
    if pub_level == "kota":
        level_id = "Kota"
    elif pub_level == "kabupaten":
        level_id = "Kabupaten"
    else:
        level_id = "Kecamatan"

    kover_depan = defects_dict["Kover depan: -"]
    halaman_judul = defects_dict["Halaman Judul Utama: -"]
    halaman_katalog = defects_dict["Halaman katalog: -"]
    tim_penyusun = defects_dict["Halaman Tim Penyusun: -"]
    kata_pengantar = defects_dict["Kata pengantar: -"]
    daftar_isi = defects_dict["Daftar Isi: -"]
    penjelasan_umum = defects_dict.get("Penjelasan Umum:", [])
    daftar_tabel_gambar = defects_dict.get("Daftar Tabel/Gambar/Grafik/Lampiran:", [])
    layout_isi = defects_dict["Layout Isi:"]
    daftar_pustaka = defects_dict.get("Daftar Pustaka: -", [])
    kover_belakang = defects_dict["Kover belakang: -"]

    # ── ISSN CROSS-PAGE INCONSISTENCY ──
    cat_idx = meta.get("catalog_idx", -1)
    team_idx = meta.get("team_idx", -1)
    hju_idx = meta.get("hju_idx", -1)
    toc_idx = meta.get("toc_idx", -1)
    correct_issn = meta.get("issn_correct_from_registry")

    if meta.get("issn_cross_page_inconsistent"):
        details = meta.get("issn_cross_page_details", [])
        detail_parts = []
        for d in details:
            issn_v = d["issn"]
            label_list = ", ".join(d["labels"])
            is_correct = correct_issn and issn_v == correct_issn
            marker = " (BENAR/resmi terdaftar)" if is_correct else " (SALAH/typo)"
            detail_parts.append(f'ISSN "{issn_v}"{marker} ditemukan pada: {label_list}')
        
        cross_page_msg = (
            f'Inkonsistensi dan kesalahan penulisan nomor ISSN antar-halaman (terdeteksi otomatis dari pemindaian lintas halaman): '
            + '; '.join(detail_parts) + '. '
        )
        if correct_issn:
            cross_page_msg += (
                f'Koreksi seharusnya: Selaraskan seluruh halaman menggunakan nomor ISSN resmi terdaftar '
                f'"ISSN {correct_issn}" (tanpa tanda titik dua).'
            )
        if cat_idx >= 0 and cross_page_msg not in halaman_katalog:
            halaman_katalog.insert(0, cross_page_msg)
        elif cross_page_msg not in kover_depan:
            kover_depan.insert(0, cross_page_msg)

    # ── REGISTRY MISMATCH (Bangkep Specific) ──
    if meta.get("issn_registry_mismatch"):
        rm = meta["issn_registry_mismatch"]
        rm_found = rm["found"]
        rm_correct = rm["correct"]
        rm_pages = rm.get("pages", [])
        if not rm_pages:
            rm_pages = [cat_idx] if cat_idx >= 0 else [0]
            
        already_in_checksum = any(item.get("issn") == rm_found for item in meta.get("issn_checksum_invalid", []))
        if not already_in_checksum:
            reg_err_msg = (
                f'Nomor ISSN "{rm_found}" tidak sesuai dengan registri resmi BPS untuk {level_id} {region} '
                f'(nomor ISSN resmi terdaftar adalah "{rm_correct}"). Terdapat saltik/typo digit angka tertukar. '
                f'Koreksi seharusnya: Selaraskan menjadi "ISSN {rm_correct}" tanpa tanda titik dua.'
            )
            
            if 0 in rm_pages and reg_err_msg not in kover_depan:
                kover_depan.insert(0, reg_err_msg)
            if cat_idx in rm_pages and cat_idx >= 0 and reg_err_msg not in halaman_katalog:
                halaman_katalog.insert(0, reg_err_msg)
            if team_idx in rm_pages and team_idx >= 0 and reg_err_msg not in tim_penyusun:
                halaman_team_msg = f'Nomor ISSN pada Halaman Tim Penyusun tertulis "{rm_found}" (saltik). Nomor resmi terdaftar adalah "{rm_correct}". Selaraskan menjadi "ISSN {rm_correct}".'
                tim_penyusun.insert(0, halaman_team_msg)
            if hju_idx in rm_pages and hju_idx >= 0 and reg_err_msg not in halaman_judul:
                halaman_judul.insert(0, reg_err_msg)
            if toc_idx in rm_pages and toc_idx >= 0 and reg_err_msg not in daftar_isi:
                daftar_isi.insert(0, f'Nomor ISSN pada Halaman Daftar Isi tertulis "{rm_found}" (saltik). Selaraskan menjadi "ISSN {rm_correct}".')

    # ── VALIDASI MATEMATIKA ALGORITMA ISO 3297 CHECKSUM / BRIN (BERLAKU SE-INDONESIA) ──
    for bad_item in meta.get("issn_checksum_invalid", []):
        bad_issn = bad_item["issn"]
        exp_char = bad_item["expected_check_digit"]
        bad_pages = bad_item.get("pages", [])
        if not bad_pages:
            bad_pages = [cat_idx] if cat_idx >= 0 else [0]
        
        chk_msg = (
            f'Nomor ISSN "{bad_issn}" terdeteksi TIDAK VALID berdasarkan standar internasional ISO 3297 / registrasi BRIN '
            f'(Checksum Modulo 11 gagal; digit verifikasi ke-8 seharusnya "{exp_char}"). '
            f'Hal ini membuktikan secara matematis adanya saltik (typo) atau digit angka tertukar pada nomor ISSN tersebut. '
            + (f'Nomor resmi terdaftar untuk {level_id} {region} adalah "{correct_issn}". ' if correct_issn else '')
            + f'Mohon periksa kembali SK penerbitan ISSN resmi dari BRIN.'
        )
        
        # Attribute strictly to pages where bad_issn was found:
        if 0 in bad_pages and chk_msg not in kover_depan:
            kover_depan.insert(0, chk_msg)
        if cat_idx in bad_pages and cat_idx >= 0 and chk_msg not in halaman_katalog:
            halaman_katalog.insert(0, chk_msg)
        if team_idx in bad_pages and team_idx >= 0:
            team_chk_short = (
                f'Nomor ISSN "{bad_issn}" pada Halaman Tim Penyusun terdeteksi TIDAK VALID berdasarkan ISO 3297 (Checksum Modulo 11 gagal). '
                + (f'Ganti dengan nomor resmi "ISSN {correct_issn}".' if correct_issn else 'Perbaiki nomor ISSN resmi.')
            )
            if team_chk_short not in tim_penyusun:
                tim_penyusun.insert(0, team_chk_short)
        if hju_idx in bad_pages and hju_idx >= 0 and chk_msg not in halaman_judul:
            halaman_judul.insert(0, chk_msg)
        if toc_idx in bad_pages and toc_idx >= 0:
            toc_chk_short = f'Nomor ISSN "{bad_issn}" pada Daftar Isi tidak valid (Checksum Modulo 11 gagal). Selaraskan dengan nomor resmi.'
            if toc_chk_short not in daftar_isi:
                daftar_isi.insert(0, toc_chk_short)

    # ── WRONG YEAR REFERENCES ──
    wrong_yr_refs = meta.get("wrong_year_refs", [])
    if wrong_yr_refs:
        preface_wrong = [r for r in wrong_yr_refs if r[0] <= 15]
        body_wrong = [r for r in wrong_yr_refs if r[0] > 15]
        
        if preface_wrong:
            yr_details = "; ".join([f'Halaman {r[1]}: tertulis "{r[2]}" (seharusnya tahun {r[3]})' for r in preface_wrong[:5]])
            kata_pengantar.append(
                f'Referensi tahun salah terdeteksi otomatis pada halaman pendahuluan: {yr_details}.'
            )
        if body_wrong:
            yr_details = "; ".join([f'Halaman {r[1]}: tertulis "{r[2]}"' for r in body_wrong[:5]])
            layout_isi.append(
                f'Referensi tahun salah terdeteksi otomatis pada batang tubuh: {yr_details}. '
                f'Seluruh referensi tahun wajib diselaraskan ke tahun {year}.'
            )

    # ── GLOBAL TYPO FINDINGS ──
    g_typos = meta.get("global_typos", [])
    if g_typos:
        unique_typos = {}
        for pg, wrong, correct in g_typos:
            key = f"{wrong}->{correct}"
            if key not in unique_typos:
                unique_typos[key] = {"wrong": wrong, "correct": correct, "pages": []}
            unique_typos[key]["pages"].append(pg)
        
        for key, info in unique_typos.items():
            pg_list = ", ".join(info["pages"][:5])
            more = f' (dan {len(info["pages"])-5} halaman lainnya)' if len(info["pages"]) > 5 else ''
            typo_msg = (
                f'Saltik terdeteksi otomatis pada halaman {pg_list}{more}: '
                f'Tertulis "{info["wrong"]}", penulisan yang benar adalah "{info["correct"]}".'
            )
            if not any(info["wrong"] in x for x in layout_isi):
                layout_isi.append(typo_msg)

    # ── ROMAN NUMERAL PAGE MISMATCH ──
    if meta.get("roman_page_mismatch"):
        rom_str, rom_int, expected_count = meta["roman_page_mismatch"]
        def _to_roman_uncached(n):
            val = [1000, 900, 500, 400, 100, 90, 50, 40, 10, 9, 5, 4, 1]
            syb = ["m", "cm", "d", "cd", "c", "xc", "l", "xl", "x", "ix", "v", "iv", "i"]
            r = ''
            i = 0
            while n > 0:
                for _ in range(n // val[i]):
                    r += syb[i]
                    n -= val[i]
                i += 1
            return r
        expected_rom_str = _to_roman_uncached(expected_count)
        halaman_katalog.append(
            f'Kesalahan jumlah halaman romawi pada Halaman Katalog: Tertulis "{rom_str}" '
            f'({rom_int} halaman), padahal urutan halaman romawi riil pada bagian pendahuluan '
            f'(termasuk halaman kosong/pembatas tanpa footer sesuai pedoman baku) adalah {expected_count} halaman ({expected_rom_str}). '
            f'Jumlah halaman romawi pada "Jumlah Halaman/Number of Pages" wajib disesuaikan menjadi "{expected_rom_str}".'
        )

    # ── DISTRICT IDENTITY MISMATCH (Indikasi Kasus Tolitoli: Hanya Ganti Kover) ──
    if meta.get("district_mismatch_info", {}).get("is_mismatch"):
        d_info = meta["district_mismatch_info"]
        cov_raw = str(d_info.get("cover_district", region)).strip()
        cov_clean = re.sub(r'^\s*kecamatan\s+', '', cov_raw, flags=re.I).strip()
        cov_d = f"Kecamatan {cov_clean}" if cov_clean else cov_raw

        inner_raw = str(d_info.get("dominant_inner_district") or d_info.get("catalog_district") or "Kecamatan Lain").strip()
        inner_clean = re.sub(r'^\s*kecamatan\s+', '', inner_raw, flags=re.I).strip()
        inner_d = f"Kecamatan {inner_clean}" if inner_clean else inner_raw
        r_details = " | ".join(d_info.get("reasons", []))
        
        kover_depan.insert(0,
            f'[FATAL KETIDAKSESUAIAN WILAYAH] Indikasi kelalaian fatal hanya mengganti kover (Copy-Paste dari publikasi lain): '
            f'Kover depan memuat "{cov_d}", namun isi dokumen merupakan publikasi "{inner_d}". '
            f'Rincian: {r_details}. Wajib mengganti seluruh isi dokumen dengan data dan naskah asli {cov_d}.'
        )
        halaman_judul.insert(0,
            f'[FATAL KETIDAKSESUAIAN WILAYAH] Judul pada Halaman Judul Utama tidak selaras dengan kover depan: '
            f'Terdeteksi identitas publikasi "{inner_d}", berbeda dengan kover depan ("{cov_d}").'
        )
        halaman_katalog.insert(0,
            f'[FATAL KETIDAKSESUAIAN WILAYAH] Identitas publikasi pada Halaman Katalog keliru: '
            f'Dokumen katalog mencantumkan atau terhubung dengan "{inner_d}", bukan "{cov_d}".'
        )
        kata_pengantar.insert(0,
            f'[FATAL KETIDAKSESUAIAN WILAYAH] Narasi Kata Pengantar menyebut wilayah yang salah: '
            f'Paragraf teks pengantar menyebut "{inner_d}", padahal buku ini adalah publikasi "{cov_d}".'
        )
        layout_isi.insert(0,
            f'[FATAL KETIDAKSESUAIAN WILAYAH] Batang Tubuh & Narasi Salah Wilayah: '
            f'Ulasan geografi Bab 1, nama desa, running title, dan data tabel memuat identitas "{inner_d}". '
            f'Publikasi dilarang dirilis dengan data kecamatan yang tertukar.'
        )

    # ── RAW TEMPLATE & UNWORKED DRAFT OVERLAY (Kasus Tidak Niat Mengerjakan) ──
    raw_tpl = meta.get("raw_template_info", {})
    if raw_tpl.get("is_pure_template"):
        m_list = "; ".join(raw_tpl.get("markers", [])[:7])
        m_cnt = raw_tpl.get("markers_count", 0)
        rejection_msg = (
            f'[DITOLAK TOTAL - HANYA UPLOAD TEMPLATE MASTER MENTAH] Dokumen ini terdeteksi 100% sebagai Master Template BPS Pusat '
            f'(Template KCDA 2026) yang belum dikerjakan sama sekali / tidak diisi substansi riil kecamatan! '
            f'Terdeteksi {m_cnt} residu template master bawaan: {m_list}. '
            f'Publikasi ini DITOLAK SEPENUHNYA (REJECTED) dan WAJIB dikerjakan ulang dari awal dengan menyisipkan data dan naskah resmi daerah.'
        )
        kover_depan.insert(0, rejection_msg)
        halaman_judul.insert(0, rejection_msg)
        halaman_katalog.insert(0, rejection_msg)
        tim_penyusun.insert(0, rejection_msg)
        kata_pengantar.insert(0, rejection_msg)
        daftar_isi.insert(0, rejection_msg)
        layout_isi.insert(0, rejection_msg)
        kover_belakang.insert(0, rejection_msg)
    elif raw_tpl.get("is_raw_template"):
        m_list = "; ".join(raw_tpl.get("markers", [])[:5])
        m_cnt = raw_tpl.get("markers_count", 0)
        draft_msg = (
            f'[PERINGATAN GLOBAL DOKUMEN - RESIDU TEMPLATE MASTER] Dokumen masih memuat teks bawaan master template BPS '
            f'yang belum diganti/dihapus pada naskah. Terdeteksi {m_cnt} residu template master: {m_list}. '
            f'Publikasi wajib dibersihkan dari teks dummy master template sebelum dapat dirilis resmi.'
        )
        kover_depan.insert(0, draft_msg)
        halaman_judul.insert(0, draft_msg)
        halaman_katalog.insert(0, draft_msg)
        tim_penyusun.insert(0, draft_msg)
        kata_pengantar.insert(0, draft_msg)
        layout_isi.insert(0, draft_msg)
    elif raw_tpl.get("markers"):
        # Residu terisolasi / minor (misal: layer tersembunyi HJU atau running header tersisa):
        # Hanya dimasukkan sebagai catatan revisi di halaman yang bersangkutan (tidak mengotori halaman lain)
        n_p = meta.get("num_pages", 0)
        for m in raw_tpl.get("markers", []):
            m_low = m.lower()
            res_item = f'[CATATAN REVISI - RESIDU TEKS TEMPLATE] {m}. Mohon periksa dan bersihkan pada file sumber.'
            if 'hju' in m_low or 'hal. 3' in m_low or 'xxxx' in m_low:
                if not (meta.get("p3_has_bg_illustration") or meta.get("p3_has_image")):
                    if not any(m[:25].lower() in x.lower() for x in halaman_judul):
                        halaman_judul.append(res_item)
            if 'daftar pustaka' in m_low or ('yyyyy' in m_low and any(f"hal. {p}" in m_low for p in range(max(1, n_p - 15), n_p + 1))):
                if not any(m[:25].lower() in x.lower() for x in daftar_pustaka):
                    daftar_pustaka.append(res_item)
            elif 'kover depan' in m_low or 'hal. 1' in m_low:
                pass  # Residu teks master tidak kasat mata pada kover depan diabaikan
            elif 'kover belakang' in m_low:
                if not any(m[:25].lower() in x.lower() for x in kover_belakang):
                    kover_belakang.append(res_item)
            elif 'tim penyusun' in m_low:
                if not any(m[:25].lower() in x.lower() for x in tim_penyusun):
                    tim_penyusun.append(res_item)
            elif 'kata pengantar' in m_low:
                if not any(m[:25].lower() in x.lower() for x in kata_pengantar):
                    kata_pengantar.append(res_item)
            elif 'katalog' in m_low:
                if not any(m[:25].lower() in x.lower() for x in halaman_katalog):
                    halaman_katalog.append(res_item)

    # ── PENGGABUNGAN TEMUAN HASIL INSPEKSI COMPUTER VISION TINGKAT TINGGI ──
    cv_audit = meta.get("cv_audit", {})
    if cv_audit:
        for d in cv_audit.get("cover_visual", {}).get("defects", []):
            if not any(d[:35].lower() in x.lower() for x in kover_depan):
                kover_depan.append(d)
        for d in cv_audit.get("hju_visual", {}).get("defects", []):
            if not any(d[:35].lower() in x.lower() for x in halaman_judul):
                halaman_judul.append(d)
        for d in cv_audit.get("preface_visual", {}).get("defects", []):
            if not any(d[:35].lower() in x.lower() for x in kata_pengantar):
                kata_pengantar.append(d)
        for d in cv_audit.get("tables_figures_visual", {}).get("defects", []):
            if not any(d[:35].lower() in x.lower() for x in layout_isi):
                layout_isi.append(d)
        for d in cv_audit.get("back_cover_visual", {}).get("defects", []):
            if not any(d[:35].lower() in x.lower() for x in kover_belakang):
                kover_belakang.append(d)

    # ── SARAN ESTETIKA, TATA LETAK VISUAL & PRAKTIK TERBAIK BPS (Disarikan dari Pedoman 2023 & Evaluasi 7206) ──
    # Catatan: Saran estetika hanya disertakan jika terdeteksi indikasi/masalah relevan pada bagian tersebut,
    # sehingga publikasi yang sudah rapi dan benar tidak terkena penambahan defect secara artifisial.
    sug = get_aesthetic_and_standard_suggestions()
    if (meta.get("preface_signature_missing") or meta.get("preface_has_toc_leak")) and meta.get("preface_idx", -1) >= 0:
        if not any("TANDA TANGAN PEJABAT" in x for x in kata_pengantar):
            kata_pengantar.append(sug["ruang_ttd"])
    if any("FOTO" in x.upper() for x in kata_pengantar) and not any("FOTO PIMPINAN" in x for x in kata_pengantar):
        kata_pengantar.append(sug["foto_pimpinan"])

    if meta.get("table_findings") and not any("DATA TABEL STATISTIK" in x for x in layout_isi):
        layout_isi.append(sug["tabel_estetika"])

    if (kover_belakang or meta.get("kover_belakang_errors")) and not any("ELEMEN KOVER BELAKANG" in x for x in kover_belakang):
        kover_belakang.append(sug["kover_belakang"])

