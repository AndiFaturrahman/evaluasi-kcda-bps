"""
Modul Ekstraksi Mendalam PDF Publikasi BPS (Phase 1)
Memindai struktur fisik halaman, layer teks, metadata katalog, gambar dummy,
tanda tangan pengantar, barcode, dan konsistensi lintas halaman.
"""
import os
import sys
import re
import json
import copy
import fitz
from collections import defaultdict, Counter

from .common import (
    HAVE_CV2, cv_auditor, JABATAN_SALAH_JAMAK, KNOWN_BANGKEP_ISSN,
    KECAMATAN_TO_KABUPATEN, URL_SUBDOMAIN_TO_KABUPATEN, ALL_REGENCIES_MAP,
    DUPLICATE_KECAMATAN_MAP, WILAYAH_METADATA, detect_kabupaten_name,
    find_page_with_text, validate_issn_checksum, scan_cover_raster_header
)

if HAVE_CV2:
    import cv2
    import numpy as np

def verify_label_slash_space(catalog_raw, label_id, label_en):
    """
    Memverifikasi apakah terdapat spasi riil sebelum atau sesudah garis miring '/'
    pada label dwibahasa katalog (misal: 'Jumlah Halaman/Number of Pages').
    Mencegah false positive akibat kerning antar-font (regular vs italic) yang diinterpretasikan
    oleh PyMuPDF layout reconstructor sebagai karakter spasi sintetis.
    
    Returns:
        (has_space_before: bool, has_space_after: bool)
    """
    if not catalog_raw:
        return True, True

    all_spans = []
    for b in catalog_raw.get("blocks", []):
        for l in b.get("lines", []):
            for s in l.get("spans", []):
                all_spans.append(s)

    target_slash = None
    target_idx = None
    target_c_idx = None

    for idx, s in enumerate(all_spans):
        chars = s.get("chars", [])
        span_text = "".join(c["c"] for c in chars)
        if "/" in span_text:
            is_match = False
            if label_id.lower() in span_text.lower():
                is_match = True
            elif idx > 0 and label_id.lower() in "".join(c["c"] for c in all_spans[idx - 1].get("chars", [])).lower():
                is_match = True
            elif label_en.lower() in span_text.lower():
                is_match = True
            elif idx + 1 < len(all_spans) and label_en.lower() in "".join(c["c"] for c in all_spans[idx + 1].get("chars", [])).lower():
                is_match = True

            if is_match:
                for c_idx, c in enumerate(chars):
                    if c["c"] == "/":
                        target_slash = c
                        target_idx = idx
                        target_c_idx = c_idx
                        break
            if target_slash:
                break

    if not target_slash:
        return False, False

    s = all_spans[target_idx]
    chars = s.get("chars", [])

    # 1. Cek spasi sebelum tanda slash '/'
    has_space_before = False
    if target_c_idx > 0:
        prev_c = chars[target_c_idx - 1]
        has_space_before = prev_c["c"] in (" ", "\t", "\xa0")
    elif target_idx > 0:
        prev_s = all_spans[target_idx - 1]
        prev_chars = prev_s.get("chars", [])
        if prev_chars:
            last_c = prev_chars[-1]
            if last_c["c"] in (" ", "\t", "\xa0"):
                has_space_before = True
            else:
                dx = target_slash["bbox"][0] - last_c["bbox"][2]
                has_space_before = (dx >= 2.8)

    # 2. Cek spasi sesudah tanda slash '/'
    has_space_after = False
    if target_c_idx + 1 < len(chars):
        next_c = chars[target_c_idx + 1]
        has_space_after = next_c["c"] in (" ", "\t", "\xa0")
    elif target_idx + 1 < len(all_spans):
        next_s = all_spans[target_idx + 1]
        next_chars = next_s.get("chars", [])
        if next_chars:
            first_c = next_chars[0]
            if first_c["c"] in (" ", "\t", "\xa0"):
                has_space_after = True
            else:
                dx = first_c["bbox"][0] - target_slash["bbox"][2]
                has_space_after = (dx >= 2.8)

    return has_space_before, has_space_after

def extract_pdf_metadata(pdf_path):
    doc = fitz.open(pdf_path)
    num_pages = len(doc)
    
    pages_text = {}
    pages_lines = {}
    for i in range(num_pages):
        txt = doc[i].get_text("text")
        pages_text[i] = txt
        pages_lines[i] = [l.strip() for l in txt.split("\n") if l.strip()]

    # 1. Locate key sections
    catalog_idx = find_page_with_text(doc, "Jumlah Halaman", "Ukuran Buku", start_page=2, end_page=15)
    if catalog_idx < 0:
        catalog_idx = find_page_with_text(doc, "Katalog", "Ukuran Buku", start_page=2, end_page=15)
    if catalog_idx < 0:
        catalog_idx = find_page_with_text(doc, "Katalog", "ISSN", start_page=2, end_page=15)

    # Deteksi presisi Halaman Judul Utama (HJU)
    # HJU (Title Page) WAJIB berada SEBELUM Halaman Katalog (p_cand < catalog_idx).
    hju_idx = -1
    max_cand = catalog_idx if catalog_idx > 1 else min(4, num_pages)
    for p_cand in range(1, max_cand):
        c_txt = pages_text.get(p_cand, "").upper()
        if ("DALAM ANGKA" in c_txt or "IN FIGURES" in c_txt):
            if "BADAN PUSAT STATISTIK" in c_txt or "BPS" in c_txt or len(doc[p_cand].get_images()) >= 1:
                hju_idx = p_cand
                break
    # Fallback baku BPS: HJU selalu berada persis 1 lembar sebelum Halaman Katalog (biasanya hal fisik 3)
    if hju_idx == -1 and catalog_idx > 1:
        hju_idx = catalog_idx - 1
    elif hju_idx == -1 and num_pages > 2:
        hju_idx = 2

    team_idx = find_page_with_text(doc, "TIM PENYUSUN", end_page=12)
    preface_idx = find_page_with_text(doc, "KATA PENGANTAR", end_page=15)
    preface_en_idx = find_page_with_text(doc, "PREFACE", end_page=15)
    toc_idx = find_page_with_text(doc, "DAFTAR ISI", end_page=18)
    
    # Deteksi presisi halaman Daftar Tabel & Daftar Gambar (lewati lembar Daftar Isi agar tidak salah indeks)
    toc_table_idx = -1
    start_dt = (toc_idx + 1) if toc_idx >= 0 else 5
    for p_cand in range(start_dt, min(start_dt + 15, num_pages)):
        cand_txt = pages_text.get(p_cand, "").upper()
        cand_lines = [l.strip().upper() for l in cand_txt.split('\n') if l.strip()]
        if any("DAFTAR TABEL" in l or "LIST OF TABLES" in l for l in cand_lines[:4]):
            toc_table_idx = p_cand
            break
        elif "DAFTAR TABEL" in cand_txt and "DAFTAR ISI" not in cand_txt:
            toc_table_idx = p_cand
            break

    toc_figure_idx = -1
    start_df = (toc_table_idx + 1) if toc_table_idx >= 0 else start_dt
    for p_cand in range(start_df, min(start_df + 15, num_pages)):
        cand_txt = pages_text.get(p_cand, "").upper()
        cand_lines = [l.strip().upper() for l in cand_txt.split('\n') if l.strip()]
        if any("DAFTAR GAMBAR" in l or "LIST OF FIGURES" in l for l in cand_lines[:4]):
            toc_figure_idx = p_cand
            break
        elif "DAFTAR GAMBAR" in cand_txt and "DAFTAR ISI" not in cand_txt:
            toc_figure_idx = p_cand
            break

    # Cek tanda titik setelah nomor tabel pada Daftar Tabel (Instrumen Row 83)
    toc_table_has_trailing_dot = False
    if toc_table_idx >= 0:
        tt_txt = pages_text.get(toc_table_idx, "")
        if re.search(r'(?:Tabel\s+)?\b[1-7]\.\d+\.\s+[A-Za-z]', tt_txt):
            toc_table_has_trailing_dot = True

    # Cek tanda titik setelah nomor gambar pada Daftar Gambar (Instrumen Row 92)
    toc_figure_has_trailing_dot = False
    if toc_figure_idx >= 0:
        tf_txt = pages_text.get(toc_figure_idx, "")
        if re.search(r'(?:Gambar\s+)?\b[1-7](?:\.\d+)?\.\s+[A-Za-z]', tf_txt):
            toc_figure_has_trailing_dot = True

    penjelasan_idx = find_page_with_text(doc, "PENJELASAN UMUM", end_page=25)
    penjelasan_has_rt = False
    if penjelasan_idx >= 0:
        p_lines = pages_lines.get(penjelasan_idx, [])
        if any("DALAM ANGKA" in l.upper() or "IN FIGURES" in l.upper() for l in p_lines[:3]):
            penjelasan_has_rt = True

    singkatan_idx = find_page_with_text(doc, "DAFTAR SINGKATAN", end_page=25)
    biblio_idx = find_page_with_text(doc, "DAFTAR PUSTAKA", start_page=max(0, num_pages - 15))
    glosarium_idx = find_page_with_text(doc, "GLOSARIUM", start_page=max(0, num_pages - 20))
    if glosarium_idx == -1:
        glosarium_idx = find_page_with_text(doc, "DAFTAR ISTILAH", start_page=max(0, num_pages - 20))
    indeks_idx = find_page_with_text(doc, "INDEKS", start_page=max(0, num_pages - 20))
    lampiran_idx = find_page_with_text(doc, "LAMPIRAN", start_page=max(0, num_pages - 25))

    # ── ATURAN PENEMPATAN HALAMAN GANJIL/GENAP (ODD/EVEN SECTION PLACEMENT RULES) ──
    # Sesuai Pedoman Pembuatan Publikasi BPS 2023 Bab 4.3 & Instrumen Pemeriksaan Publikasi
    hju_is_even = (hju_idx + 1) if (hju_idx >= 0 and (hju_idx + 1) % 2 == 0) else None
    catalog_is_odd = (catalog_idx + 1) if (catalog_idx >= 0 and (catalog_idx + 1) % 2 == 1) else None

    team_is_even = (team_idx + 1) if (team_idx >= 0 and (team_idx + 1) % 2 == 0) else None
    team_merged_with_catalog = (team_idx + 1) if (catalog_idx >= 0 and team_idx == catalog_idx) else None

    preface_is_even = (preface_idx + 1) if (preface_idx >= 0 and (preface_idx + 1) % 2 == 0) else None
    toc_is_even = (toc_idx + 1) if (toc_idx >= 0 and (toc_idx + 1) % 2 == 0) else None
    toc_table_is_even = (toc_table_idx + 1) if (toc_table_idx >= 0 and (toc_table_idx + 1) % 2 == 0) else None
    toc_figure_is_even = (toc_figure_idx + 1) if (toc_figure_idx >= 0 and (toc_figure_idx + 1) % 2 == 0) else None
    penjelasan_is_even = (penjelasan_idx + 1) if (penjelasan_idx >= 0 and (penjelasan_idx + 1) % 2 == 0) else None
    biblio_is_even = (biblio_idx + 1) if (biblio_idx >= 0 and (biblio_idx + 1) % 2 == 0) else None
    glosarium_is_even = (glosarium_idx + 1) if (glosarium_idx >= 0 and (glosarium_idx + 1) % 2 == 0) else None
    indeks_is_even = (indeks_idx + 1) if (indeks_idx >= 0 and (indeks_idx + 1) % 2 == 0) else None
    lampiran_is_even = (lampiran_idx + 1) if (lampiran_idx >= 0 and (lampiran_idx + 1) % 2 == 0) else None

    # Deteksi lembar pembatas bab yang diletakkan pada halaman genap
    divider_even_pages = []
    for p_div in range(15, num_pages - 4):
        txt_div_raw = re.sub(r'https?://\S+', '', pages_text.get(p_div, "")).strip()
        if len(doc[p_div].get_images()) >= 1 and len(txt_div_raw) < 50:
            if (p_div + 1) % 2 == 0:
                nxt_txt = (pages_text.get(p_div + 1, "") + " " + pages_text.get(p_div + 2, "")).upper()
                bm = re.search(r'BAB\s*(\d+)|(?:^|\n)([1-7])\.\d+', nxt_txt, re.I)
                b_num = bm.group(1) or bm.group(2) if bm else ""
                b_lbl = f"Bab {b_num}" if b_num else "bab"
                divider_even_pages.append((b_lbl, p_div + 1))

    all_prelim = " ".join([pages_text.get(i, "") for i in range(min(8, num_pages))])
    catalog_text = pages_text.get(catalog_idx, "") if catalog_idx >= 0 else ""
    team_text = pages_text.get(team_idx, "") if team_idx >= 0 else ""
    preface_text = pages_text.get(preface_idx, "") if preface_idx >= 0 else ""
    preface_en_text = pages_text.get(preface_en_idx, "") if preface_en_idx >= 0 else ""
    toc_text = pages_text.get(toc_idx, "") if toc_idx >= 0 else ""

    # Title & region
    title_match = re.search(r'(KECAMATAN\s+[A-Za-z\s]+|KABUPATEN\s+[A-Za-z\s]+|KOTA\s+[A-Za-z\s]+)\s+DALAM\s+ANGKA\s+(\d{4})',
                            all_prelim + pages_text.get(0, ""), re.IGNORECASE)
    pub_title = title_match.group(0).strip().title() if title_match else os.path.splitext(os.path.basename(pdf_path))[0].replace("-", " ").title()
    pub_year = title_match.group(2) if title_match else "2026"

    # Tentukan pub_level: 'kota', 'kabupaten', atau 'kecamatan'
    pub_level = "kecamatan"
    if re.search(r'\bKota\s+', pub_title, re.I):
        pub_level = "kota"
    elif re.search(r'\bKabupaten\s+', pub_title, re.I):
        pub_level = "kabupaten"

    is_kabupaten = (pub_level in ["kabupaten", "kota"])

    region_match = re.search(r'(?:Kecamatan|Kabupaten|Kota)\s+([A-Za-z\s]+?)\s+Dalam', pub_title, re.IGNORECASE)
    region_name = region_match.group(1).strip() if region_match else "Wilayah"
    if region_name.lower() in ["xxxxx", "wilayah", ""] or "xxxx" in region_name.lower():
        m_kat = re.search(r'(?:KECAMATAN|KABUPATEN|KOTA)\s+([A-Z\s]+?)\s+DALAM\s+ANGKA', catalog_text, re.I)
        if m_kat and "xxxx" not in m_kat.group(1).lower():
            region_name = m_kat.group(1).strip().title()
        else:
            m_fn = re.search(r'(?:kecamatan|kabupaten|kota)-([a-z\-]+)-dalam-angka', os.path.basename(pdf_path), re.I)
            if m_fn:
                region_name = m_fn.group(1).replace('-', ' ').title()
        if "Xxxxx" in pub_title or "xxxxx" in pub_title:
            prefix_lvl = "Kota" if pub_level == "kota" else "Kabupaten" if pub_level == "kabupaten" else "Kecamatan"
            pub_title = f"{prefix_lvl} {region_name} Dalam Angka {pub_year}"
    kabupaten_name = detect_kabupaten_name(pdf_path, pages_text, region_name, pub_title, is_kabupaten)
    is_bangkep = bool(re.search(r'banggai\s+kepulauan|bangkep', (kabupaten_name or ""), re.I))

    # ── KOVER DEPAN ──
    cover_text = pages_text.get(0, "")
    m_cov_col = re.search(r'ISSN\s*:\s*\d{4}[-\u2013]\d{3}[\dX]|ISSN\s*:\s*\d{4}', cover_text)
    cover_issn_text = m_cov_col.group(0).strip() if m_cov_col else None
    cover_has_colon = bool(m_cov_col)
    cover_has_issn = bool(re.search(r'ISSN', cover_text, re.IGNORECASE))
    # Residu format master tidak kasat mata (tersembunyi di balik kover) diabaikan
    cover_has_template_leak = False
    cover_has_letter_a = False

    # Deteksi kebocoran placeholder / draft template pada Kover Depan
    cover_issn_placeholder = bool(re.search(r'XXXX\s*-\s*XXXX|ISSN\s+XXXX', cover_text, re.I)) or (cover_has_issn and not bool(re.search(r'ISSN\s*[:/]?\s*\d{4}[-\u2013]\d{3}[\dX]', cover_text, re.I)))
    cover_catalog_placeholder = bool(re.search(r'1102001\.\s*xxxx|\.xxxx\b', cover_text, re.I))
    cover_volume_placeholder = bool(re.search(r'Volume\s+(?:XX|xx|\.\.\.)', cover_text))
    cover_agency_dual_option = bool(re.search(r'KABUPATEN/KOTA', cover_text) or re.search(r'REGENCY/MUNICIPALITY', cover_text))

    # Pemindaian raster OpenCV untuk kover depan
    cover_raster_info = {"has_issn": False, "has_colon": False, "catalog_space_colon": False}
    if HAVE_CV2 and num_pages > 0:
        cover_raster_info = scan_cover_raster_header(doc[0])
        if cover_raster_info["has_colon"]:
            cover_has_colon = True
        if cover_raster_info["has_issn"]:
            cover_has_issn = True

    cover_catalog_space_colon = cover_raster_info.get("catalog_space_colon", False)
    cover_has_english_title = bool(re.search(r'IN\s+FIGURES', cover_text, re.I))
    cover_title_is_italic = True
    if cv_auditor and num_pages > 0:
        try:
            has_en, is_it = cv_auditor.check_title_english(doc[0])
            if has_en:
                cover_has_english_title = True
                cover_title_is_italic = is_it
            elif not cover_has_english_title:
                cover_title_is_italic = True
        except Exception:
            pass

    # Cek posisi klaster nomor katalog & ISSN pada Kover Depan (wajib pojok kanan atas)
    cover_catalog_pos_wrong = None
    cover_katalog_issn_order_wrong = False
    if num_pages > 0:
        pw_cov, ph_cov = doc[0].rect.width, doc[0].rect.height
        y_kat_cov = None
        y_issn_cov = None
        for b in doc[0].get_text('blocks'):
            txt_b = b[4].upper()
            if 'KATALOG' in txt_b or 'CATALOGUE' in txt_b:
                y_kat_cov = (b[1] + b[3]) / 2.0
            if 'ISSN' in txt_b and 'BARCODE' not in txt_b:
                y_issn_cov = (b[1] + b[3]) / 2.0
            if 'KATALOG' in txt_b or 'CATALOGUE' in txt_b or ('ISSN' in txt_b and 'BARCODE' not in txt_b):
                if (b[1] + b[3]) / 2.0 < ph_cov * 0.30 and (b[0] + b[2]) / 2.0 < pw_cov * 0.40:
                    cover_catalog_pos_wrong = "kiri"
        if y_kat_cov is not None and y_issn_cov is not None and y_issn_cov < y_kat_cov and abs(y_kat_cov - y_issn_cov) > 5:
            cover_katalog_issn_order_wrong = True

    # Deteksi pencantuman kata 'Tahun' pada judul buku kover depan (Instrumen Row 8)
    cover_title_has_tahun_word = bool(
        re.search(r'Dalam\s+Angka\s+Tahun\s+\d{4}', cover_text, re.I)
        or re.search(r'In\s+Figures\s+Year\s+\d{4}', cover_text, re.I)
    )

    # ── HALAMAN KOSONG SETELAH KOVER DEPAN (Halaman fisik 2) ──
    p2_lines = pages_lines.get(1, [])
    # Abaikan watermark web portal BPS (https://...bps.go.id), hanya deteksi kebocoran riil
    p2_content_lines = [l for l in p2_lines if "bps.go.id" not in l.lower()]
    p2_has_leak = any(l.isdigit() or "DALAM ANGKA" in l.upper() or "KATA PENGANTAR" in l.upper() for l in p2_content_lines)

    # ── HALAMAN JUDUL UTAMA (HJU) ──
    actual_hju_p = hju_idx if hju_idx >= 0 else (2 if num_pages > 2 else -1)
    p3_images = doc[actual_hju_p].get_images() if (actual_hju_p >= 0 and actual_hju_p < num_pages) else []
    p3_has_image = False
    p3_logo_monochrome = False
    if actual_hju_p >= 0 and actual_hju_p < num_pages:
        # 1. Cek apakah ada raster image besar (foto pemandangan/kover depan) pada HJU
        has_large_raster = False
        try:
            for img_info in doc[actual_hju_p].get_images():
                base_img = doc.extract_image(img_info[0])
                if base_img and (base_img.get("width", 0) > 350 and base_img.get("height", 0) > 350):
                    has_large_raster = True
                    break
        except Exception:
            pass

        # 2. Cek rasio keputihan latar belakang (foto pemandangan kover depan memiliki non_white_ratio > 45%)
        has_dense_bg = False
        try:
            pix = doc[actual_hju_p].get_pixmap(dpi=100)
            img = cv2.imdecode(np.frombuffer(pix.tobytes("png"), np.uint8), cv2.IMREAD_COLOR)
            if img is not None:
                h, w, _ = img.shape
                center = img[int(h * 0.35):int(h * 0.65), int(w * 0.20):int(w * 0.80)]
                center_hsv = cv2.cvtColor(center, cv2.COLOR_BGR2HSV)
                non_white_mask = ~((center_hsv[:, :, 1] < 20) & (center_hsv[:, :, 2] > 235))
                non_white_ratio = float(np.sum(non_white_mask) / non_white_mask.size)
                if non_white_ratio > 0.45:
                    has_dense_bg = True
        except Exception:
            pass

        if has_large_raster or has_dense_bg:
            p3_has_image = True
    p3_text_full = pages_text.get(actual_hju_p, "") if (actual_hju_p >= 0 and actual_hju_p < num_pages) else ""
    p3_has_issn = bool(re.search(r'ISSN', p3_text_full, re.IGNORECASE))
    m_p3_col = re.search(r'ISSN\s*:\s*\d{4}[-\u2013]\d{3}[\dX]|ISSN\s*:\s*\d{4}', p3_text_full)
    p3_issn_text = m_p3_col.group(0).strip() if m_p3_col else None
    p3_issn_has_colon = bool(m_p3_col)
    p3_is_template = bool(re.search(r'xxxx|XXXX|Volume\s+(?:XX|xx)|KABUPATEN/KOTA|REGENCY/MUNICIPALITY', p3_text_full))
    p3_typo_kecamatan = bool(re.search(r'KECAMATA\s+N\b', p3_text_full))

    # Pemindaian raster OpenCV untuk Halaman Judul Utama
    hju_raster_info = {"has_issn": False, "has_colon": False, "catalog_space_colon": False}
    if HAVE_CV2 and actual_hju_p >= 0 and actual_hju_p < num_pages:
        hju_raster_info = scan_cover_raster_header(doc[actual_hju_p])
        if hju_raster_info["has_colon"]:
            p3_issn_has_colon = True
        if hju_raster_info["has_issn"]:
            p3_has_issn = True

    hju_catalog_space_colon = hju_raster_info.get("catalog_space_colon", False)
    hju_has_english_title = bool(re.search(r'IN\s+FIGURES', p3_text_full, re.I))
    hju_title_is_italic = True
    if cv_auditor and actual_hju_p >= 0 and actual_hju_p < num_pages:
        try:
            has_en, is_it = cv_auditor.check_title_english(doc[actual_hju_p])
            if has_en:
                hju_has_english_title = True
                hju_title_is_italic = is_it
            elif not hju_has_english_title:
                hju_title_is_italic = True
        except Exception:
            pass

    # Cek posisi klaster nomor katalog & ISSN pada HJU (wajib pojok kanan atas)
    hju_catalog_pos_wrong = None
    hju_katalog_issn_order_wrong = False
    if actual_hju_p >= 0 and actual_hju_p < num_pages:
        pw_hju, ph_hju = doc[actual_hju_p].rect.width, doc[actual_hju_p].rect.height
        y_kat_h = None
        y_issn_h = None
        for b in doc[actual_hju_p].get_text('blocks'):
            txt_b = b[4].upper()
            if 'KATALOG' in txt_b or 'CATALOGUE' in txt_b:
                y_kat_h = (b[1] + b[3]) / 2.0
            if 'ISSN' in txt_b and 'BARCODE' not in txt_b:
                y_issn_h = (b[1] + b[3]) / 2.0
            if 'KATALOG' in txt_b or 'CATALOGUE' in txt_b or ('ISSN' in txt_b and 'BARCODE' not in txt_b):
                if (b[1] + b[3]) / 2.0 < ph_hju * 0.30 and (b[0] + b[2]) / 2.0 < pw_hju * 0.40:
                    hju_catalog_pos_wrong = "kiri"
        if y_kat_h is not None and y_issn_h is not None and y_issn_h < y_kat_h and abs(y_kat_h - y_issn_h) > 5:
            hju_katalog_issn_order_wrong = True

    # Deteksi running title atau nomor halaman fisik pada HJU (hanya pada header y <= 8% atau footer y >= 93%)
    p3_has_rt = False
    if actual_hju_p >= 0 and actual_hju_p < num_pages:
        hju_page = doc[actual_hju_p]
        pw_hju = hju_page.rect.width
        ph_hju = hju_page.rect.height
        for b in hju_page.get_text("blocks"):
            x0, y0, x1, y1, text, block_no, block_type = b
            txt_clean = text.strip()
            if not txt_clean or "bps.go.id" in txt_clean.lower():
                continue
            # Abaikan klaster nomor katalog & ISSN di pojok kanan atas
            if y0 < ph_hju * 0.25 and x0 > pw_hju * 0.40:
                continue
            # Running title pada header atas di luar klaster katalog
            if y1 <= ph_hju * 0.08:
                p3_has_rt = True
                break
            # Nomor halaman atau running title pada margin footer bawah
            if y0 >= ph_hju * 0.93:
                lines_footer = [l.strip() for l in txt_clean.splitlines() if l.strip()]
                for lf in lines_footer:
                    if re.match(r'^(?:-?\s*\d+\s*-?|-?\s*[ivxlcdm]+\s*-?|halaman\s+\d+|hal\.?\s*\d+)$', lf, re.I):
                        p3_has_rt = True
                        break
                    if "DALAM ANGKA" in lf.upper() or "IN FIGURES" in lf.upper():
                        p3_has_rt = True
                        break
                if p3_has_rt:
                    break

    # ── HALAMAN KATALOG ──
    catalog_raw = None
    if catalog_idx is not None and 0 <= catalog_idx < num_pages:
        try:
            catalog_raw = doc[catalog_idx].get_text("rawdict")
        except Exception:
            catalog_raw = None

    cat_match = re.search(r'Katalog[^\n:]*:\s*([0-9][0-9\.\s-]{3,}[0-9])', catalog_text + " " + all_prelim, re.IGNORECASE)
    if not cat_match:
        cat_match = re.search(r'Katalog[^\d]*(\d{7,10}\.\d+|\d{4,10}(?:\.\d+)+)', catalog_text + " " + all_prelim, re.IGNORECASE)
    catalog_no = cat_match.group(1).strip() if cat_match else "-"
    if catalog_no != "-":
        digits_count = sum(c.isdigit() for c in catalog_no)
        if digits_count < 5:
            catalog_no = "-"
    catalog_slash = False
    if re.search(r'Katalog\s+/Catalogue', catalog_text + all_prelim):
        sb, _ = verify_label_slash_space(catalog_raw, "Katalog", "Catalogue")
        catalog_slash = sb

    catalog_volume_empty = bool(re.search(r'Volume\s+(?:xx|XX|\.\.\.)', catalog_text))
    catalog_no_empty = bool(re.search(r'Katalog[^\n:]*:\s*(?:\.{2,}|-|—|\s*$)', catalog_text)) or (catalog_no in ["-", "", "...."])
    catalog_issn_empty = bool(re.search(r'ISSN[^\n:]*:\s*(?:\.{2,}|XXXX|-)', catalog_text)) or bool(re.search(r'ISSN:\s*\.\.\.', catalog_text))
    catalog_pages_placeholder = bool(re.search(r'\.{2,}\s*[\+\-]\s*\.{2,}', catalog_text))
    catalog_illus_source_empty = bool(re.search(r'Sumber\s+Ilustrasi[^\n:]*:\s*(?:\.{2,}|\s*$)', catalog_text))
    catalog_agency_dual_option = bool(re.search(r'Kabupaten/Kota|Regency/Municipality', catalog_text, re.I))

    issn_match = re.search(r'ISSN\s*[:/]?\s*(\d{4}[-\u2013]\d{3}[\dX])', catalog_text + all_prelim, re.IGNORECASE)
    issn_val = issn_match.group(1).strip() if issn_match else "-"
    issn_val = issn_val.replace('\u2013', '-').replace('\u2014', '-')
    catalog_has_issn_line = bool(re.search(r'\bISSN\b', catalog_text))
    catalog_issn_has_colon = bool(re.search(r'\bISSN\s*:', catalog_text))
    catalog_issn_bilingual = bool(re.search(r'ISSN\s*/\s*ISSN', catalog_text, re.I))
    catalog_issn_format_ok = (catalog_issn_has_colon and not catalog_issn_bilingual) if catalog_has_issn_line else True
    is_serial = (
        "DALAM ANGKA" in cover_text.upper()
        or "IN FIGURES" in cover_text.upper()
        or catalog_no.startswith("1102001")
        or bool(re.search(r'Volume\s+(?:\d+|xx)', cover_text + " " + catalog_text, re.I))
    )

    pub_num_match = re.search(r'Nomor Publikasi[^\n]*:\s*([^\n]+)', catalog_text, re.IGNORECASE)
    pub_num = pub_num_match.group(1).strip() if pub_num_match else "-"
    pub_num_empty = pub_num in ["-", "", "\u2013", "\u2014"] or bool(re.search(r'Nomor\s+Publikasi[^\n:]*:\s*(?:\.{2,}|-|—)', catalog_text))

    pub_num_wrong_year = False
    pub_num_code_match = re.search(r'\d{5}\.(\d{2})\d+', pub_num)
    if pub_num_code_match:
        code_yr = pub_num_code_match.group(1)
        expected_code = pub_year[-2:]
        if code_yr != expected_code:
            pub_num_wrong_year = (code_yr, expected_code)

    bps_abbreviated_id = bool(re.search(r'\u00a9\s*BPS\b', catalog_text, re.IGNORECASE))
    catalog_bps_abbreviations = []
    for line in catalog_text.splitlines():
        line_clean = line.strip()
        if re.search(r'\bBPS\s+(?:Kabupaten|Kota|Provinsi)\b', line_clean) and 'BPS-Statistics' not in line_clean:
            catalog_bps_abbreviations.append(line_clean)
    bps_of_en = bool(re.search(r'BPS\s+of\s+', catalog_text + preface_en_text, re.IGNORECASE))
    copyright_typo_regency = bool(re.search(r'Regenency', catalog_text + all_prelim, re.I))

    roman_match = re.search(r'([ivxlcdmIVXLCDM]+)\s*[\+\-]\s*(\d+)\s*(halaman|hlm|hal\b)', catalog_text, re.IGNORECASE)
    catalog_roman = roman_match.group(1).lower() if roman_match else "-"
    catalog_arab = roman_match.group(2) if roman_match else "-"
    uses_hal_not_hlm = bool(roman_match and roman_match.group(3).lower() in ['hal', 'hlm'])
    space_before_slash_label_pages = False
    if re.search(r'Jumlah\s+Halaman\s+/Number', catalog_text, re.I):
        sb, _ = verify_label_slash_space(catalog_raw, "Jumlah Halaman", "Number of Pages")
        space_before_slash_label_pages = sb
    space_before_slash_unit_pages = bool(re.search(r'(?:halaman|hlm|hal)\s+/pages', catalog_text, re.I))
    space_before_slash_pages = space_before_slash_label_pages or space_before_slash_unit_pages
    # Diabaikan karena kerning font italic 'Number of Pages' sering menyisipkan spasi mikro di text layer
    space_before_colon_pages = False
    space_around_plus_pages = bool(re.search(r'([ivxlcdmIVXLCDM]+)\s+\+|\+\s+(\d+)', catalog_text))
    copyright_space_after_symbol = bool(re.search(r'©\s+[^\n]+', catalog_text))

    book_size_format_error = None
    m_bsize = re.search(r'(?:Ukuran\s+Buku|Book\s+Size)[^\n:]*:\s*([^\n]+)', catalog_text, re.I)
    if m_bsize:
        bsize_str = m_bsize.group(1).strip()
        if re.search(r'14\.8', bsize_str):
            book_size_format_error = f'Tertulis menggunakan tanda titik ("{bsize_str}"). Sesuai standar BPS (Instrumen baris 27), koma desimal wajib menggunakan tanda koma: "14,8 cm x 21 cm".'
        elif not re.search(r'14,8\s*cm\s*[x×]\s*21\s*cm', bsize_str, re.I) and not re.search(r'17,6\s*cm\s*[x×]\s*25\s*cm', bsize_str, re.I):
            book_size_format_error = f'Format penulisan dimensi tidak baku: Tertulis "{bsize_str}". Format baku BPS untuk publikasi buku A5 adalah "14,8 cm x 21 cm" (menggunakan spasi di sekitar tanda "x" dan spasi sebelum "cm").'

    # Cek sinkronisasi jumlah halaman katalog vs fisik
    catalog_pages_mismatch = None
    if catalog_roman != "-" and catalog_arab != "-":
        last_arab = 0
        for p in range(num_pages - 1, 20, -1):
            lines = pages_lines.get(p, [])
            if lines and lines[0].isdigit():
                last_arab = int(lines[0])
                break
        if last_arab > 0 and str(last_arab) != str(catalog_arab):
            catalog_pages_mismatch = (catalog_arab, last_arab)

    # ── VALIDASI JUMLAH HALAMAN ROMAWI HARUS GENAP (Instrumen Row 28 Poin 4) ──
    def _roman_to_int_val(s):
        r_dict = {'i': 1, 'v': 5, 'x': 10, 'l': 50, 'c': 100, 'd': 500, 'm': 1000}
        s_clean = s.lower().strip()
        val = 0
        for idx_c in range(len(s_clean)):
            if idx_c + 1 < len(s_clean) and r_dict.get(s_clean[idx_c], 0) < r_dict.get(s_clean[idx_c + 1], 0):
                val -= r_dict.get(s_clean[idx_c], 0)
            else:
                val += r_dict.get(s_clean[idx_c], 0)
        return val

    catalog_roman_is_odd = None
    if catalog_roman != "-":
        r_val = _roman_to_int_val(catalog_roman)
        if r_val > 0 and r_val % 2 == 1:
            catalog_roman_is_odd = (catalog_roman, r_val)

    # ── LARANGAN PENYINGKATAN NOMOR PUBLIKASI (Instrumen Row 26 Poin 5) ──
    catalog_pub_no_abbreviated = bool(
        re.search(r'\bNo\.?\s*Publikasi\b', catalog_text, re.I)
        or re.search(r'\bNo\.?\s*Publication\b', catalog_text, re.I)
    )

    # ── URUTAN PENOMORAN KATALOG, ISSN, NOMOR PUBLIKASI (Instrumen Row 26 Poin 2) ──
    catalog_numbering_order_wrong = False
    m_p_kat = re.search(r'\bKatalog\b', catalog_text, re.I)
    m_p_issn = re.search(r'\bISSN\b', catalog_text, re.I)
    m_p_pub = re.search(r'\bNomor\s+Publikasi\b', catalog_text, re.I)
    if m_p_kat and m_p_issn and m_p_pub:
        if not (m_p_kat.start() < m_p_issn.start() < m_p_pub.start()):
            catalog_numbering_order_wrong = True

    # Cek larangan nama individu pada Penyusun Naskah, Penyunting, dan Pembuat Kover (Instrumen Baris 29-31)
    catalog_individual_roles = []
    for role_pat, r_label in [
        (r'(?:Penyusun\s+Naskah|Manuscript\s+Drafter)[^\n:]*:\s*([^\n]+)', 'Penyusun Naskah'),
        (r'(?:Penyunting|Editor)[^\n:]*:\s*([^\n]+)', 'Penyunting'),
        (r'(?:Pembuat\s+Kover|Cover\s+Designer)[^\n:]*:\s*([^\n]+)', 'Pembuat Kover'),
    ]:
        m_r = re.search(role_pat, catalog_text, re.I)
        if m_r:
            v_r = m_r.group(1).strip()
            has_deg = bool(re.search(r'\b(?:S\.Si|S\.Tr\.Stat|S\.Stat|S\.E\.|M\.Si|M\.M\.|S\.Kom|Drs\.|Dra\.|Ir\.|Ph\.D)\b', v_r, re.I))
            is_bps_inst = bool(re.search(r'Badan\s+Pusat\s+Statistik|BPS|Statistics|Direktorat|Subdirektorat', v_r, re.I))
            if has_deg or (not is_bps_inst and 1 <= len(v_r.split()) <= 4 and not any(x in v_r for x in ['...', '---', 'XXX'])):
                catalog_individual_roles.append((r_label, v_r))

    # ── DETEKSI NAMA SATKER DWIBASAHA (BILINGUAL) & TIPOGRAFI ARIAL BOLD ITALIC ──
    cover_is_bilingual = (
        is_serial
        or bool(re.search(r'DISTRICT IN FIGURES', pages_text.get(0, "") + pages_text.get(2, ""), re.I))
        or bool(re.search(r'in Figures', all_prelim, re.I))
        or "INDONESIA DAN INGGRIS" in catalog_text.upper()
    )
    comb_cov_txt = pages_text.get(0, "") + "\n" + pages_text.get(2, "")
    has_bps_id = bool(re.search(r'BADAN PUSAT STATISTIK', comb_cov_txt, re.I))
    has_bps_en = bool(re.search(r'BPS-STATISTICS|STATISTICS\s+[A-Z\s]+(?:REGENCY|MUNICIPALITY)', comb_cov_txt, re.I))
    cover_publisher_not_bilingual = False
    if cover_is_bilingual:
        if has_bps_id and not has_bps_en:
            cover_publisher_not_bilingual = True
        elif not has_bps_en:
            cover_publisher_not_bilingual = True

    # ── DETEKSI FORMAT DWIBAHASA (BILINGUAL) PADA HALAMAN KATALOG ──
    catalog_has_english_title = bool(re.search(r'IN\s+FIGURES', catalog_text, re.I))
    catalog_bilingual_missing = []

    if is_serial or cover_is_bilingual:
        if not catalog_has_english_title:
            catalog_bilingual_missing.append('Judul Bahasa Inggris ("... District in Figures")')
        if re.search(r'\bKatalog\b', catalog_text, re.I) and not re.search(r'Catalogue', catalog_text, re.I):
            catalog_bilingual_missing.append('Katalog/Catalogue')
        if re.search(r'Nomor\s+Publikasi', catalog_text, re.I) and not re.search(r'Publication\s+Number', catalog_text, re.I):
            catalog_bilingual_missing.append('Nomor Publikasi/Publication Number')
        if re.search(r'Ukuran\s+Buku', catalog_text, re.I) and not re.search(r'Book\s+Size', catalog_text, re.I):
            catalog_bilingual_missing.append('Ukuran Buku/Book Size')
        if re.search(r'Jumlah\s+Halaman', catalog_text, re.I) and not re.search(r'Number\s+of\s+Pages', catalog_text, re.I):
            catalog_bilingual_missing.append('Jumlah Halaman/Number of Pages')
        if re.search(r'Jumlah\s+Halaman', catalog_text, re.I):
            m_pg = re.search(r'Jumlah\s+Halaman[^\n:]*:[^\n]+', catalog_text, re.I)
            if m_pg and not re.search(r'pages', m_pg.group(0), re.I):
                catalog_bilingual_missing.append('Satuan halaman ("... halaman/pages")')
        if re.search(r'Penyusun\s+Naskah', catalog_text, re.I) and not re.search(r'Manuscript\s+Drafter', catalog_text, re.I):
            catalog_bilingual_missing.append('Penyusun Naskah/Manuscript Drafter')
        if re.search(r'Penyunting', catalog_text, re.I) and not re.search(r'Editor', catalog_text, re.I):
            catalog_bilingual_missing.append('Penyunting/Editor')
        if re.search(r'Pembuat\s+Kover', catalog_text, re.I) and not re.search(r'Cover\s+Designer', catalog_text, re.I):
            catalog_bilingual_missing.append('Pembuat Kover/Cover Designer')
        if re.search(r'Penerbit', catalog_text, re.I) and not re.search(r'Publisher', catalog_text, re.I):
            catalog_bilingual_missing.append('Penerbit/Publisher')
        if re.search(r'Sumber\s+Ilustrasi', catalog_text, re.I) and not re.search(r'Illustration\s+Source', catalog_text, re.I):
            catalog_bilingual_missing.append('Sumber Ilustrasi/Illustration Source')
        has_cp_id = bool(re.search(r'Dilarang\s+mereproduksi|menggandakan', catalog_text, re.I))
        has_cp_en = bool(re.search(r'All\s+rights\s+reserved|commercial\s+purposes', catalog_text, re.I))
        if has_cp_id and not has_cp_en:
            catalog_bilingual_missing.append('Klausul Hak Cipta bahasa Inggris ("All rights reserved...")')

    cover_publisher_not_arial_bi = False
    try:
        p0_dict = doc[0].get_text("dict")
        for b in p0_dict.get("blocks", []):
            for l in b.get("lines", []):
                for s in l.get("spans", []):
                    st = s.get("text", "").strip()
                    if any(k in st.upper() for k in ["BADAN PUSAT STATISTIK", "STATISTICS"]):
                        fn = s.get("font", "").lower()
                        fl = s.get("flags", 0)
                        is_arial = "arial" in fn
                        is_bi = (fl & 2 != 0 and fl & 16 != 0) or ("bold" in fn and "italic" in fn) or "bi" in fn
                        if not (is_arial and is_bi):
                            cover_publisher_not_arial_bi = True
                            break
    except Exception:
        pass

    # ── FORMAT ISSN HALAMAN KATALOG (Wajib 'ISSN:' tanpa spasi sebelum titik dua) ──
    catalog_issn_colon_error = False
    if "ISSN" in catalog_text.upper():
        m_cat_issn = re.search(r'ISSN(\s*:?)\s*(\d{4}[-–]\d{3}[\dX])', catalog_text, re.I)
        if m_cat_issn:
            sep = m_cat_issn.group(1)
            if sep != ":":
                catalog_issn_colon_error = True
        elif bool(re.search(r'ISSN\s+:', catalog_text, re.I)):
            catalog_issn_colon_error = True

    # ── FORMAT BOLD NAMA PEJABAT PADA KATA PENGANTAR ──
    preface_name_not_bold = False
    if preface_idx >= 0 and preface_idx < num_pages:
        try:
            p_dict = doc[preface_idx].get_text("dict")
            for b in p_dict.get("blocks", []):
                for l in b.get("lines", []):
                    for s in l.get("spans", []):
                        st = s.get("text", "").strip()
                        if st.isupper() and 2 <= len(st.split()) <= 4 and len(st) > 6 and s.get("bbox", [0,0,0,0])[1] > 350:
                            if not any(skip in st for skip in ["KATA PENGANTAR", "PREFACE", "BPS", "BADAN", "STATISTIK", "KABUPATEN", "KECAMATAN", "HTTP", "DALAM ANGKA", "DISTRICT IN FIGURES", "REPUBLIK", "INDONESIA"]):
                                fn = s.get("font", "").lower()
                                fl = s.get("flags", 0)
                                is_bold = (fl & 16 != 0) or ("bold" in fn) or ("black" in fn) or ("heavy" in fn)
                                if not is_bold:
                                    preface_name_not_bold = True
                                    break
        except Exception:
            pass

    # Cek larangan pencantuman NIP pada penandatangan Kata Pengantar & Tim Penyusun (Instrumen Baris 52 & 61)
    preface_has_nip = False
    if preface_idx >= 0 and preface_idx < num_pages:
        pref_comb_txt = pages_text.get(preface_idx, "") + " " + pages_text.get(preface_idx + 1, "")
        if re.search(r'\bNIP[\.:]?\s*\d{8,}', pref_comb_txt, re.I):
            preface_has_nip = True

    team_has_nip = False
    team_has_rt = False
    team_has_page_num = False
    if team_idx >= 0 and team_idx < num_pages:
        if re.search(r'\bNIP[\.:]?\s*\d{8,}', pages_text.get(team_idx, ""), re.I):
            team_has_nip = True
        t_lines = pages_lines.get(team_idx, [])
        if any("DALAM ANGKA" in l.upper() or "IN FIGURES" in l.upper() for l in t_lines[:3]):
            team_has_rt = True
        if t_lines and (t_lines[0].isdigit() or t_lines[0].lower() in ['iii', 'iv', 'v']):
            team_has_page_num = True

    # ── FORMAT DWIBAHASA DAFTAR ISI (Kata Pengantar/Preface dsb) ──
    toc_bilingual_slash_error = False
    if cover_is_bilingual and toc_idx >= 0 and toc_idx < num_pages:
        toc_full_txt = pages_text.get(toc_idx, "")
        if "KATA PENGANTAR" in toc_full_txt.upper():
            if not re.search(r'Kata\s+Pengantar\s*/\s*Preface', toc_full_txt, re.I):
                if "Preface" in toc_full_txt:
                    toc_bilingual_slash_error = True

    # ── TANDA TITIK SETELAH NOMOR SUBBAB PADA DAFTAR ISI (Instrumen Row 74) ──
    toc_subchapter_has_trailing_dot = []
    if toc_idx >= 0 and toc_idx < num_pages:
        t_lines = pages_lines.get(toc_idx, [])
        for tl in t_lines:
            m_sdot = re.match(r'^\s*([1-7](?:\.\d+)+)\.\s+([A-Za-z]{3,})', tl)
            if m_sdot:
                toc_subchapter_has_trailing_dot.append((m_sdot.group(1) + '.', m_sdot.group(1), m_sdot.group(2)))

    # ── PENGGUNAAN ISTILAH DAFTAR GRAFIK ALIH-ALIH DAFTAR GAMBAR (Instrumen Row 94) ──
    uses_daftar_grafik = bool(
        re.search(r'\bDAFTAR\s+GRAFIK\b', all_prelim, re.I)
        or re.search(r'\bLIST\s+OF\s+CHARTS\b', all_prelim, re.I)
    )

    # ── LARANGAN PENCANTUMAN LEMBAR DAFTAR PETA (Instrumen Row 180) ──
    uses_daftar_peta = bool(
        re.search(r'\bDAFTAR\s+PETA\b', all_prelim, re.I)
        or re.search(r'\bLIST\s+OF\s+MAPS\b', all_prelim, re.I)
    )

    # ── RESIDU TEMPLATE DAFTAR PUSTAKA ──
    biblio_has_template_dots = False
    bib_idx_cand = find_page_with_text(doc, "DAFTAR PUSTAKA", start_page=max(0, num_pages - 15))
    if bib_idx_cand >= 0 and bib_idx_cand < num_pages:
        bib_txt = pages_text.get(bib_idx_cand, "")
        if re.search(r'\.{5,}', bib_txt):
            biblio_has_template_dots = True

    # ══════════════════════════════════════════════════════════════════════
    # CROSS-PAGE ISSN CONSISTENCY VALIDATOR (NEW: Ultra Deep)

    # Scans EVERY page for ISSN mentions and detects:
    # - Inconsistencies between pages (e.g. 2065 vs 2655)
    # - Typo variants against KNOWN_BANGKEP_ISSN registry
    # - Pages that should have ISSN but don't
    # ══════════════════════════════════════════════════════════════════════
    issn_per_page = {}  # {page_idx: [issn_values]}
    for i in range(min(25, num_pages)):
        txt = pages_text.get(i, "")
        found = re.findall(r'ISSN\s*[:/]?\s*(\d{4}[-\u2013]\d{3}[\dX])', txt, re.I)
        if found:
            issn_per_page[i] = [m.replace('\u2013', '-') for m in found]

    all_found_issns = set()
    for ms in issn_per_page.values():
        all_found_issns.update(ms)

    issn_cross_page_inconsistent = len(all_found_issns) > 1
    issn_cross_page_details = []
    if issn_cross_page_inconsistent:
        for issn_variant in sorted(all_found_issns):
            pages_with = [str(p + 1) for p, ms in issn_per_page.items() if issn_variant in ms]
            page_labels = []
            for p, ms in issn_per_page.items():
                if issn_variant in ms:
                    if p == catalog_idx:
                        page_labels.append(f"Halaman Katalog (hal {p+1})")
                    elif p == team_idx:
                        page_labels.append(f"Halaman Tim Penyusun (hal {p+1})")
                    elif p == 2:
                        page_labels.append(f"Halaman Judul Utama (hal {p+1})")
                    elif p == 0:
                        page_labels.append(f"Kover Depan (hal {p+1})")
                    elif toc_idx >= 0 and p == toc_idx:
                        page_labels.append(f"Daftar Isi (hal {p+1})")
                    else:
                        page_labels.append(f"Halaman {p+1}")
            issn_cross_page_details.append({
                "issn": issn_variant,
                "pages": pages_with,
                "labels": page_labels
            })

    # ── VALIDASI MATEMATIKA ALGORITMA CHECKSUM ISO 3297 / BRIN SE-INDONESIA ──
    issn_checksum_invalid = []
    for found_issn in all_found_issns:
        if found_issn and found_issn != "-" and not re.search(r'X{4}|0{4}', found_issn, re.I):
            valid, exp_digit = validate_issn_checksum(found_issn)
            if not valid and exp_digit is not None:
                pages_with = [p for p, ms in issn_per_page.items() if found_issn in ms]
                issn_checksum_invalid.append({
                    "issn": found_issn,
                    "expected_check_digit": exp_digit,
                    "pages": pages_with
                })

    # Cross-reference with KNOWN_BANGKEP_ISSN registry (Hanya untuk publikasi Kab. Banggai Kepulauan)
    issn_registry_mismatch = None
    issn_correct_from_registry = None
    if is_bangkep and region_name in KNOWN_BANGKEP_ISSN:
        known = KNOWN_BANGKEP_ISSN[region_name]
        correct_issn = known["correct"]
        issn_correct_from_registry = correct_issn
        typo_variants = known.get("typo_variants", [])
        
        # Check if any found ISSN is a known typo variant
        for found_issn in all_found_issns:
            pages_with = [p for p, ms in issn_per_page.items() if found_issn in ms]
            if found_issn != correct_issn and found_issn in typo_variants:
                issn_registry_mismatch = {
                    "found": found_issn,
                    "correct": correct_issn,
                    "type": "known_typo",
                    "pages": pages_with
                }
                break
            elif found_issn != correct_issn and found_issn not in typo_variants:
                issn_registry_mismatch = {
                    "found": found_issn,
                    "correct": correct_issn,
                    "type": "unknown_variant",
                    "pages": pages_with
                }
                break
        
        # Also check the primary extracted ISSN
        issn_normalized = issn_val.replace('\u2013', '-')
        if issn_normalized != "-" and issn_normalized != correct_issn:
            if not issn_registry_mismatch:
                pages_with = [p for p, ms in issn_per_page.items() if issn_normalized in ms]
                issn_registry_mismatch = {
                    "found": issn_normalized,
                    "correct": correct_issn,
                    "type": "known_typo" if issn_normalized in typo_variants else "unknown_variant",
                    "pages": pages_with
                }

    # ══════════════════════════════════════════════════════════════════════
    # CROSS-PAGE KATALOG NUMBER CONSISTENCY
    # ══════════════════════════════════════════════════════════════════════
    katalog_per_page = {}
    for i in range(min(15, num_pages)):
        txt = pages_text.get(i, "")
        km = re.findall(r'(?:Katalog|Catalogue)[^0-9]*(\d{7,10}\.\d+)', txt, re.I)
        if km:
            katalog_per_page[i] = km
    all_found_katalogs = set()
    for ms in katalog_per_page.values():
        all_found_katalogs.update(ms)
    katalog_cross_page_inconsistent = len(all_found_katalogs) > 1

    # ══════════════════════════════════════════════════════════════════════
    # WRONG YEAR SCANNER (Scans entire document for stale year references)
    # Detects: "Dalam Angka 2024", "Dalam Angka 2025", "in Figures 2024", etc.
    # ══════════════════════════════════════════════════════════════════════
    wrong_year_refs = []
    expected_year = int(pub_year) if pub_year.isdigit() else 2026
    for i in range(num_pages):
        txt = pages_text.get(i, "")
        lines = pages_lines.get(i, [])
        pg_label = lines[0] if lines and lines[0].isdigit() else str(i + 1)
        
        for wrong_yr in range(2020, expected_year):
            if f"Dalam Angka {wrong_yr}" in txt:
                wrong_year_refs.append((i + 1, pg_label, f"Dalam Angka {wrong_yr}", str(expected_year)))
            if f"in Figures {wrong_yr}" in txt:
                wrong_year_refs.append((i + 1, pg_label, f"in Figures {wrong_yr}", str(expected_year)))

    # ══════════════════════════════════════════════════════════════════════
    # ENHANCED PER-PAGE TYPO SCANNER (Beyond table-level scanning)
    # ══════════════════════════════════════════════════════════════════════
    global_typos = []
    for i in range(num_pages):
        txt = pages_text.get(i, "")
        lines = pages_lines.get(i, [])
        pg_label = lines[0] if lines and lines[0].isdigit() else str(i + 1)

        # "ibukota" should be "ibu kota" (KBBI standard)
        if re.search(r'\bibukota\b', txt, re.I) and i > 5:
            global_typos.append((pg_label, "ibukota", "ibu kota (dipisah, KBBI)"))
        # "Subdistric" missing t
        if re.search(r'\bSubdistric\b', txt) and i > 5:
            global_typos.append((pg_label, "Subdistric", "Subdistrict"))
        # "Regenency" 
        if "Regenency" in txt:
            global_typos.append((pg_label, "Regenency", "Regency"))
        # "BPS of" instead of "BPS-Statistics"
        if re.search(r'BPS\s+of\s+', txt) and i > 3:
            global_typos.append((pg_label, "BPS of [Regency]", "BPS-Statistics [Regency]"))
        # "diterbitk an" (broken word)
        if re.search(r'diterbitk\s+an', txt, re.I):
            global_typos.append((pg_label, "diterbitk an", "diterbitkan"))
        # "Puseksmas" typo  
        if "Puseksmas" in txt:
            global_typos.append((pg_label, "Puseksmas", "Puskesmas"))
        # "Kepalad" typo
        if "Kepalad" in txt:
            global_typos.append((pg_label, "Kepalad", "Kepala"))
        # "DIpotong" mid-word capitalization
        if "DIpotong" in txt:
            global_typos.append((pg_label, "DIpotong", "Dipotong"))
        # Double "Menurut Menurut"
        if re.search(r'\bMenurut\s+Menurut\b', txt, re.I):
            global_typos.append((pg_label, "Menurut Menurut", "Menurut (satu kali)"))
        # "Buah- buahan" broken hyphen
        if "Buah- buahan" in txt or "Buah -buahan" in txt:
            global_typos.append((pg_label, "Buah- buahan / Buah -buahan", "Buah-buahan"))
        # "poverity" English typo
        if "poverity" in txt.lower():
            global_typos.append((pg_label, "poverity", "poverty"))

        # Typo BPS-STATISTIC (kurang huruf 's', standar resmi BPS adalah BPS-Statistics)
        if re.search(r'\bBPS-STATISTIC\b', txt, re.I) and not re.search(r'\bBPS-STATISTICS\b', txt, re.I):
            global_typos.append((pg_label, "BPS-STATISTIC", "BPS-Statistics (kurang huruf 's', standar baku Pedoman BPS 2023 hal. 64)"))
        # Nomenklatur satker bahasa Inggris BPS daerah (tanpa kata 'OF')
        if re.search(r'\bBPS-STATISTICS\s+OF\b', txt, re.I):
            global_typos.append((pg_label, "BPS-STATISTICS OF", "BPS-Statistics [Regency] (tanpa kata 'OF', Pedoman BPS 2023)"))
        # Typo Ministry of Religious Affair (kurang s)
        if re.search(r'\bMinistry of Religious Affair\b', txt, re.I) and not re.search(r'\bMinistry of Religious Affairs\b', txt, re.I):
            global_typos.append((pg_label, "Ministry of Religious Affair", "Ministry of Religious Affairs (tambahkan 's')"))
        # Typo LIST OF ABBREVIATION (kurang s)
        if re.search(r'\bLIST OF ABBREVIATION\b', txt, re.I) and not re.search(r'\bLIST OF ABBREVIATIONS\b', txt, re.I):
            global_typos.append((pg_label, "LIST OF ABBREVIATION", "LIST OF ABBREVIATIONS (tambahkan 's')"))
        # Typo Meterologi (kurang o)
        if re.search(r'\bMeterologi\b', txt, re.I):
            global_typos.append((pg_label, "Meterologi", "Meteorologi (tambahkan huruf 'o')"))
        # Typo Muncipality (kurang i)
        if re.search(r'\bMuncipality\b', txt, re.I):
            global_typos.append((pg_label, "Muncipality", "Municipality (kurang huruf 'i')"))
        # Typo campuran bahasa "Social dan Welfare"
        if re.search(r'\bSocial dan Welfare\b', txt, re.I):
            global_typos.append((pg_label, "Social dan Welfare", "Social and Welfare (konsisten bahasa Inggris)"))
        # Ejaan nama wilayah Dako Pamean vs Dako Pemean (Kepmendagri)
        if re.search(r'\bDako Pamean\b', txt, re.I):
            global_typos.append((pg_label, "Dako Pamean", "Dako Pemean (ejaan baku Kepmendagri 050-145 Tahun 2022)"))

    # ══════════════════════════════════════════════════════════════════════
    # DISTRICT IDENTITY INTEGRITY & CLONE DETECTOR
    # Kasus Fatal (seperti di Kab. Tolitoli): Kover diedit jadi Kecamatan A,
    # tetapi isi naskah/katalog/pengantar/tabel masih milik Kecamatan B!
    # ══════════════════════════════════════════════════════════════════════
    cover_txt_norm = re.sub(r'\s+', ' ', cover_text)
    m_cov_dist = re.search(r'Kecamatan\s+([A-Za-z\s]+?)\s+Dalam\s+Angka', cover_txt_norm, re.I)
    cover_district_clean = None
    dummy_placeholders = {'yyy', 'yyyyy', 'xxx', 'xxxxx', 'wilayah', 'kecamatan', ''}
    
    if m_cov_dist:
        cand_cov = re.sub(r'\s+', ' ', m_cov_dist.group(1)).strip().title()
        # Bersihkan kata 'Kecamatan' yang berulang (misal layer kover terduplikasi/shadow text)
        cand_clean = re.sub(r'\bkecamatan\b', '', cand_cov, flags=re.I).strip()
        if cand_clean and cand_clean.lower() not in dummy_placeholders:
            cover_district_clean = cand_clean.title()
            
    # Jika kover depan memiliki text layer terpisah (misal nama kecamatan berada di text frame/layer berbeda):
    if not cover_district_clean:
        # Cek apakah nama wilayah hasil ekstraksi (region_name) muncul eksplisit di teks kover
        if region_name and len(region_name) > 2 and re.search(r'\b' + re.escape(region_name) + r'\b', cover_text, re.I):
            cover_district_clean = region_name
        else:
            # Pindai apakah ada nama kecamatan resmi dari database yang tertulis di kover
            for kec_name in KECAMATAN_TO_KABUPATEN.keys():
                if len(kec_name) > 3 and re.search(r'\b' + re.escape(kec_name) + r'\b', cover_text, re.I):
                    cover_district_clean = kec_name.title()
                    break

    if not cover_district_clean:
        m_fname = re.search(r'kecamatan-([a-z\-]+)-dalam-angka', os.path.basename(pdf_path), re.I)
        if m_fname:
            cand_fn = m_fname.group(1).replace('-', ' ').title()
            cand_fn_clean = re.sub(r'\bkecamatan\b', '', cand_fn, flags=re.I).strip()
            if cand_fn_clean and cand_fn_clean.lower() not in dummy_placeholders:
                cover_district_clean = cand_fn_clean.title()
                
    if not cover_district_clean:
        cover_district_clean = region_name

    p3_txt_norm = re.sub(r'\s+', ' ', pages_text.get(2, ""))
    m_hju_dist = re.search(r'Kecamatan\s+([A-Za-z\s]+?)\s+Dalam\s+Angka', p3_txt_norm, re.I)
    hju_district_clean = re.sub(r'\s+', ' ', m_hju_dist.group(1)).strip().title() if m_hju_dist else None

    kat_txt_norm = re.sub(r'\s+', ' ', catalog_text)
    m_kat_dist = re.search(r'KECAMATAN\s+([A-Z\s]+?)\s+DALAM\s+ANGKA', kat_txt_norm, re.I)
    catalog_district_clean = re.sub(r'\s+', ' ', m_kat_dist.group(1)).strip().title() if m_kat_dist else None

    pref_txt_norm = re.sub(r'\s+', ' ', preface_text)
    m_pref_dist = re.search(r'Publikasi\s+Kecamatan\s+([A-Za-z\s]+?)\s+Dalam\s+Angka', pref_txt_norm, re.I)
    preface_district_clean = re.sub(r'\s+', ' ', m_pref_dist.group(1)).strip().title() if m_pref_dist else None

    inner_stop_words = {
        'dalam', 'angka', 'ini', 'tersebut', 'yang', 'pada', 'dan', 'serta', 'sebagai',
        'secara', 'dengan', 'wilayah', 'bps', 'kota', 'setempat', 'lainnya', 'terkait',
        'masing', 'di', 'ke', 'dari', 'tahun', 'regency', 'district', 'figures',
        'kabupaten', 'se', 'induk', 'pemekaran', 'xxxxx', 'yyyyy', 'xxx'
    }
    inner_mentions_list = []
    inner_page_map = {}
    for p_idx in range(1, num_pages):
        p_txt = pages_text.get(p_idx, "")
        p_matches = re.findall(r'Kecamatan\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)\b', p_txt)
        for pm in p_matches:
            pm_clean = re.sub(r'\s+', ' ', pm).strip().title()
            pm_words = set(pm_clean.lower().split())
            if not (pm_words & inner_stop_words) and len(pm_clean) > 2 and "xxxx" not in pm_clean.lower():
                inner_mentions_list.append(pm_clean)
                inner_page_map.setdefault(pm_clean, set()).add(p_idx + 1)
                
    counts_inner = Counter(inner_mentions_list)
    dominant_inner_district, dom_inner_count = counts_inner.most_common(1)[0] if counts_inner else (None, 0)

    district_mismatch_reasons = []
    is_district_identity_mismatch = False
    
    if cover_district_clean:
        cov_lower = cover_district_clean.lower()
        if dominant_inner_district and dom_inner_count >= 5:
            dom_lower = dominant_inner_district.lower()
            if cov_lower != dom_lower and cov_lower not in dom_lower and dom_lower not in cov_lower:
                is_district_identity_mismatch = True
                sample_pgs = sorted(list(inner_page_map.get(dominant_inner_district, [])))[:6]
                district_mismatch_reasons.append(
                    f'Batang tubuh dan ulasan buku didominasi oleh nama "Kecamatan {dominant_inner_district}" (ditemukan {dom_inner_count} kali pada hal {sample_pgs}), bertentangan dengan kover depan ("Kecamatan {cover_district_clean}").'
                )
                
        # Placeholder master template (seperti Yyy/Xxxxx) bukan ketidaksesuaian wilayah riil antar-kecamatan
        dummy_placeholders = {'yyy', 'yyyyy', 'xxx', 'xxxxx', 'wilayah'}
        
        if hju_district_clean:
            hju_lower = hju_district_clean.lower()
            if hju_lower not in dummy_placeholders:
                if cov_lower != hju_lower and cov_lower not in hju_lower and hju_lower not in cov_lower:
                    is_district_identity_mismatch = True
                    district_mismatch_reasons.append(
                        f'Halaman Judul Utama memuat "Kecamatan {hju_district_clean}", bertentangan dengan kover depan ("Kecamatan {cover_district_clean}").'
                    )
                
        if catalog_district_clean:
            kat_lower = catalog_district_clean.lower()
            if kat_lower not in dummy_placeholders:
                if cov_lower != kat_lower and cov_lower not in kat_lower and kat_lower not in cov_lower:
                    is_district_identity_mismatch = True
                    district_mismatch_reasons.append(
                        f'Halaman Katalog memuat judul "Kecamatan {catalog_district_clean} Dalam Angka", bertentangan dengan kover depan ("Kecamatan {cover_district_clean}").'
                    )
                
        if preface_district_clean:
            pref_lower = preface_district_clean.lower()
            if pref_lower not in dummy_placeholders:
                if cov_lower != pref_lower and cov_lower not in pref_lower and pref_lower not in cov_lower:
                    is_district_identity_mismatch = True
                    district_mismatch_reasons.append(
                        f'Kata Pengantar memuat narasi "Publikasi Kecamatan {preface_district_clean} Dalam Angka", bertentangan dengan kover depan ("Kecamatan {cover_district_clean}").'
                    )
                
    district_mismatch_info = {
        "is_mismatch": is_district_identity_mismatch,
        "cover_district": cover_district_clean,
        "dominant_inner_district": dominant_inner_district,
        "hju_district": hju_district_clean,
        "catalog_district": catalog_district_clean,
        "preface_district": preface_district_clean,
        "reasons": district_mismatch_reasons
    }

    # ══════════════════════════════════════════════════════════════════════
    # RAW TEMPLATE UPLOAD & UNWORKED DRAFT DETECTOR
    # Kasus Fatal: Pengunggah hanya mengunggah file template master mentah
    # (Template KCDA 2026) atau draf yang belum diisi data riil kecamatan!
    # Anti-Bias: Residu teks yang hanya terisolasi di 1 halaman (misal HJU
    # yang tertutup gambar kover) tidak boleh diklaim sebagai draf setengah jadi.
    # ══════════════════════════════════════════════════════════════════════
    full_doc_text = " ".join([pages_text.get(i, "") for i in range(num_pages)])
    cover_full_txt = pages_text.get(0, "")
    back_full_txt = pages_text.get(num_pages - 1, "") if num_pages > 0 else ""
    team_txt = team_text or pages_text.get(team_idx if team_idx >= 0 else 4, "")
    p3_txt = pages_text.get(2, "")

    template_markers_found = []
    marker_locations = []

    if re.search(r'\bCOVER\s+DEPAN\b', cover_full_txt, re.I):
        template_markers_found.append('Label teks instruksi master "COVER DEPAN" tercetak di kover depan (Hal. 1)')
        marker_locations.append('kover_depan')
    if re.search(r'\bCOVER\s+BELAKANG\b', back_full_txt, re.I):
        template_markers_found.append(f'Label teks instruksi master "COVER BELAKANG" tercetak di kover belakang (Hal. {num_pages})')
        marker_locations.append('kover_belakang')
    if re.search(r'\bYYYYY\b', full_doc_text):
        pages_y = [str(i + 1) for i in range(num_pages) if re.search(r'\bYYYYY\b', pages_text.get(i, ""))]
        p_str = f" (terdeteksi di Hal. {', '.join(pages_y)})" if pages_y else ""
        template_markers_found.append(f'Nama wilayah template "YYYYY" ("KECAMATAN YYYYY" / "YYYYY DISTRICT IN FIGURES"){p_str}')
        marker_locations.append('batang_tubuh')
    if re.search(r'\bKecamatan\s+XXX\b|\bKecamatan\s+XXXXX\b', full_doc_text):
        pages_k = [str(i + 1) for i in range(num_pages) if re.search(r'\bKecamatan\s+XXX\b|\bKecamatan\s+XXXXX\b', pages_text.get(i, ""))]
        p_str = f" (terdeteksi di Hal. {', '.join(pages_k)})" if pages_k else ""
        template_markers_found.append(f'Placeholder nama kecamatan "Kecamatan XXX"{p_str} masih tercantum di judul tabel/ulasan')
        marker_locations.append('batang_tubuh')
    if re.search(r'KABUPATEN/KOTA\s+XXXX', full_doc_text, re.I) or re.search(r'BPS-STATISTICS\s+XXXX', full_doc_text, re.I):
        pages_x = [str(i + 1) for i in range(num_pages) if re.search(r'KABUPATEN/KOTA\s+XXXX|BPS-STATISTICS\s+XXXX', pages_text.get(i, ""), re.I)]
        p_str = f" (terdeteksi di Hal. {', '.join(pages_x)})" if pages_x else ""
        template_markers_found.append(f'Identitas satker dummy master "KABUPATEN/KOTA XXXX"{p_str} masih belum diganti')
        if re.search(r'KABUPATEN/KOTA\s+XXXX', p3_txt, re.I) and not re.search(r'KABUPATEN/KOTA\s+XXXX', full_doc_text.replace(p3_txt, ''), re.I):
            marker_locations.append('hju')
        else:
            marker_locations.append('multi_section')
    if re.search(r'nama\s+kepala\s+BPS\s+Kako\s+tanpa\s+gelar', full_doc_text, re.I):
        pages_nk = [str(i + 1) for i in range(num_pages) if re.search(r'nama\s+kepala\s+BPS\s+Kako\s+tanpa\s+gelar', pages_text.get(i, ""), re.I)]
        p_str = f" (terdeteksi di Hal. {', '.join(pages_nk)})" if pages_nk else ""
        template_markers_found.append(f'Teks instruksi template "nama kepala BPS Kako tanpa gelar"{p_str} pada halaman Tim Penyusun')
        marker_locations.append('tim_penyusun')
    if re.search(r'\bNAMA\s+TANPA\s+GELAR\b', full_doc_text):
        pages_ntg = [str(i + 1) for i in range(num_pages) if re.search(r'\bNAMA\s+TANPA\s+GELAR\b', pages_text.get(i, ""))]
        p_str = f" (terdeteksi di Hal. {', '.join(pages_ntg)})" if pages_ntg else ""
        template_markers_found.append(f'Teks instruksi template "NAMA TANPA GELAR"{p_str} pada halaman Kata Pengantar / Preface')
        marker_locations.append('kata_pengantar')
    # Personil dummy hanya dicek pada halaman Tim Penyusun (mencegah false match pada nomor ISSN XXXX-XXXX)
    if re.search(r'xxxxx\s*[•\*]\s*xxxxx', team_txt, re.I) or ('xxxxx' in team_txt and '•' in team_txt):
        template_markers_found.append('Placeholder nama personil penyusun "xxxxx • xxxxx" pada susunan tim')
        marker_locations.append('tim_penyusun')
    if re.search(r'lorem\s+ipsum\s+dolor\s+sit\s+amet', full_doc_text, re.I):
        pages_lorem = [str(i + 1) for i in range(num_pages) if re.search(r'lorem\s+ipsum\s+dolor\s+sit\s+amet', pages_text.get(i, ""), re.I)]
        p_str = f" (terdeteksi di Hal. {', '.join(pages_lorem)})" if pages_lorem else ""
        template_markers_found.append(f'Ulasan statistik dan sambutan masih berupa teks dummy Latin "Lorem ipsum dolor sit amet..."{p_str}')
        marker_locations.append('batang_tubuh')
    if re.search(r'1102001\.(?:xx|xxxx)\b', full_doc_text, re.I):
        pages_kat = [str(i + 1) for i in range(num_pages) if re.search(r'1102001\.(?:xx|xxxx)\b', pages_text.get(i, ""), re.I)]
        p_str = f" (terdeteksi di Hal. {', '.join(pages_kat)})" if pages_kat else ""
        template_markers_found.append(f'Nomor katalog masih berupa placeholder template "1102001.xx" / "1102001.xxxx"{p_str}')
        if re.search(r'1102001\.(?:xx|xxxx)\b', p3_txt, re.I) and not re.search(r'1102001\.(?:xx|xxxx)\b', full_doc_text.replace(p3_txt, ''), re.I):
            marker_locations.append('hju')
        else:
            marker_locations.append('katalog')
    if re.search(r'ISSN\s*XXXX\s*-\s*XXXX', full_doc_text, re.I):
        pages_issn = [str(i + 1) for i in range(num_pages) if re.search(r'ISSN\s*XXXX\s*-\s*XXXX', pages_text.get(i, ""), re.I)]
        p_str = f" (terdeteksi di Hal. {', '.join(pages_issn)})" if pages_issn else ""
        template_markers_found.append(f'Nomor ISSN masih berupa template bawaan "ISSN XXXX -XXXX"{p_str}')
        if re.search(r'ISSN\s*XXXX\s*-\s*XXXX', p3_txt, re.I) and not re.search(r'ISSN\s*XXXX\s*-\s*XXXX', full_doc_text.replace(p3_txt, ''), re.I):
            marker_locations.append('hju')
        else:
            marker_locations.append('multi_section')
    if re.search(r'Dinas\s+xxx\b', full_doc_text, re.I):
        pages_dinas = [str(i + 1) for i in range(num_pages) if re.search(r'Dinas\s+xxx\b', pages_text.get(i, ""), re.I)]
        p_str = f" (terdeteksi di Hal. {', '.join(pages_dinas)})" if pages_dinas else ""
        template_markers_found.append(f'Daftar kontributor data masih memuat "Dinas xxx"{p_str}')
        marker_locations.append('katalog')
    if re.search(r'Jl\.\s*\.{2,}|Telp\.:\s*\.{2,}|@bps\.go\.id', back_full_txt, re.I) and '...' in back_full_txt:
        template_markers_found.append(f'Alamat, kontak, dan email pada kover belakang masih berupa placeholder titik-titik ("Jl. ... Telp.: ...") (Hal. {num_pages})')
        marker_locations.append('kover_belakang')

    unique_marker_sections = set(marker_locations)
    has_lorem = bool(re.search(r'lorem\s+ipsum\s+dolor\s+sit\s+amet', full_doc_text, re.I))
    
    # Hitung kemunculan YYYYY di batang tubuh naskah (di luar HJU)
    yyyyy_pages = [i + 1 for i in range(num_pages) if re.search(r'\bYYYYY\b', pages_text.get(i, ""))]
    # Hanya dianggap masif jika tersebar di banyak halaman batang tubuh (>= 5 halaman)
    has_yyyyy_body_massive = len(yyyyy_pages) >= 5

    is_pure_template = (
        bool(re.search(r'\bCOVER\s+DEPAN\b', cover_full_txt, re.I)) or
        region_name.lower() in ['yyyyy', 'xxxxx', 'wilayah'] or
        len(template_markers_found) >= 10
    )
    
    # Draf setengah jadi masif HANYA aktif jika benar-benar draf mentah yang belum dikerjakan:
    # 1. Dokumen merupakan template murni 100%, ATAU
    # 2. Ada ulasan Latin Lorem Ipsum, ATAU
    # 3. Running title YYYYY tersebar masif di batang tubuh (>= 5 halaman), ATAU
    # 4. Residu template tersebar masif di >= 5 seksi dan >= 3 seksi di luar HJU.
    is_raw_template = (
        is_pure_template or
        has_lorem or
        has_yyyyy_body_massive or
        (len(template_markers_found) >= 5 and len(unique_marker_sections - {'hju'}) >= 3)
    )

    is_hju_only_leak = (len(template_markers_found) > 0 and unique_marker_sections == {'hju'})

    raw_template_info = {
        "is_pure_template": is_pure_template,
        "is_raw_template": is_raw_template,
        "is_hju_only_leak": is_hju_only_leak,
        "markers_count": len(template_markers_found),
        "markers": template_markers_found,
        "marker_sections": list(unique_marker_sections),
        "status_label": "REJECTED_PURE_TEMPLATE" if is_pure_template else ("FATAL_UNWORKED_DRAFT" if is_raw_template else "NORMAL")
    }

    # ══════════════════════════════════════════════════════════════════════
    # ROMAN NUMERAL PAGE COUNT VALIDATOR
    # Validates catalog roman count vs actual preliminary page sequence
    # Catatan Pedoman BPS: Halaman judul, katalog, tim penyusun, serta halaman kosong
    # pemisah bab/seksi TIDAK mencetak nomor halaman (blind folio), tetapi TETAP dihitung
    # dalam urutan penomoran Romawi hingga halaman sebelum Bab 1 (angka Arab 1).
    # ══════════════════════════════════════════════════════════════════════
    roman_page_mismatch = None
    if catalog_roman != "-":
        roman_map = {'i': 1, 'v': 5, 'x': 10, 'l': 50, 'c': 100, 'd': 500, 'm': 1000}
        def _parse_roman(r_s):
            val = 0
            s_low = r_s.lower()
            for j_r in range(len(s_low)):
                c_v = roman_map.get(s_low[j_r], 0)
                n_v = roman_map.get(s_low[j_r + 1], 0) if j_r + 1 < len(s_low) else 0
                if c_v < n_v:
                    val -= c_v
                else:
                    val += c_v
            return val

        catalog_roman_int = _parse_roman(catalog_roman)

        # 1. Cari angka Romawi tertinggi yang tercetak pada preliminaries
        highest_printed_roman = 0
        highest_printed_page = 0
        for i in range(min(35, num_pages)):
            lines_i = pages_lines.get(i, [])
            for l_item in lines_i:
                l_low = l_item.strip().lower()
                if re.match(r'^[ivxlcdm]+$', l_low) and len(l_low) <= 8:
                    r_val = _parse_roman(l_low)
                    if 1 <= r_val <= 60 and r_val > highest_printed_roman:
                        highest_printed_roman = r_val
                        highest_printed_page = i + 1

        # 2. Cari halaman fisik tempat Bab 1 / angka Arab 1 dimulai
        p_arab_start = -1
        for i in range(min(35, num_pages)):
            txt_i = pages_text.get(i, "")
            lines_i = pages_lines.get(i, [])
            if any(k in txt_i.upper() for k in ["BAB 1", "BAB I", "1. GEOGRAFI", "GEOGRAPHY"]):
                if any(l in ["1", "01"] for l in lines_i[:4]):
                    p_arab_start = i + 1
                    break

        # 3. Hitung estimasi halaman preliminaries riil:
        # Halaman kover depan = hal 1, kover belakang/kosong kover = hal 2.
        # Lembar preliminaries berada dari hal 3 s.d. sebelum Bab 1.
        if p_arab_start > 2:
            prelim_sheet_count = (p_arab_start - 1) - 2
        else:
            blank_after_highest = 0
            if highest_printed_page > 0:
                for check_p in range(highest_printed_page, min(highest_printed_page + 3, num_pages)):
                    if len(pages_lines.get(check_p, [])) <= 1:
                        blank_after_highest += 1
            prelim_sheet_count = highest_printed_roman + blank_after_highest

        expected_roman_count = max(prelim_sheet_count, highest_printed_roman)

        # Cocokkan catalog_roman_int terhadap expected_roman_count atau highest_printed_roman
        is_roman_match = (
            abs(catalog_roman_int - expected_roman_count) <= 1 or
            abs(catalog_roman_int - highest_printed_roman) <= 1 or
            (catalog_roman_int in [20, 21, 22] and expected_roman_count in [20, 21, 22])
        )

        if not is_roman_match and catalog_roman_int > 0 and expected_roman_count > 0:
            if abs(catalog_roman_int - expected_roman_count) > 2:
                roman_page_mismatch = (catalog_roman, catalog_roman_int, expected_roman_count)

    catalog_label_errors = []
    standard_catalog_labels = [
        ("Katalog", "Catalogue"),
        ("Nomor Publikasi", "Publication Number"),
        ("Ukuran Buku", "Book Size"),
        ("Jumlah Halaman", "Number of Pages"),
        ("Penyusun Naskah", "Manuscript Drafter"),
        ("Penyunting", "Editor"),
        ("Pembuat Kover", "Cover Designer"),
        ("Penerbit", "Publisher"),
        ("Dicetak oleh", "Printed by"),
        ("Sumber Ilustrasi", "Illustration Source"),
    ]
    for label_id, label_en in standard_catalog_labels:
        # 1. Spasi sebelum titik dua pada label
        m_col = re.search(rf'(?:{label_id}/{label_en}|{label_id}|{label_en})\s+:', catalog_text, re.I)
        if m_col:
            if label_id != "Jumlah Halaman":  # Sudah memiliki deteksi mandiri
                catalog_label_errors.append(
                    f'Terdapat spasi sebelum tanda titik dua pada label "{label_id}/{label_en} :". '
                    f'Penulisan baku ditulis rapat tanpa spasi sebelum titik dua ("{label_id}/{label_en}:").'
                )
        # 2. Spasi sebelum garis miring pada label
        if re.search(rf'{label_id}\s+/{label_en}', catalog_text, re.I):
            if label_id not in ["Katalog", "Jumlah Halaman"]:  # Sudah memiliki deteksi mandiri
                sb, _ = verify_label_slash_space(catalog_raw, label_id, label_en)
                if sb:
                    catalog_label_errors.append(
                        f'Terdapat spasi sebelum garis miring pada label "{label_id} /{label_en}". '
                        f'Penulisan baku dwibahasa BPS ditulis rapat tanpa spasi sebelum garis miring ("{label_id}/{label_en}").'
                    )
        # 3. Spasi setelah garis miring pada label
        if re.search(rf'{label_id}/\s+{label_en}', catalog_text, re.I):
            _, sa = verify_label_slash_space(catalog_raw, label_id, label_en)
            if sa:
                catalog_label_errors.append(
                    f'Terdapat spasi setelah garis miring pada label "{label_id}/ {label_en}". '
                    f'Penulisan baku dwibahasa BPS ditulis rapat setelah garis miring ("{label_id}/{label_en}").'
                )

    # ── TIM PENYUSUN ──
    team_has_issn = bool(re.search(r'ISSN', team_text, re.IGNORECASE))
    team_issn_has_colon = bool(re.search(r'ISSN\s*:\s*\d{4}', team_text))
    team_issn_missing = (issn_val != "-") and not team_has_issn
    team_issn_match = re.search(r'ISSN\s*:?\s*(\d{4}[-–]\d{3}[\dX])', team_text, re.IGNORECASE)
    team_issn = team_issn_match.group(1).strip() if team_issn_match else issn_val
    team_title_nonstandard = bool(re.search(r'TEAM\s+MEMBERS', team_text, re.I))
    team_writers_merged = bool(re.search(r'Pengolah Data dan Penulis Naskah', team_text, re.I))
    team_is_template = bool(re.search(r'nama\s+kepala\s+BPS|tanpa\s+gelar|xxxxx|XXXXX|Volume\s+(?:xx|XX)|ISSN\s+XXXX', team_text, re.I))

    # Sesuai Pedoman Publikasi hal. 81: Jika penanggung jawab, penyunting, pengolah data,
    # penulis naskah, penata letak, dan penerjemah lebih dari satu orang, maka terjemahan
    # bahasa Inggris DIBOLEHKAN dalam bentuk jamak (tambahkan 's').
    team_lines_list = [l.strip() for l in team_text.splitlines() if l.strip()]
    role_blocks = []
    c_role = None
    c_names = []
    for tl in team_lines_list:
        if any(k in tl.upper() for k in ['PENGARAH', 'PENANGGUNG JAWAB', 'PENYUNTING', 'PENGOLAH DATA', 'PENULIS NASKAH', 'PENATA LETAK', 'PENERJEMAH']):
            if c_role:
                role_blocks.append((c_role, c_names))
            c_role = tl
            c_names = []
        elif c_role:
            if not any(k in tl.upper() for k in ['KECAMATAN', 'DISTRICT', 'HTTP', 'ISSN', 'TIM PENYUSUN', 'VOLUME']):
                c_names.append(tl)
    if c_role:
        role_blocks.append((c_role, c_names))

    jabatan_errors = []
    jabatan_tips = []
    for r_line, n_list in role_blocks:
        names_joined = ' '.join(n_list)
        p_tokens = [tok.strip() for tok in re.split(r'[•,\&]|\bdan\b', names_joined) if len(tok.strip()) > 2]
        p_count = max(1, len(p_tokens))
        if p_count == 1:
            for wrong, correct in JABATAN_SALAH_JAMAK.items():
                if wrong.lower() in r_line.lower():
                    jabatan_errors.append((wrong, correct, 1))
        else:
            if 'Data Processor' in r_line and 'Data Processors' not in r_line:
                jabatan_tips.append('Pengolah Data berjumlah lebih dari satu orang, disarankan menggunakan bentuk jamak "Data Processors" (Pedoman hal. 81).')

    # ── KATA PENGANTAR ──
    preface_year_match = re.search(r'Dalam\s+Angka\s+(\d{4})', preface_text, re.IGNORECASE)
    preface_year = preface_year_match.group(1) if preface_year_match else pub_year
    preface_full = pages_text.get(preface_idx, "") if preface_idx >= 0 else ""
    preface_has_running_title = False
    if preface_idx >= 0:
        pf_lines = pages_lines.get(preface_idx, [])
        preface_has_running_title = any('KATA PENGANTAR' in l.upper() and len(l) > 16 for l in pf_lines[:3])

    preface_year_mismatch = None
    if preface_idx >= 0:
        pref_txt = pages_text.get(preface_idx, "")
        m_pref_yrs = re.findall(r'Dalam\s+Angka\s+(\d{4})', pref_txt, re.I)
        for y_found in m_pref_yrs:
            if y_found != str(pub_year):
                preface_year_mismatch = (y_found, pub_year)
                break

    preface_titimangsa_mismatch = None
    if preface_idx >= 0:
        pref_txt = pages_text.get(preface_idx, "")
        m_titi = re.search(r'([A-Z][a-z]+),\s+([A-Za-z]+)\s+(\d{4})', pref_txt)
        if m_titi:
            t_city, t_month, t_year = m_titi.group(1), m_titi.group(2), m_titi.group(3)
            if t_year != str(pub_year):
                preface_titimangsa_mismatch = (
                    f'Kesalahan tahun pada titimangsa Kata Pengantar: Tertulis "{t_city}, {t_month} {t_year}". '
                    f'Tahun wajib diselaraskan dengan tahun publikasi ({pub_year}).'
                )

    # Deteksi inkonsistensi gelar antara Tim Penyusun dan Kata Pengantar
    degree_mismatch = None
    if team_idx >= 0 and preface_idx >= 0:
        # Cari nama di Tim Penyusun (Pengarah / Penanggung Jawab)
        t_name_match = re.search(r'(?:Pengarah|Director|Penanggung\s+Jawab|Person in Charge)[^\n:]*[:\n]\s*([A-Z][a-zA-Z\s\.,]+)', team_text)
        # Cari nama pimpinan di Kata Pengantar
        p_name_match = re.search(r'([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+,\s*[A-Z\.]+)', preface_full)
        if t_name_match and p_name_match:
            t_name = t_name_match.group(1).split('\n')[0].strip()
            p_name = p_name_match.group(1).split('\n')[-1].strip()
            
            def _base_person_name(s):
                c = re.sub(r'\b(Dr|Dra|Drs|Ir|H|Hj)\.?\s+', '', s, flags=re.I)
                c = re.sub(r',\s*[A-Za-z\.,\s]+$', '', c)
                return c.strip().lower()

            base_t = _base_person_name(t_name)
            base_p = _base_person_name(p_name)
            if base_t and base_p and (base_t == base_p or base_t in base_p or base_p in base_t):
                if p_name != t_name and p_name != "-" and t_name != "-":
                    degree_mismatch = (t_name, p_name)

    preface_roman_missing = False
    preface_has_toc_leak = False
    if preface_idx >= 0:
        pref_txt = pages_text.get(preface_idx, "")
        preface_roman_missing = not bool(re.search(r'^\s*[ivxlcdm]+\s*$', pref_txt, re.MULTILINE | re.IGNORECASE))
        preface_has_toc_leak = "Kata Pengantar/Preface" in pref_txt and "..." in pref_txt

    jabatan_penanda_id_singkat = bool(re.search(r'Kepala\s+BPS\s+Kabupaten', preface_full, re.I))
    jabatan_penanda_en_chief = bool(re.search(r'Chief\s+Statistician', preface_en_text + preface_full, re.I))
    preface_en_errors = []
    if "BPS of " in preface_en_text:
        preface_en_errors.append('Penggunaan "BPS of [Regency]" (standar baku adalah "BPS-Statistics [Regency]")')
    if " i n " in preface_en_text:
        preface_en_errors.append('Saltik spasi di dalam kata "in" pada frasa "[District] i n Figures"')
    if "poverity" in preface_en_text.lower():
        preface_en_errors.append('Saltik bahasa Inggris "poverity" (seharusnya "poverty")')

    preface_typo_spasi = bool(re.search(r'diterbitk\s+an', preface_full, re.I))
    preface_typo_dash = bool(re.search(r'sebesar\s*[–—]\s*besarnya', preface_full, re.I))

    # Deteksi penyebutan nama kecamatan lain pada judul publikasi di Kata Pengantar / Preface
    preface_other_districts = []
    pref_opening_match = re.search(r'Publikasi\s+Kecamatan\s+([A-Za-z\s]+?)\s+Dalam\s+Angka', preface_full, re.I)
    if pref_opening_match:
        pref_kec_title = re.sub(r'\s+', ' ', pref_opening_match.group(1)).strip().title()
        if pref_kec_title.lower() not in ['xxxxx', 'wilayah', '', region_name.lower().strip()]:
            if pref_kec_title.lower() != region_name.lower().strip():
                preface_other_districts.append(pref_kec_title)
                
    pref_en_match = re.search(r'([A-Za-z\s]+?)\s+District\s+in\s+Figures', preface_en_text + " " + preface_full, re.I)
    if pref_en_match:
        pref_en_title = re.sub(r'\s+', ' ', pref_en_match.group(1)).strip().title()
        if pref_en_title.lower() not in ['xxxxx', 'wilayah', '', region_name.lower().strip()]:
            if pref_en_title.lower() != region_name.lower().strip() and pref_en_title not in preface_other_districts:
                preface_other_districts.append(pref_en_title)

    # Deteksi ketiadaan tanda tangan penanggung jawab pada Kata Pengantar
    preface_signature_missing = False
    if preface_idx >= 0:
        pref_page = doc[preface_idx]
        blocks = pref_page.get_text('blocks')
        title_block = None
        sig_block = None
        page_h = pref_page.rect.height
        
        # 1. Cari blok jabatan pimpinan (Kepala / Head / Chief Statistician) di separuh bawah halaman
        for b in blocks:
            b_txt = b[4].strip()
            if b[1] > page_h * 0.40:
                if any(k in b_txt for k in ['Kepala BPS', 'Kepala Badan Pusat Statistik', 'Chief Statistician', 'Kepala', 'Head']):
                    title_block = b
                    break
                    
        # 2. Cari blok nama pejabat di bawah jabatan
        if title_block:
            for b in blocks:
                b_txt = b[4].strip()
                if b[1] > title_block[3] and b[1] < page_h * 0.95:
                    lines_b = [l.strip() for l in b_txt.split('\n') if l.strip()]
                    if lines_b and len(lines_b) <= 3:
                        first_line = lines_b[0]
                        if len(first_line.split()) >= 2 and not any(kw in first_line.lower() for kw in ['penerbit', 'katalog', 'halaman', 'website', 'http', 'salakan', 'poso', 'palu', 'tolitoli']):
                            sig_block = b
                            break

        # 3. Cek keberadaan objek tanda tangan di antara title_block dan sig_block
        if title_block and sig_block:
            has_sig_obj = False
            top_y, bot_y = title_block[3], sig_block[1]
            left_x = min(title_block[0], sig_block[0]) - 20
            right_x = max(title_block[2], sig_block[2]) + 20
            
            for info in pref_page.get_image_info():
                bbox = info.get('bbox')
                if bbox and bbox[1] >= top_y - 25 and bbox[3] <= bot_y + 25:
                    if info.get('width', 0) > 20 and info.get('height', 0) > 10:
                        has_sig_obj = True
                        break
                        
            if not has_sig_obj:
                for d in pref_page.get_drawings():
                    rect = d.get('rect')
                    if rect and rect.y0 >= top_y - 15 and rect.y1 <= bot_y + 15:
                        if rect.width > 20 and rect.height > 10:
                            has_sig_obj = True
                            break
                            
            if not has_sig_obj and HAVE_CV2:
                try:
                    clip_rect = fitz.Rect(max(0, left_x), max(0, top_y), min(pref_page.rect.width, right_x), min(pref_page.rect.height, bot_y))
                    if clip_rect.width > 20 and clip_rect.height > 10:
                        pix = pref_page.get_pixmap(clip=clip_rect, dpi=150)
                        nparr = np.frombuffer(pix.tobytes("png"), np.uint8)
                        img = cv2.imdecode(nparr, cv2.IMREAD_GRAYSCALE)
                        if img is not None:
                            dark_px = np.sum(img < 200)
                            if dark_px > 40:
                                has_sig_obj = True
                except Exception:
                    pass
                    
            if not has_sig_obj:
                preface_signature_missing = True

    # ── DAFTAR ISI ──
    toc_has_issn = bool(re.search(r'ISSN\s*[:/]?\s*\d{4}[-\u2013]\d{3}[\dX]', toc_text, re.IGNORECASE))
    toc_issn_placeholder = bool(re.search(r'ISSN\s*XXXX|XXXX\s*-\s*XXXX', toc_text, re.I))
    toc_issn_missing = not toc_has_issn or toc_issn_placeholder
    toc_has_running_title = False
    toc_volume_empty = bool(re.search(r'Volume\s+(?:xx|XX|\.\.\.)', toc_text))
    toc_bookmark_error = "Error! Bookmark not defined" in (toc_text + " " + pages_text.get(toc_idx + 1, ""))
    if toc_idx >= 0:
        toc_lines = pages_lines.get(toc_idx, [])
        for l in toc_lines[:3]:
            if "DALAM ANGKA" in l.upper() or "IN FIGURES" in l.upper():
                toc_has_running_title = True
                break

    toc_chapters_point_to_dividers = []
    if toc_idx >= 0:
        toc_full_combined = pages_text.get(toc_idx, "") + " " + pages_text.get(toc_idx + 1, "")
        for m in re.finditer(r'([1-7])\.\s+[^\n\.]+\.{3,}\s*(\d+)', toc_full_combined):
            chap_num = m.group(1)
            ref_pg = int(m.group(2))
            toc_chapters_point_to_dividers.append((chap_num, ref_pg))

    toc_errors = []
    toc_page_numbers = {}
    if toc_idx >= 0:
        toc_full = pages_text.get(toc_idx, "")
        for label, keyword in [
            ("Kata Pengantar", "Kata Pengantar"),
            ("Preface", "Preface"),
            ("Daftar Isi", "Daftar Isi"),
            ("Daftar Gambar", "Daftar Gambar"),
            ("Penjelasan Umum", "Penjelasan Umum"),
            ("Daftar Singkatan", "Daftar Singkatan"),
            ("Daftar Pustaka", "Daftar Pustaka"),
        ]:
            match = re.search(rf'{keyword}[^\n]*?([ivxlcdmIVXLCDM]{{1,8}}|\d{{1,3}})\s*$', toc_full, re.MULTILINE | re.IGNORECASE)
            if match:
                toc_page_numbers[label] = match.group(1).strip()

    actual_pages = {}
    if toc_figure_idx >= 0:
        actual_pages["Daftar Gambar"] = pages_lines.get(toc_figure_idx, ["-"])[0]
    if penjelasan_idx >= 0:
        actual_pages["Penjelasan Umum"] = pages_lines.get(penjelasan_idx, ["-"])[0]
    if singkatan_idx >= 0:
        actual_pages["Daftar Singkatan"] = pages_lines.get(singkatan_idx, ["-"])[0]
    if biblio_idx >= 0:
        actual_pages["Daftar Pustaka"] = pages_lines.get(biblio_idx, ["-"])[0]

    for label in ["Daftar Gambar", "Penjelasan Umum", "Daftar Singkatan", "Daftar Pustaka"]:
        toc_pg = toc_page_numbers.get(label, "")
        act_pg = actual_pages.get(label, "")
        if toc_pg and act_pg and toc_pg.lower() != act_pg.lower() and act_pg != "-":
            toc_errors.append(f'"{label}" pada Daftar Isi merujuk ke halaman {toc_pg}, tetapi halaman fisik riil adalah {act_pg}')

    # ── DAFTAR TABEL & DAFTAR GAMBAR ──
    daftar_tabel_running_title = False
    if toc_table_idx >= 0:
        dt_lines = pages_lines.get(toc_table_idx, [])
        for l in dt_lines[:4]:
            if "DALAM ANGKA" in l.upper() or "IN FIGURES" in l.upper():
                daftar_tabel_running_title = True
                break

    daftar_gambar_placeholder = False
    daftar_gambar_has_xxx = False
    if toc_figure_idx >= 0:
        fig_text_combined = "".join([pages_text.get(fi, "") for fi in range(toc_figure_idx, min(toc_figure_idx + 4, num_pages))])
        for line in fig_text_combined.splitlines():
            line_clean = line.strip()
            if not line_clean:
                continue
            if re.search(r'\b(?:Judul\s+Gambar|Figure\s+Title|Judul\s+Grafik|Chart\s+Title|Nama\s+Gambar)\b', line_clean, re.I):
                daftar_gambar_placeholder = True
                break
            if re.match(r'^(?:Gambar\s+)?\d+(?:\.\d+)*\s*[\.]{3,}\s*\d+$', line_clean, re.I):
                daftar_gambar_placeholder = True
                break
        daftar_gambar_has_xxx = bool(re.search(r'\b(?:xxx|XXX)\b', fig_text_combined))

    toc_preface_not_italic = False
    if toc_idx >= 0 and toc_idx < num_pages:
        try:
            t_dict = doc[toc_idx].get_text("dict")
            for b in t_dict.get("blocks", []):
                for l in b.get("lines", []):
                    for s in l.get("spans", []):
                        st = s.get("text", "").strip()
                        if st.lower() in ["preface", "table of contents", "list of tables", "list of figures"]:
                            font_n = s.get("font", "").lower()
                            fl = s.get("flags", 0)
                            if not ((fl & 2) or "italic" in font_n or "oblique" in font_n):
                                toc_preface_not_italic = True
                                break
        except Exception:
            pass

    toc_figures_has_dots = False
    if toc_idx >= 0 and toc_idx < num_pages:
        toc_figures_has_dots = bool(re.search(r'Gambar\s+\d+\.\d+[^\n]*?\.\.\.\.+', toc_text))

    penjelasan_english_not_italic = False
    if penjelasan_idx >= 0 and penjelasan_idx < num_pages:
        try:
            p_dict = doc[penjelasan_idx].get_text("dict")
            for b in p_dict.get("blocks", []):
                for l in b.get("lines", []):
                    for s in l.get("spans", []):
                        st = s.get("text", "").strip()
                        if any(term in st for term in ["Not applicable", "Data not available", "Estimated figure", "Preliminary figures", "Null or zero"]):
                            font_n = s.get("font", "").lower()
                            fl = s.get("flags", 0)
                            if not ((fl & 2) or "italic" in font_n or "oblique" in font_n):
                                penjelasan_english_not_italic = True
                                break
        except Exception:
            pass

    # ── SCANNER GAMBAR DUMMY KAMERA (PER BAB) ──
    dummy_figures = []
    for p in range(20, num_pages - 4):
        txt = pages_text.get(p, "")
        lines = pages_lines.get(p, [])
        prt = lines[0] if lines and lines[0].isdigit() else str(p + 1)
        
        drawings = doc[p].get_drawings()
        has_grey_rect = any(d.get('fill') and 0.60 <= d['fill'][0] <= 0.72 and 0.60 <= d['fill'][1] <= 0.72 for d in drawings)
        has_fig_word = any(re.match(r'^(Gambar|Figure)\s*\d+\.\d+', l) for l in lines) or ('Gambar' in txt and 'Figure' in txt)
        has_dots = ('Sumber/Source' in txt and ('...' in txt or '....' in txt)) or txt.count('...') >= 2
        
        if (has_fig_word and has_dots) or has_grey_rect:
            fig_match = re.search(r'(Gambar|Figure)\s*(\d+\.\d+)', txt)
            fig_num = fig_match.group(2) if fig_match else None
            if fig_num:
                dummy_figures.append((fig_num, prt, p + 1))

    # ── SCANNER LOREM IPSUM & DUMMY TEXT DI SELURUH HALAMAN BATANG TUBUH ──
    lorem_ipsum_pages = []
    for p in range(min(20, num_pages), num_pages - 1):
        p_txt = pages_text.get(p, "").lower()
        if "lorem ipsum" in p_txt or "duis autem vel eum" in p_txt or "dolor sit amet" in p_txt:
            lines = pages_lines.get(p, [])
            p_lbl = lines[0] if lines and lines[0].isdigit() else str(p + 1)
            lorem_ipsum_pages.append((p + 1, p_lbl))

    # ── SCANNER YYYYY PADA RUNNING TITLE ──
    yyyyy_running_title_pages = []
    for p in range(min(20, num_pages), num_pages - 1):
        p_txt = pages_text.get(p, "")
        if "YYYYY" in p_txt:
            lines = pages_lines.get(p, [])
            p_lbl = lines[0] if lines and lines[0].isdigit() else str(p + 1)
            yyyyy_running_title_pages.append((p + 1, p_lbl))

    # ── SCANNER PEMBATAS BAB (BAB 1 s.d. 7) ──
    chapter_starts = {}
    for p in range(min(20, num_pages), num_pages - 1):
        p_txt = pages_text.get(p, "")
        for ch in range(1, 8):
            if ch not in chapter_starts:
                if re.search(rf'(?:^|\n)\s*{ch}\s+[A-Z]{{3,}}', p_txt) or re.search(rf'BAB\s+{ch}\b', p_txt, re.I):
                    chapter_starts[ch] = p + 1

    missing_chapter_dividers = []
    for ch in range(2, 8):
        if ch in chapter_starts:
            ch_p = chapter_starts[ch]
            has_div = False
            for prev_p in [ch_p - 1, ch_p - 2]:
                if 0 <= prev_p - 1 < num_pages:
                    pr_txt = re.sub(r'https?://\S+', '', pages_text.get(prev_p - 1, "")).strip()
                    if len(doc[prev_p - 1].get_images()) >= 1 and len(pr_txt) < 50:
                        has_div = True
                        break
            if not has_div:
                missing_chapter_dividers.append(ch)

    # ── SCANNER JUDUL GAMBAR XXX & GRAFIK KOSONG ──
    xxx_figures = []
    empty_peta_wilayah = False
    empty_grafik_jarak = False
    real_figures_found = 0
    fig_has_tahun = []
    fig_has_trailing_dot = []
    fig_note_has_keterangan = []
    for p in range(min(20, num_pages), num_pages - 1):
        p_txt = pages_text.get(p, "")
        lines = pages_lines.get(p, [])
        p_lbl = lines[0] if lines and lines[0].isdigit() else str(p + 1)
        m_fig = re.search(r'(?:Gambar|Figure)\s*(\d+)', p_txt)
        if m_fig:
            fig_idx_str = m_fig.group(1)
            is_xxx = re.search(r'(?:Gambar|Figure)\s*\d+\s+xxx\b', p_txt, re.I) or "\nxxx\n" in p_txt or p_txt.count("xxx") >= 2
            if is_xxx:
                xxx_figures.append((fig_idx_str, p + 1, p_lbl))
            else:
                real_figures_found += 1
            # Cek kata "Tahun" pada judul gambar (Instrumen Baris 169)
            m_fig_thn = re.search(r'(?:Gambar|Figure)\s*[\d\.]+\s+.*?\bTahun\s+\d{4}\b', p_txt, re.I)
            if m_fig_thn:
                fig_has_tahun.append((p + 1, p_lbl, m_fig_thn.group(0).strip()))

            # Cek titik di akhir nomor gambar atau judul gambar (Instrumen Baris 164)
            m_fig_all = re.search(r'(?:Gambar|Figure)\s*([1-7](?:\.\d+)?|\d+)(\.)?\s+([^\n]+)', p_txt)
            if m_fig_all:
                f_num = m_fig_all.group(1)
                has_dot_num = (m_fig_all.group(2) == '.')
                f_title = m_fig_all.group(3).strip()
                if has_dot_num:
                    fig_has_trailing_dot.append((p + 1, p_lbl, f"Gambar {f_num}.", f"Gambar {f_num}", "nomor"))
                elif f_title.endswith('.'):
                    fig_has_trailing_dot.append((p + 1, p_lbl, f_title, f_title.rstrip('.'), "judul"))

            # Cek Keterangan: alih-alih Catatan: di bawah gambar (Instrumen Baris 172)
            if re.search(r'^\s*Keterangan\s*[:/]', p_txt, re.MULTILINE | re.IGNORECASE) and ('Gambar' in p_txt or 'Figure' in p_txt) and 'Tabel' not in p_txt:
                fig_note_has_keterangan.append((p + 1, p_lbl))

            if fig_idx_str == "1" and ("Peta Wilayah" in p_txt or "Map of" in p_txt):
                imgs = [im for im in doc[p].get_image_info() if im.get('width', 0) > 150 and im.get('height', 0) > 150]
                if len(imgs) == 0:
                    empty_peta_wilayah = True
            if fig_idx_str == "2" and ("Jarak ke Ibukota" in p_txt or "Distance to the District" in p_txt):
                if "...." in p_txt or "..." in p_txt:
                    empty_grafik_jarak = True
    
    daftar_gambar_unnecessary = (real_figures_found < 3 and toc_figure_idx >= 0)

    # ── PEMBATAS BAB & AWAL BAB GANJIL ──
    even_start_chapters = []
    divider_has_running_title = False
    divider_has_page_num = False
    chapter_opening_has_rt = []
    divider_texts = []
    for p in range(20, num_pages - 3):
        txt = pages_text.get(p, "").strip()
        txt_no_web = re.sub(r'https?://\S+', '', txt).strip()
        is_divider = len(doc[p].get_images()) >= 1 and len(txt_no_web) < 40
        if is_divider or bool(re.search(r'\bBAB\s*[1-7]\b', txt, re.I) and len(txt_no_web) < 120):
            divider_texts.append(txt)
        if is_divider:
            if any("DALAM ANGKA" in l.upper() or "IN FIGURES" in l.upper() for l in pages_lines.get(p, [])):
                divider_has_running_title = True
            div_lines = pages_lines.get(p, [])
            if div_lines and div_lines[0].isdigit():
                divider_has_page_num = True
            if p + 1 < num_pages:
                next_lines = pages_lines.get(p + 1, [])
                if any("DALAM ANGKA" in l.upper() or "IN FIGURES" in l.upper() for l in next_lines[:3]):
                    ch_txt = pages_text.get(p + 1, "")
                    ch_m = re.search(r'BAB\s*(\d+)|(?:^|\n)([1-7])\.\d+', ch_txt, re.I)
                    ch_num = ch_m.group(1) or ch_m.group(2) if ch_m else ""
                    ch_label = f"Bab {ch_num}" if ch_num else "bab"
                    chapter_opening_has_rt.append((ch_label, p + 2))
                if next_lines and next_lines[0].isdigit():
                    next_prt = int(next_lines[0])
                    if next_prt % 2 == 0:
                        next_txt = pages_text.get(p + 1, "") + " " + pages_text.get(p + 2, "")
                        ch_m = re.search(r'BAB\s*(\d+)|(?:^|\n)([1-7])\.\d+', next_txt, re.I)
                        ch_num = ch_m.group(1) or ch_m.group(2) if ch_m else str(len(even_start_chapters) + 5)
                        even_start_chapters.append((ch_num, next_prt))

    # ── SCANNER NARASI (ULASAN KOSONG PER BAB & SUBBAB TITIK AKHIR) ──
    empty_ulasan_chapters = []
    body_subchapter_has_trailing_dot = []
    for p in range(20, num_pages - 4):
        txt = pages_text.get(p, "")
        lines = pages_lines.get(p, [])
        pg_num = lines[0] if lines and lines[0].isdigit() else str(p + 1)

        # Cek nomor subbab dengan tanda titik di akhir pada batang tubuh (Instrumen Baris 130)
        for line in lines:
            line_s = line.strip()
            m_sub = re.match(r'^([1-7]\.\d+)\.\s+([A-Z][A-Za-z\s]{3,})$', line_s)
            if m_sub:
                sub_code = m_sub.group(1)
                sub_title = m_sub.group(2).strip()
                if not any(k in sub_title.upper() for k in ["TABEL", "TABLE", "GAMBAR", "FIGURE", "LAMPIRAN", "GRAFIK"]):
                    body_subchapter_has_trailing_dot.append((p + 1, pg_num, line_s, f"{sub_code} {sub_title}"))

        if "ULASAN" in txt.upper() and "DESCRIPTION" in txt.upper():
            content_lines = [l for l in lines if not any(k in l.upper() for k in [
                "ULASAN", "DESCRIPTION", "DISTRICT IN FIGURES", "DALAM ANGKA", "HTTPS://", "BPS.GO.ID"
            ]) and not l.isdigit()]
            if len(content_lines) < 3:
                bab_name = ""
                for back_p in range(max(0, p - 3), p):
                    b_txt = pages_text.get(back_p, "")
                    bm = re.search(r'BAB\s+(\d+|[IVXLCDM]+)[^\n]*\n([^\n]+)', b_txt, re.I)
                    if bm:
                        bab_name = f"Bab {bm.group(1)} ({bm.group(2).strip()})"
                        break
                empty_ulasan_chapters.append((p + 1, pg_num, bab_name or f"Halaman {pg_num}"))

    # ── SCANNER TABEL (GRANULAR PER HALAMAN) ──
    table_findings = []
    sample_tables = []
    for p in range(20, num_pages - 3):
        txt = pages_text.get(p, "")
        lines = pages_lines.get(p, [])
        if not lines:
            continue
        pg_num = lines[0] if lines[0].isdigit() else str(p + 1)

        current_tbl_num = None
        candidate_title = None
        for idx_l, line in enumerate(lines):
            num_match = re.match(r'^([1-7](?:\.\d+)+)(\.)?$', line)
            if num_match and idx_l + 1 < len(lines):
                c_cand = lines[idx_l + 1]
                if len(c_cand) > 5 and not c_cand.isdigit() and 'KECAMATAN' not in c_cand.upper():
                    current_tbl_num = num_match.group(1)
                    candidate_title = c_cand
                    if num_match.group(2) == '.':
                        table_findings.append(
                            f"Tabel {current_tbl_num} (hal {pg_num}, hal fisik {p+1}): Terdapat tanda titik (.) di akhir nomor tabel ('{line}'). Sesuai Pedoman Publikasi BPS 2023 hal. 40 & Instrumen baris 141, nomor tabel tidak boleh diakhiri tanda titik."
                        )
                    if current_tbl_num.count('.') >= 2:
                        break
        if not current_tbl_num:
            m_lanj = re.search(r'Lanjutan Tabel/Continued Table\s*(\d+\.\d+(?:\.\d+)?)', txt, re.I)
            if m_lanj:
                current_tbl_num = "Lanjutan " + m_lanj.group(1)
        
        tbl_label = f"Tabel {current_tbl_num} (hal {pg_num}, hal fisik {p+1})" if current_tbl_num else f"Tabel pada halaman {pg_num} (hal fisik {p+1})"

        if current_tbl_num or ('Tabel' in txt) or ('Table' in txt):
            is_tbl_bi = bool(
                re.search(r'\bTable\b', txt, re.I)
                or re.search(r'/\s*Table', txt, re.I)
                or ("Source" in txt and "Sumber" in txt)
                or ("Note" in txt and "Catatan" in txt)
            )
            sample_tables.append({
                "page": p + 1,
                "tbl_num": current_tbl_num,
                "is_bilingual": is_tbl_bi
            })

        # Titik di akhir judul tabel (Instrumen Row 141)
        if candidate_title and candidate_title.endswith('.'):
            table_findings.append(
                f"{tbl_label}: Terdapat tanda titik (.) di akhir judul tabel ('{candidate_title}'). Sesuai Pedoman Publikasi BPS 2023 hal. 40 & Instrumen baris 141, nomor dan judul tabel tidak boleh diakhiri tanda titik."
            )

        # Kata "Tahun" pada judul tabel (Instrumen Row 145)
        if candidate_title and re.search(r'\bTahun\s+(?:202\d|201\d)\b', candidate_title, re.I) and not re.search(r'Tahun\s+Ajaran', candidate_title, re.I):
            table_findings.append(
                f"{tbl_label}: Judul tabel memuat kata 'Tahun' sebelum angka tahun ('{candidate_title}'). Sesuai Pedoman Publikasi BPS 2023 hal. 41 & Instrumen baris 145, judul tabel tidak perlu menampilkan kata 'Tahun', melainkan didahului tanda koma sebelum keterangan waktu (contoh: '..., 2024')."
            )

        # "Keterangan:" alih-alih "Catatan:" di bawah tabel (Instrumen Row 158)
        if re.search(r'^\s*Keterangan\s*[:/]', txt, re.MULTILINE | re.IGNORECASE) and ('Tabel' in txt or 'Table' in txt or has_continuation):
            table_findings.append(
                f"{tbl_label}: Penjelasan di bawah tabel menggunakan kata 'Keterangan:'. Sesuai Pedoman BPS 2023 hal. 43 & Instrumen baris 158, penjelasan di bawah tabel wajib didahului dengan kata 'Catatan:' bukan 'Keterangan:'."
            )

        # Judul terbalik di bawah data
        has_tabel_word = any(l.upper() in ["TABEL", "TABLE"] for l in lines)
        if has_tabel_word:
            tabel_indices = [i for i, l in enumerate(lines) if l.upper() in ["TABEL", "TABLE"]]
            if tabel_indices and tabel_indices[0] > len(lines) // 2:
                table_findings.append(
                    f"{tbl_label}: Tata letak terbalik. Judul tabel dan label 'Tabel/Table' diletakkan di BAGIAN BAWAH data tabel alih-alih di atas tabel."
                )

        # Sumber/Catatan di atas header kolom
        has_continuation = any("Lanjutan Tabel" in l or "Continued Table" in l for l in lines)
        if has_continuation:
            cat_idx = -1
            col1_idx = -1
            for i_l, l in enumerate(lines):
                if "Catatan/Note" in l or "Sumber/Source" in l:
                    cat_idx = i_l
                if "(1)" in l:
                    col1_idx = i_l
            if cat_idx != -1 and col1_idx != -1 and cat_idx < col1_idx:
                table_findings.append(
                    f"{tbl_label}: Posisi Catatan dan Sumber diletakkan di ATAS tabel sebelum header kolom. Sesuai standar BPS, blok Catatan dan Sumber wajib diletakkan di bagian bawah tabel."
                )

        # Deteksi data tabel KOSONG TOTAL (blank cells tanpa angka, tanpa tanda nol/dash, tanpa elipsis)
        data_nums = []
        for l in lines:
            cleaned = l.replace('.', '').replace(',', '').replace('%', '').strip()
            if cleaned.isdigit() and len(cleaned) > 0:
                if l == pg_num:
                    continue
                if re.match(r'^[1-7](?:\.\d+)+$', l):
                    continue
                if current_tbl_num and l in current_tbl_num.split('.'):
                    continue
                if re.match(r'^\(\d+\)$', l):
                    continue
                if cleaned in ['2020', '2021', '2022', '2023', '2024', '2025', '2026']:
                    continue
                if l in ['1', '2', '3', '4', '5', '6', '7', '8', '9', '10'] and any('Gol' in x or 'Group' in x or '(1)' in x for x in lines):
                    continue
                data_nums.append(l)

        cell_dashes = [l for l in lines if l in ['-', '–', '—']]
        ellipsis_count = txt.count('…') + len(re.findall(r'^\.{3}$', txt, re.M))

        has_stub = (
            any(kw.lower() in txt.lower() for kw in [
                'desa/kelurahan', 'village/subdistrict', 'tingkat pendidikan', 'educational level',
                'dusun', 'jenis tanaman', 'komoditi', 'rincian', 'indikator', 'kelompok umur',
                'status', 'lapangan usaha', 'sektor', 'kategori', 'nama desa', 'nama kelurahan',
                'uraian', 'bulan', 'month', 'tahun', 'year'
            ])
            or ('(1)' in txt and '(2)' in txt)
            or bool(re.search(r'\b(?:Desa|Kelurahan|Dusun)\b', txt))
        )
        is_table_structure = (has_tabel_word or has_continuation) and has_stub and len(lines) >= 15

        if is_table_structure and len(data_nums) == 0 and len(cell_dashes) == 0 and ellipsis_count < 10:
            table_findings.append(
                f"{tbl_label}: Data tabel KOSONG TOTAL / belum diisi. Seluruh sel data baris tidak memuat angka, notasi nol ('–'), ataupun notasi tidak tersedia ('NA'). Sesuai Pedoman Publikasi BPS 2023 hal. 42 dan Instrumen baris 151, dilarang membiarkan sel tabel kosong tanpa notasi. Jika data memang tidak tersedia dari instansi terkait, tabel opsional sebaiknya tidak dimuat dalam buku daripada dibiarkan berupa template kosong melompong."
            )
        elif ellipsis_count >= 10:
            table_findings.append(
                f"{tbl_label}: Data tabel kosong total / belum tersedia. Seluruh sel data numerik hanya menyajikan tanda elipsis ('…' atau '...'). Jika data tidak tersedia, tabel opsional sebaiknya tidak ditampilkan atau diisi data riil."
            )

        # Cek penggunaan angka 0, 0,0, 0,00 pada sel data tabel (Instrumen Row 156)
        bare_zeros = [l for l in lines if l in ['0', '0,0', '0,00']]
        if len(bare_zeros) >= 3 and is_table_structure:
            table_findings.append(
                f"{tbl_label}: Ditemukan penggunaan angka nol ('{bare_zeros[0]}') pada {len(bare_zeros)} sel tabel. "
                f"Sesuai Pedoman Pembuatan Publikasi BPS 2023 Bab 4 hal. 69 & Instrumen baris 156, nilai nol mutlak (tidak ada) "
                f"WAJIB disajikan dengan tanda strip panjang En Dash ('–'), sedangkan nilai mendekati nol dilambangkan dengan '~0' "
                f"(dilarang menggunakan angka 0, 0,0, maupun 0,00 dalam sel tabel statistik)."
            )

        # Catatan/Sumber sampah
        if re.search(r'Catatan/Note\s*:\s*\.{2,}', txt) or re.search(r'Catatan/Note\s*:\s*,{2,}', txt):
            table_findings.append(
                f"{tbl_label}: Baris Catatan/Note hanya memuat tanda elipsis '...' tanpa keterangan teknis apapun. Jika tidak ada catatan khusus, teks 'Catatan/Note:' wajib dihapus sepenuhnya."
            )
        if re.search(r'Sumber/Source\s*:\s*\.{2,}', txt):
            table_findings.append(
                f"{tbl_label}: Baris Sumber/Source belum diisi (hanya memuat elipsis '...'). Wajib mencantumkan nama instansi resmi asal data."
            )

        # Kolom melompat
        col_nums = [int(m) for m in re.findall(r'^\((\d+)\)$', txt, re.MULTILINE)]
        if col_nums and len(col_nums) >= 2:
            for idx_c in range(1, len(col_nums)):
                if col_nums[idx_c] - col_nums[idx_c-1] > 1:
                    table_findings.append(
                        f"{tbl_label}: Penomoran kolom tabel melompat dari ({col_nums[idx_c-1]}) langsung ke ({col_nums[idx_c]}). Kolom ({col_nums[idx_c-1]+1}) s.d. ({col_nums[idx_c]-1}) hilang."
                    )
                    break

        # Superscript tanpa catatan kaki
        if re.search(r'\b(Desa|Villages?)\s*1/', txt) and not re.search(r'1/\s*\S+', txt[-300:]):
            table_findings.append(
                f"{tbl_label}: Tanda superscript '1/' ditemukan pada header tabel tanpa penjelasan catatan kaki yang sesuai di bagian bawah tabel."
            )

        # Satuan km2 / m2 bukan superskrip
        if re.search(r'\(km2\b|\(km2/', txt):
            table_findings.append(
                f"{tbl_label}: Kesalahan penulisan satuan luas '(km2)'. Sesuai kaidah baku tipografi BPS, wajib menggunakan simbol superskrip kuadrat '(km²)'."
            )
        if re.search(r'\(m2\b|\(m2/', txt):
            table_findings.append(
                f"{tbl_label}: Kesalahan penulisan satuan luas '(m2)'. Wajib menggunakan simbol superskrip kuadrat '(m²)'."
            )

        # Saltik spesifik
        if "Kepalad" in txt:
            table_findings.append(
                f"{tbl_label}: Saltik pada judul tabel: Tertulis 'Kepalad Sekolah' (kelebihan huruf 'd', penulisan yang benar adalah 'Kepala Sekolah')."
            )
        if re.search(r'\bSubdistric\b', txt):
            table_findings.append(
                f"{tbl_label}: Saltik pada teks bahasa Inggris: Tertulis 'Subdistric' (kurang huruf 't', penulisan yang benar adalah 'Subdistrict')."
            )
        if "ibukota" in txt.lower():
            table_findings.append(
                f"{tbl_label}: Penggunaan kata tidak baku 'ibukota'. Penulisan baku menurut KBBI dan pedoman BPS adalah 'ibu kota' (dipisah)."
            )
        if "Puseksmas" in txt:
            table_findings.append(
                f"{tbl_label}: Saltik pada judul tabel: Tertulis 'Puseksmas' (penulisan yang benar adalah 'Puskesmas')."
            )
        if "DIpotong" in txt:
            table_findings.append(
                f"{tbl_label}: Saltik huruf kapital di tengah kata: Tertulis 'DIpotong' (seharusnya 'Dipotong')."
            )
        if re.search(r'\bMenurut\s+Menurut\b', txt, re.I):
            table_findings.append(
                f"{tbl_label}: Saltik pengulangan kata pada judul tabel: Tertulis 'Menurut Menurut' (kata 'Menurut' tercetak dua kali berturut-turut)."
            )
        if "Buah- buahan" in txt or "Buah -buahan" in txt:
            table_findings.append(
                f"{tbl_label}: Kesalahan spasi pada kata ulang di judul tabel: Tertulis 'Buah- buahan' (penulisan baku tanda hubung tanpa spasi: 'Buah-buahan')."
            )
        if "Fasilitas/ " in txt or "Pos/ " in txt:
            table_findings.append(
                f"{tbl_label}: Kesalahan spasi setelah garis miring pada judul tabel/header (contoh: 'Fasilitas/ Upaya' atau 'Kantor Pos/ Pos Pembantu'). Tanda garis miring tidak boleh diikuti spasi."
            )
        if re.search(r'\b2024/\s', txt):
            table_findings.append(
                f"{tbl_label}: Tahun ajaran terpotong pada judul tabel: Tertulis '2024/' tanpa tahun penutup (seharusnya '2024/2025')."
            )

        # Penulisan kata tugas 'Menurut' dengan huruf kapital di tengah kalimat judul tabel
        if candidate_title and re.search(r'[a-z0-9\)]\s+Menurut\b', candidate_title):
            table_findings.append(
                f"{tbl_label}: Penulisan judul tabel memuat kata 'Menurut' dengan huruf kapital di tengah kalimat ('{candidate_title}'). "
                f"Sesuai kaidah PUEBI/EYD dan Pedoman Publikasi BPS, kata tugas/preposisi di tengah judul wajib diawali huruf kecil: 'menurut' (contoh: '... menurut Jenis Kelamin ...')."
            )

        # Ketidakurutan nomor catatan kaki tabel (Footnote Sequence Gap, misal 1 dan 3 ada tapi 2 hilang)
        has_fn1 = bool(re.search(r'(?:Catatan|Note|Sumber|Source|Tabel|Table)[^\n]*?\b1\b|1/\s+|[a-zA-Z]1\b', txt))
        has_fn3 = bool(re.search(r'(?:Catatan|Note|Sumber|Source|Tabel|Table)[^\n]*?\b3\b|3/\s+|[a-zA-Z]3\b', txt))
        has_fn2 = bool(re.search(r'(?:Catatan|Note|Sumber|Source|Tabel|Table)[^\n]*?\b2\b|2/\s+|[a-zA-Z]2\b', txt))
        if has_fn1 and has_fn3 and not has_fn2 and ('Catatan' in txt or 'Note' in txt):
            table_findings.append(
                f"{tbl_label}: Terdapat ketidakurutan nomor catatan kaki (terdapat nomor catatan kaki 1 dan 3, tapi tidak ada nomor catatan kaki 2). "
                f"Seharusnya penomoran catatan kaki dan tanda rujukan berurutan 1, 2, 3, dst. Periksa juga tabel lainnya."
            )

        # Posisi baris agregat total kecamatan di baris pertama alih-alih baris paling bawah
        m_col_num = re.search(r'\(\s*1\s*\)', txt)
        if m_col_num:
            after_cols = txt[m_col_num.end():m_col_num.end() + 250].strip()
            m_after_lines = [l.strip() for l in after_cols.splitlines() if l.strip() and not re.match(r'^\(\s*\d+\s*\)$', l.strip())]
            if m_after_lines:
                first_data_line = m_after_lines[0]
                if first_data_line.upper().startswith("KECAMATAN ") and not first_data_line.upper().endswith("DALAM ANGKA"):
                    table_findings.append(
                        f"{tbl_label}: Baris data agregat kecamatan (\"{first_data_line}\") diletakkan pada baris pertama. "
                        f"Sesuai kaidah penyajian tabel statistik BPS, baris data agregat kecamatan seharusnya diletakkan pada baris paling bawah tabel di bawah rincian desa/kelurahan. Periksa kembali tabel lainnya."
                    )

        # Stub Jenis Tanaman pada Peternakan/Perikanan
        is_livestock_or_fishery = any(k in txt.lower() for k in ["ternak", "unggas", "daging", "telur", "ikan", "perikanan", "budidaya ikan"])
        if is_livestock_or_fishery and ("Jenis Tanaman" in txt or "Kind of Plants" in txt):
            table_findings.append(
                f"{tbl_label}: Kesalahan fatal header kolom stub. Kolom stub tertulis 'Jenis Tanaman/Kind of Plants', padahal menyajikan data Peternakan/Perikanan. Ganti header stub sesuai komoditasnya."
            )

        # Sumber Air Minum pada Vaksinasi
        if any(k in txt.lower() for k in ["imunisasi", "vaksin", "bcg", "dpt", "campak"]) and "Sumber Air Minum" in txt:
            table_findings.append(
                f"{tbl_label}: Kesalahan fatal header kolom. Header kolom tertulis 'Sumber Air Minum/Source of Drinking Water' padahal data tabel menyajikan data vaksinasi/imunisasi."
            )

        # Rentang tahun pada judul tabel (Kaidah Pedoman Publikasi BPS hal. 66)
        m_2yr = re.search(r'\b(20\d\d)\s*([–\-])\s*(20\d\d)\b', txt)
        if m_2yr:
            y1 = int(m_2yr.group(1))
            sep = m_2yr.group(2)
            y2 = int(m_2yr.group(3))
            if y2 - y1 == 1:
                table_findings.append(
                    f"{tbl_label}: Kesalahan penulisan rentang tahun pada judul tabel: Tertulis '{m_2yr.group(0)}'. "
                    f"Sesuai Pedoman Publikasi BPS (hal. 66), apabila hanya menyajikan dua tahun, gunakan kata 'dan' sebagai penghubung antar tahun ('{y1} dan {y2}'). "
                    f"Tanda pisah En Dash (–) hanya digunakan jika menyajikan rentang lebih dari dua tahun (contoh: {y1}–{y2+2})."
                )
            elif y2 - y1 > 1 and sep == '-':
                table_findings.append(
                    f"{tbl_label}: Penulisan rentang tahun pada judul tabel masih menggunakan tanda minus strip (-): Tertulis '{m_2yr.group(0)}'. "
                    f"Sesuai Pedoman Publikasi BPS, penulisan rentang tahun (lebih dari dua tahun) wajib menggunakan notasi En Dash (–) tanpa spasi ('{y1}–{y2}')."
                )

        # Deteksi perataan kolom angka di tengah (Center Aligned) alih-alih rata kanan (Right Aligned)
        page_obj = doc[p]
        words = page_obj.get_text('words')
        num_words = [w for w in words if re.match(r'^\d+([,\.]\d+)+$', w[4])]
        if len(num_words) >= 6:
            cols = {}
            for w in num_words:
                found = False
                for c_x in cols:
                    if abs(w[0] - c_x) < 30:
                        cols[c_x].append(w)
                        found = True
                        break
                if not found:
                    cols[w[0]] = [w]
            for c_x, col_list in cols.items():
                if len(col_list) >= 5:
                    centers = [(w[0] + w[2])/2 for w in col_list]
                    x1s = [w[2] for w in col_list]
                    diff_len = len(set(len(w[4]) for w in col_list))
                    if diff_len > 1:
                        center_spread = max(centers) - min(centers)
                        x1_spread = max(x1s) - min(x1s)
                        if center_spread < 1.2 and x1_spread > 2.5:
                            sample_vals = ", ".join([w[4] for w in col_list[:3]])
                            table_findings.append(
                                f"{tbl_label}: Kolom angka ({sample_vals}, dll.) diformat rata tengah (center-aligned) sehingga koma desimal tidak lurus vertikal. "
                                f"Sesuai Pedoman Publikasi BPS 2023 Bab 4 hal. 68, angka pada sel tabel statistik WAJIB rata kanan (right-aligned)."
                            )
                            break

    # ── RUNNING TITLE BATANG TUBUH ──
    rt_odd_wrong = []
    rt_even_wrong = []
    for page_idx in range(24, min(num_pages - 2, 106)):
        txt = pages_text.get(page_idx, "").strip()
        lines = pages_lines.get(page_idx, [])
        if not lines or not lines[0].isdigit():
            continue
        pg_num = int(lines[0])
        if pg_num < 3:
            continue
        rt = lines[1] if len(lines) > 1 else ""
        if pg_num % 2 == 1:
            if rt and 'DISTRICT IN FIGURES' not in rt.upper() and 'BAB' not in rt.upper() and len(rt) > 3:
                rt_odd_wrong.append(pg_num)
        else:
            if rt and 'DALAM ANGKA' not in rt.upper() and len(rt) > 3:
                rt_even_wrong.append(pg_num)

    # ── DAFTAR PUSTAKA & KOVER BELAKANG ──
    has_daftar_pustaka = (biblio_idx >= 0)
    biblio_has_rt = False
    biblio_has_arabic_page = False
    if biblio_idx >= 0:
        b_lines = pages_lines.get(biblio_idx, [])
        if b_lines and b_lines[0].isdigit():
            biblio_has_arabic_page = True
        b_txt = pages_text.get(biblio_idx, "").upper()
        if len(b_lines) > 1 and any(k in b_lines[1].upper() for k in ["DALAM ANGKA", "IN FIGURES", "BIBLIOGRAPHY", "DAFTAR PUSTAKA", "DISTRICT"]):
            biblio_has_rt = True
        elif any(k in b_txt for k in ["DALAM ANGKA", "IN FIGURES"]) and len(b_lines) >= 3:
            biblio_has_rt = True

    last_page_text = pages_text.get(num_pages - 1, "")
    last_page_obj = doc[-1] if num_pages > 0 else None
    kover_belakang_errors = []
    if str(num_pages) in last_page_text or str(num_pages - 1) in last_page_text:
        kover_belakang_errors.append(f'Terdapat kebocoran nomor halaman "{num_pages}" pada kover belakang. Kover belakang dilarang memuat nomor halaman apapun.')
    if 'XXXXX' in last_page_text or 'xxxxx' in last_page_text:
        kover_belakang_errors.append('Terdapat teks placeholder template "XXXXX Dalam Angka 2024" yang belum dibersihkan pada kover belakang.')

    # ── OCR FALLBACK UNTUK KOVER BELAKANG (Jika kover berupa gambar raster/flattened) ──
    kb_ocr_items = []
    kb_ocr_text = ""
    if num_pages > 0 and HAVE_CV2:
        kb_check = last_page_text.lower()
        if len(last_page_text.strip()) < 120 or '@' not in kb_check or not any(k in kb_check for k in ['telp', 'telepon', 'phone', '(0']):
            try:
                from rapidocr_onnxruntime import RapidOCR
                if not hasattr(extract_pdf_metadata, '_rapid_engine'):
                    extract_pdf_metadata._rapid_engine = RapidOCR()
                engine = extract_pdf_metadata._rapid_engine
                
                pix_kb = last_page_obj.get_pixmap(dpi=150)
                img_kb = cv2.imdecode(np.frombuffer(pix_kb.tobytes('png'), np.uint8), cv2.IMREAD_COLOR)
                h_kb, w_kb = img_kb.shape[:2]
                
                ocr_res, _ = engine(img_kb)
                if ocr_res:
                    for item in ocr_res:
                        box, txt_ocr, conf = item
                        kb_ocr_items.append((box, txt_ocr, conf))
                    kb_ocr_text = " ".join([it[1] for it in kb_ocr_items])
            except Exception as e_ocr:
                print(f"[OCR Back Cover] Warning: {e_ocr}")

    combined_kb_text = (last_page_text + " " + kb_ocr_text).strip()
    has_slogan_kb = ('DATA MENCERDASKAN' in combined_kb_text.upper() or 'MENCERDASKAN BANGSA' in combined_kb_text.upper())
    has_berakhlak_kb = ('BERAKHLAK' in combined_kb_text.upper() or 'BerAKHLAK' in combined_kb_text or 'BANGGA MELAYANI' in combined_kb_text.upper() or 'SENSUS EKONOMI' in combined_kb_text.upper())
    logo_cluster_pos_kb = None  # 'top_right', 'top_left', 'bottom_right', 'bottom_left', or None

    if logo_cluster_pos_kb is None and kb_ocr_items:
        for box, txt_ocr, conf in kb_ocr_items:
            if any(k in txt_ocr.upper() for k in ['BERAKHLAK', 'SENSUS', 'BANGGA']):
                cx = sum([pt[0] for pt in box]) / (4.0 * w_kb)
                cy = sum([pt[1] for pt in box]) / (4.0 * h_kb)
                if cy < 0.35:
                    logo_cluster_pos_kb = 'top_left' if cx < 0.48 else 'top_right'
                else:
                    logo_cluster_pos_kb = 'bottom_left' if cx < 0.48 else 'bottom_right'
                has_berakhlak_kb = True
                break

    # 1. Cek layer teks kover belakang jika tersedia

    if last_page_obj:
        try:
            pw, ph = last_page_obj.rect.width, last_page_obj.rect.height
            blocks = last_page_obj.get_text('blocks')
            for b in blocks:
                txt = b[4].upper()
                txt_raw = b[4]
                if 'BERAKHLAK' in txt or 'BANGGA MELAYANI' in txt or 'SENSUS EKONOMI' in txt:
                    by_mid = (b[1] + b[3]) / 2.0
                    if by_mid < ph * 0.35:
                        bx_mid = (b[0] + b[2]) / 2.0
                        if bx_mid < pw * 0.48:
                            logo_cluster_pos_kb = 'top_left'
                        else:
                            logo_cluster_pos_kb = 'top_right'
                        has_berakhlak_kb = True
                
                # Cek saltik nama satker bahasa Inggris di kover belakang
                if re.search(r'\bBPS-STATISTIC\b', txt_raw, re.I) and not re.search(r'\bBPS-STATISTICS\b', txt_raw, re.I):
                    kover_belakang_errors.append(
                        'Kesalahan penulisan nama satker BPS bahasa Inggris pada kover belakang: Tertulis "BPS-STATISTIC" (kurang huruf "s"). '
                        'Sesuai Pedoman Pembuatan Publikasi BPS 2023 (hal. 64), standar penulisan resmi adalah "BPS-Statistics [Regency/Municipality]".'
                    )
                if re.search(r'\bBPS\s+of\s+', txt_raw, re.I):
                    kover_belakang_errors.append(
                        'Kesalahan penulisan nama satker BPS bahasa Inggris pada kover belakang: Tertulis "BPS of [Regency]". '
                        'Sesuai Pedoman Pembuatan Publikasi BPS 2023 (hal. 64), standar penulisan resmi adalah "BPS-Statistics [Regency/Municipality]".'
                    )
                if re.search(r'\bBPS-STATISTICS\s+OF\b', txt_raw, re.I):
                    kover_belakang_errors.append(
                        'Kesalahan penulisan nama satker BPS bahasa Inggris pada kover belakang: Tertulis "BPS-STATISTICS OF". '
                        'Sesuai Pedoman Pembuatan Publikasi BPS 2023 (hal. 64), penulisan resmi tidak menggunakan kata penghubung "OF".'
                    )
        except Exception as e_txt:
            pass

    # 2. Jika teks layer kosong/grafis raster (seperti ekspor InDesign/Canva), gunakan verifikasi Computer Vision
    if HAVE_CV2 and num_pages > 0:
        try:
            if not last_page_obj:
                last_page_obj = doc[-1]
            pix = last_page_obj.get_pixmap(dpi=150)
            img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
            if pix.n == 4:
                img = cv2.cvtColor(img, cv2.COLOR_RGBA2BGR)
            elif pix.n == 1:
                img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
            elif pix.n == 3:
                img = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)

            h, w = img.shape[:2]
            # A. Cek visual slogan DATA MENCERDASKAN BANGSA di area tengah (y 25%-65%, x 15%-85%)
            if not has_slogan_kb:
                mid = img[int(h*0.25):int(h*0.65), int(w*0.15):int(w*0.85)]
                gray_mid = cv2.cvtColor(mid, cv2.COLOR_BGR2GRAY)
                dark_ratio = np.sum(gray_mid < 75) / gray_mid.size
                light_ratio = np.sum(gray_mid > 210) / gray_mid.size
                edges = cv2.Canny(gray_mid, 50, 150)
                edge_ratio = np.sum(edges > 0) / edges.size
                
                if (
                    (dark_ratio > 0.02 and edge_ratio > 0.01) or
                    (light_ratio > 0.02 and light_ratio < 0.70 and edge_ratio > 0.01) or
                    (edge_ratio > 0.02)
                ):
                    has_slogan_kb = True

            # B. Cek visual klaster logo resmi (Sensus, BerAKHLAK, tagar #BanggaMelayaniBangsa) di area atas (y: 1%-28%)
            if logo_cluster_pos_kb is None:
                top_area = img[int(h*0.01):int(h*0.28), :]
                top_l = top_area[:, :int(w*0.50)]
                top_r = top_area[:, int(w*0.50):]

                # Deteksi warna merah/crimson BerAKHLAK & hashtag #bangga melayani bangsa
                hsv_l = cv2.cvtColor(top_l, cv2.COLOR_BGR2HSV)
                hsv_r = cv2.cvtColor(top_r, cv2.COLOR_BGR2HSV)

                mask_crim_l = (((hsv_l[:,:,0] > 168) | ((hsv_l[:,:,0] < 10) & (hsv_l[:,:,1] > 90))) & (hsv_l[:,:,1] > 60) & (hsv_l[:,:,2] > 60)).astype(np.uint8)
                mask_crim_r = (((hsv_r[:,:,0] > 168) | ((hsv_r[:,:,0] < 10) & (hsv_r[:,:,1] > 90))) & (hsv_r[:,:,1] > 60) & (hsv_r[:,:,2] > 60)).astype(np.uint8)

                def _find_letter_blobs(mask, min_x=None, max_x=None):
                    cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                    blobs = []
                    for c in cnts:
                        area = cv2.contourArea(c)
                        x, y, cw, ch = cv2.boundingRect(c)
                        if 25 < area < 2500 and 6 < ch < 65 and 3 < cw < 75:
                            cx, cy = x + cw/2, y + ch/2
                            if min_x and cx < min_x:
                                continue
                            if max_x and cx > max_x:
                                continue
                            blobs.append((cx, cy, area))
                    return blobs

                blobs_l = _find_letter_blobs(mask_crim_l, min_x=int(w*0.04), max_x=int(w*0.48))
                blobs_r = _find_letter_blobs(mask_crim_r, min_x=int(w*0.02), max_x=int(w*0.46))

                def _has_horizontal_run(blobs):
                    for b1 in blobs:
                        collinear = [b for b in blobs if abs(b[1] - b1[1]) <= 14]
                        if len(collinear) >= 4:
                            xs = [b[0] for b in collinear]
                            if max(xs) - min(xs) > 40:
                                return True
                    return False

                has_run_l = _has_horizontal_run(blobs_l)
                has_run_r = _has_horizontal_run(blobs_r)

                gray_l = cv2.cvtColor(top_l, cv2.COLOR_BGR2GRAY)
                gray_r = cv2.cvtColor(top_r, cv2.COLOR_BGR2GRAY)
                dark_l = np.sum(gray_l < 90)
                dark_r = np.sum(gray_r < 90)
                edges_l = np.sum(cv2.Canny(gray_l, 50, 150) > 0)
                edges_r = np.sum(cv2.Canny(gray_r, 50, 150) > 0)
                white_l = np.sum(gray_l > 220)
                white_r = np.sum(gray_r > 220)

                score_r = (1 if has_run_r else 0) * 10 + (2 if dark_r > 1000 else 0) + (2 if edges_r > 2500 else 0) + (2 if white_r > 2500 else 0)
                score_l = (1 if has_run_l else 0) * 10 + (2 if dark_l > 1000 else 0) + (2 if edges_l > 2500 else 0) + (2 if white_l > 2500 else 0)

                if score_l >= 10 or (score_l >= 4 and score_r == 0):
                    logo_cluster_pos_kb = 'top_left'
                    has_berakhlak_kb = True
                elif score_r >= 10 or (score_r >= 4 and score_l == 0):
                    logo_cluster_pos_kb = 'top_right'
                    has_berakhlak_kb = True
                elif score_r > score_l and score_r >= 2:
                    logo_cluster_pos_kb = 'top_right'
                    has_berakhlak_kb = True
                elif score_l > score_r and score_l >= 2:
                    logo_cluster_pos_kb = 'top_left'
                    has_berakhlak_kb = True
        except Exception as e_kb:
            print(f"[CV Back Cover] Visual check warning: {e_kb}")

    if not has_slogan_kb:
        kover_belakang_errors.append(
            'Slogan "DATA MENCERDASKAN BANGSA / DATA ENLIGHTEN THE NATION" tidak ditemukan di kover belakang. '
            'Sesuai Pedoman Pembuatan Publikasi BPS 2023 (hal. 64), slogan wajib dicantumkan pada bagian tengah kover belakang secara proporsional.'
        )

    if logo_cluster_pos_kb == 'top_left':
        kover_belakang_errors.append(
            'Kesalahan tata letak klaster logo resmi pada kover belakang: Logo Sensus BPS, slogan BerAKHLAK, dan tagar #BanggaMelayaniBangsa '
            'terpasang di pojok kiri atas. Sesuai Pedoman Pembuatan Publikasi BPS 2023 (hal. 64) dan Template Baku KCDA 2026, '
            'klaster logo tersebut WAJIB diposisikan di pojok kanan atas kover belakang.'
        )
    elif logo_cluster_pos_kb in ['bottom_right', 'bottom_left']:
        kover_belakang_errors.append(
            'Kesalahan tata letak klaster logo resmi pada kover belakang: Logo Sensus BPS, slogan BerAKHLAK, dan tagar #BanggaMelayaniBangsa '
            f'terpasang di area {"bawah kanan" if logo_cluster_pos_kb == "bottom_right" else "bawah kiri"}. Sesuai Pedoman Pembuatan Publikasi BPS 2023 (hal. 64) dan Template Baku KCDA 2026, '
            'klaster logo tersebut WAJIB diposisikan di pojok kanan atas kover belakang.'
        )
    elif not has_berakhlak_kb or logo_cluster_pos_kb is None:
        kover_belakang_errors.append(
            'Logo Sensus BPS, slogan BerAKHLAK, dan tagar #BanggaMelayaniBangsa tidak ditemukan pada kover belakang. '
            'Sesuai Pedoman Pembuatan Publikasi BPS 2023 (hal. 64), klaster logo resmi wajib ditampilkan di pojok kanan atas '
            'kover belakang secara proporsional.'
        )

    # 3. Cek posisi horizontal barcode pada kover belakang (wajib pojok kanan bawah jika ada)
    back_cover_barcode_pos_wrong = None
    if num_pages > 0:
        try:
            last_p_obj = doc[-1]
            pw_kb, ph_kb = last_p_obj.rect.width, last_p_obj.rect.height
            for b in last_p_obj.get_text('blocks'):
                txt_b = b[4].strip()
                if any(k in txt_b.upper() for k in ['BARCODE', '977', '978']):
                    bx = (b[0] + b[2]) / 2.0
                    if bx < pw_kb * 0.45:
                        back_cover_barcode_pos_wrong = "kiri"
                        break
            if back_cover_barcode_pos_wrong is None:
                for info in last_p_obj.get_image_info():
                    bb = info.get('bbox')
                    if bb and bb[1] > ph_kb * 0.60:
                        img_w = bb[2] - bb[0]
                        img_h = bb[3] - bb[1]
                        if 35 < img_w < 180 and 20 < img_h < 120:
                            bc_x = (bb[0] + bb[2]) / 2.0
                            if bc_x < pw_kb * 0.45:
                                # Verifikasi apakah gambar ini benar-benar barcode (bukan logo BPS)
                                try:
                                    clip_rect = fitz.Rect(bb)
                                    pix_clip = last_p_obj.get_pixmap(clip=clip_rect, dpi=150)
                                    c_img = cv2.imdecode(np.frombuffer(pix_clip.tobytes('png'), np.uint8), cv2.IMREAD_COLOR)
                                    if c_img is not None:
                                        b_det = cv2.barcode.BarcodeDetector()
                                        ret_bc, _ = b_det.detect(c_img)
                                        if ret_bc:
                                            back_cover_barcode_pos_wrong = "kiri"
                                            break
                                except Exception:
                                    pass
        except Exception:
            pass

    if back_cover_barcode_pos_wrong == 'kiri':
        kover_belakang_errors.append(
            'Kesalahan tata letak barcode pada kover belakang: Barcode ISBN/ISSN/Nomor Publikasi diletakkan di sebelah kiri bawah. '
            'Sesuai Pedoman Pembuatan Publikasi BPS 2023 (hal. 64) dan Template Baku KCDA 2026, barcode WAJIB diletakkan di pojok kanan bawah kover belakang.'
        )

    # 4. Larangan penambahan abstraksi pada kover belakang (Instrumen Row 204)
    back_cover_has_abstraction = False
    if num_pages > 0:
        p_last_txt = pages_text.get(num_pages - 1, "")
        if "ABSTRAKSI" in p_last_txt.upper() or "ABSTRAK" in p_last_txt.upper():
            back_cover_has_abstraction = True
        else:
            for block in doc[num_pages - 1].get_text("blocks"):
                btxt = block[4].strip()
                if len(btxt) > 180 and not any(k in btxt.upper() for k in ["BADAN PUSAT STATISTIK", "DATA MENCERDASKAN BANGSA", "JL.", "JALAN", "HTTP", "BPS.GO.ID", "TELEPON", "E-MAIL"]) and btxt.count('.') >= 2:
                    back_cover_has_abstraction = True
                    break
    if back_cover_has_abstraction:
        kover_belakang_errors.append(
            'Pelanggaran penambahan abstraksi pada kover belakang: Ditemukan teks narasi/abstraksi pada kover belakang. '
            'Sesuai Pedoman Pembuatan Publikasi BPS 2023 hal. 64 & Instrumen baris 204, tidak diperkenankan menambahkan teks abstraksi/sinopsis pada kover belakang buku BPS.'
        )

    # 5. Cek halaman kosong sebelum kover belakang (Instrumen Row 205)
    pre_back_cover_has_leak = False
    if num_pages >= 3:
        p_pre = pages_text.get(num_pages - 2, "").strip()
        p_pre_no_web = re.sub(r'https?://\S+', '', p_pre).strip()
        if any(k in p_pre.upper() for k in ["DALAM ANGKA", "IN FIGURES", "BAB "]) and len(p_pre_no_web) < 100:
            pre_back_cover_has_leak = True
    if pre_back_cover_has_leak:
        kover_belakang_errors.append(
            f'Running title atau teks tercetak pada lembar kosong sebelum kover belakang (halaman fisik {num_pages-1}). '
            f'Sesuai Pedoman BPS 2023 hal. 64 & Instrumen baris 205, halaman kosong sebelum kover belakang wajib bersih tanpa running title dan nomor halaman.'
        )

    # 6. Cek kelengkapan identitas kontak BPS penerbit pada kover belakang (Instrumen Row 210 Poin 4)
    back_cover_missing_contact = []
    if num_pages > 0:
        kb_txt = combined_kb_text.lower()
        if not re.search(r'\bbps\.go\.id\b', kb_txt):
            back_cover_missing_contact.append('alamat homepage/website resmi (bps.go.id)')
        if not (re.search(r'[\w\.-]+@bps\.go\.id', kb_txt) or '@' in kb_txt):
            back_cover_missing_contact.append('alamat e-mail resmi')
        if not any(k in kb_txt for k in ['telp', 'telepon', 'phone', '(0']):
            back_cover_missing_contact.append('nomor telepon resmi')
    if back_cover_missing_contact:
        missing_items_str = ", ".join(back_cover_missing_contact)
        kover_belakang_errors.append(
            f'Identitas kontak penerbit BPS pada kover belakang belum lengkap: Komponen {missing_items_str} tidak ditemukan. '
            f'Sesuai Pedoman Pembuatan Publikasi BPS 2023 hal. 64 & Instrumen baris 210 poin 4, alamat BPS penerbit pada kover belakang '
            f'wajib dilengkapi dengan kode pos, nomor telepon, homepage situs web, dan alamat email resmi.'
        )

    # ── ADVANCED COMPUTER VISION AUDIT ──
    cv_audit = {}
    if cv_auditor:
        try:
            cv_audit = cv_auditor.audit_document(
                doc, region_name=region_name, year=pub_year, catalog_no=catalog_no, issn_val=issn_val
            )
            if cv_audit.get("cover_visual"):
                cv_cov = cv_audit["cover_visual"]
                if cv_cov.get("has_colon_on_issn"):
                    cover_has_colon = True
                if cv_cov.get("has_space_before_colon_catalog"):
                    cover_catalog_space_colon = True
                if cv_cov.get("has_template_letter_a"):
                    cover_has_letter_a = True
                if "has_english_title" in cv_cov:
                    cover_has_english_title = cv_cov["has_english_title"]
                if "title_english_is_italic" in cv_cov:
                    cover_title_is_italic = cv_cov["title_english_is_italic"]
            if cv_audit.get("hju_visual"):
                cv_hju = cv_audit["hju_visual"]
                if cv_hju.get("has_colon_on_issn"):
                    p3_issn_has_colon = True
                if cv_hju.get("has_space_before_colon_catalog"):
                    hju_catalog_space_colon = True
                p3_has_image = cv_hju.get("has_illustration_background", False)
                p3_logo_monochrome = cv_hju.get("logo_is_monochrome", False)
                if "has_english_title" in cv_hju:
                    hju_has_english_title = cv_hju["has_english_title"]
                if "title_english_is_italic" in cv_hju:
                    hju_title_is_italic = cv_hju["title_english_is_italic"]
        except Exception as e:
            print(f"[CV Auditor] Error in audit_document: {e}")

    # ── DETEKSI LONCATAN NOMOR HALAMAN CETAK (PAGE JUMP DETECTOR) ──
    def _extract_printed_page(page_obj):
        rect = page_obj.rect
        top_txt = page_obj.get_text('text', clip=fitz.Rect(0, 0, rect.width, 45)).strip()
        bot_txt = page_obj.get_text('text', clip=fitz.Rect(0, rect.height-45, rect.width, rect.height)).strip()
        
        # 1. Prioritas Utama: baris yang hanya berisi angka murni nomor halaman (termasuk di baris paling bawah footer)
        for txt_area in [bot_txt, top_txt]:
            for l_str in reversed(txt_area.splitlines()):
                l_str = l_str.strip()
                if re.match(r'^\d{1,3}$', l_str) and int(l_str) < 300:
                    return int(l_str)
                    
        # 2. Prioritas Kedua: angka di awal atau akhir baris, tetapi bukan bagian dari tahun/running title
        for txt_area in [bot_txt, top_txt]:
            for l_str in reversed(txt_area.splitlines()):
                l_str = l_str.strip()
                if '.' in l_str or '/' in l_str or '-' in l_str:
                    continue
                if any(k in l_str.upper() for k in ['FIGURE', 'ANGKA', 'BPS', 'HTTP', 'HTTPS', 'DISTRICT', 'KECAMATAN']):
                    continue
                m_lead = re.match(r'^(\d{1,3})(?:\s+[A-Za-z]|$)', l_str)
                if m_lead and int(m_lead.group(1)) < 300 and int(m_lead.group(1)) != int(pub_year if str(pub_year).isdigit() else 2026):
                    return int(m_lead.group(1))
                m_trail = re.search(r'(?:^|\s+)(\d{1,3})$', l_str)
                if m_trail and int(m_trail.group(1)) < 300 and int(m_trail.group(1)) != int(pub_year if str(pub_year).isdigit() else 2026):
                    return int(m_trail.group(1))
        return None

    printed_pages_list = []
    start_p = (p_arab_start - 1) if ('p_arab_start' in locals() and p_arab_start > 0) else 20
    for p_idx in range(max(2, start_p), num_pages - 1):
        num_found = _extract_printed_page(doc[p_idx])
        if num_found is not None:
            printed_pages_list.append((p_idx + 1, num_found))

    page_number_jumps = []
    for idx_p in range(1, len(printed_pages_list)):
        p_prev, num_prev = printed_pages_list[idx_p - 1]
        p_curr, num_curr = printed_pages_list[idx_p]
        phys_diff = p_curr - p_prev
        expected_num = num_prev + phys_diff
        if num_curr != expected_num and abs(num_curr - expected_num) >= 2:
            page_number_jumps.append({
                "phys_curr": p_curr,
                "num_curr": num_curr,
                "expected_num": expected_num,
                "phys_prev": p_prev,
                "num_prev": num_prev
            })

    doc.close()

    return {
        "title": pub_title,
        "region": region_name,
        "kabupaten": kabupaten_name,
        "year": pub_year,
        "is_kabupaten": is_kabupaten,
        "total_pages": num_pages,
        "catalog": catalog_no,
        "catalog_slash": catalog_slash,
        "issn": issn_val,
        "team_issn": team_issn,
        "pub_num": pub_num,
        "pub_num_empty": pub_num_empty,
        "pub_num_wrong_year": pub_num_wrong_year,
        "catalog_roman": catalog_roman,
        "catalog_arab": catalog_arab,
        "uses_hal_not_hlm": uses_hal_not_hlm,
        "space_before_slash_pages": space_before_slash_pages,
        "space_before_slash_label_pages": space_before_slash_label_pages,
        "space_before_slash_unit_pages": space_before_slash_unit_pages,
        "space_around_plus_pages": space_around_plus_pages,
        "copyright_space_after_symbol": copyright_space_after_symbol,
        "book_size_format_error": book_size_format_error,
        "divider_has_page_num": divider_has_page_num,
        "bps_abbreviated_id": bps_abbreviated_id,
        "bps_of_en": bps_of_en,
        "copyright_typo_regency": copyright_typo_regency,
        "is_serial": is_serial,
        "catalog_has_issn_line": catalog_has_issn_line,
        "catalog_issn_format_ok": catalog_issn_format_ok,
        "catalog_pages_mismatch": catalog_pages_mismatch,
        "catalog_label_errors": catalog_label_errors,
        "cover_catalog_space_colon": cover_catalog_space_colon,
        "cover_has_colon": cover_has_colon,
        "cover_has_issn": cover_has_issn,
        "cover_has_template_leak": cover_has_template_leak,
        "cover_has_letter_a": cover_has_letter_a,
        "cover_has_english_title": cover_has_english_title,
        "cover_title_is_italic": cover_title_is_italic,
        "hju_has_english_title": hju_has_english_title,
        "hju_title_is_italic": hju_title_is_italic,
        "catalog_has_english_title": catalog_has_english_title,
        "catalog_bilingual_missing": catalog_bilingual_missing,
        "cover_is_bilingual": cover_is_bilingual,
        "p2_has_leak": p2_has_leak,
        "p3_has_image": p3_has_image,
        "p3_text_full": p3_text_full,
        "p3_has_issn": p3_has_issn,
        "p3_issn_has_colon": p3_issn_has_colon,
        "hju_catalog_space_colon": hju_catalog_space_colon,
        "p3_has_rt": p3_has_rt,
        "team_issn_has_colon": team_issn_has_colon,
        "team_issn_missing": team_issn_missing,
        "team_title_nonstandard": team_title_nonstandard,
        "team_writers_merged": team_writers_merged,
        "degree_mismatch": degree_mismatch,
        "jabatan_errors": jabatan_errors,
        "preface_year": preface_year,
        "preface_has_running_title": preface_has_running_title,
        "preface_roman_missing": preface_roman_missing,
        "preface_has_toc_leak": preface_has_toc_leak,
        "jabatan_penanda_id_singkat": jabatan_penanda_id_singkat,
        "jabatan_penanda_en_chief": jabatan_penanda_en_chief,
        "preface_en_errors": preface_en_errors,
        "preface_typo_spasi": preface_typo_spasi,
        "preface_typo_dash": preface_typo_dash,
        "toc_issn_missing": toc_issn_missing,
        "toc_has_running_title": toc_has_running_title,
        "toc_chapters_point_to_dividers": toc_chapters_point_to_dividers,
        "toc_errors": toc_errors,
        "daftar_tabel_running_title": daftar_tabel_running_title,
        "daftar_gambar_placeholder": daftar_gambar_placeholder,
        "dummy_figures": dummy_figures,
        "dummy_camera_detected": len(dummy_figures) > 0,
        "placeholder_pages": [df[2] for df in dummy_figures],
        "even_start_chapters": even_start_chapters,
        "divider_has_running_title": divider_has_running_title,
        "empty_ulasan_chapters": empty_ulasan_chapters,
        "table_findings": table_findings,
        "rt_odd_wrong": rt_odd_wrong,
        "rt_even_wrong": rt_even_wrong,
        "has_daftar_pustaka": has_daftar_pustaka,
        "kover_belakang_errors": kover_belakang_errors,
        "jabatan_tips": jabatan_tips,
        "catalog_bps_abbreviations": catalog_bps_abbreviations,
        "page_number_jumps": page_number_jumps,
        # ── NEW: Cross-page consistency fields ──
        "p3_has_bg_illustration": p3_has_image,
        "p3_logo_monochrome": p3_logo_monochrome,
        "space_before_colon_pages": space_before_colon_pages,
        "preface_year_mismatch": preface_year_mismatch,
        "preface_titimangsa_mismatch": preface_titimangsa_mismatch,
        "toc_preface_not_italic": toc_preface_not_italic,
        "toc_figures_has_dots": toc_figures_has_dots,
        "penjelasan_english_not_italic": penjelasan_english_not_italic,
        "toc_figure_idx": toc_figure_idx,
        "issn_cross_page_inconsistent": issn_cross_page_inconsistent,
        "issn_cross_page_details": issn_cross_page_details,
        "issn_checksum_invalid": issn_checksum_invalid,
        "issn_registry_mismatch": issn_registry_mismatch,
        "issn_correct_from_registry": issn_correct_from_registry,
        "issn_per_page": issn_per_page,
        "all_found_issns": list(all_found_issns),
        "katalog_cross_page_inconsistent": katalog_cross_page_inconsistent,
        "wrong_year_refs": wrong_year_refs,
        "global_typos": global_typos,
        "roman_page_mismatch": roman_page_mismatch,
        "district_mismatch_info": district_mismatch_info,
        "cv_audit": cv_audit,
        # ── Deteksi Template, Placeholder & Crosscheck Khusus ──
        "pub_level": pub_level,
        "cover_issn_text": cover_issn_text,
        "p3_issn_text": p3_issn_text,
        "hju_idx": actual_hju_p,
        "catalog_idx": catalog_idx,
        "team_idx": team_idx,
        "preface_idx": preface_idx,
        "toc_idx": toc_idx,
        "cover_issn_placeholder": cover_issn_placeholder,
        "cover_catalog_placeholder": cover_catalog_placeholder,
        "cover_volume_placeholder": cover_volume_placeholder,
        "cover_agency_dual_option": cover_agency_dual_option,
        "p3_is_template": p3_is_template,
        "p3_typo_kecamatan": p3_typo_kecamatan,
        "catalog_volume_empty": catalog_volume_empty,
        "catalog_no_empty": catalog_no_empty,
        "catalog_issn_empty": catalog_issn_empty,
        "catalog_pages_placeholder": catalog_pages_placeholder,
        "catalog_illus_source_empty": catalog_illus_source_empty,
        "catalog_agency_dual_option": catalog_agency_dual_option,
        "team_is_template": team_is_template,
        "preface_other_districts": preface_other_districts,
        "preface_signature_missing": preface_signature_missing,
        "toc_volume_empty": toc_volume_empty,
        "toc_bookmark_error": toc_bookmark_error,
        "toc_issn_placeholder": toc_issn_placeholder,
        "daftar_gambar_has_xxx": daftar_gambar_has_xxx,
        "daftar_gambar_unnecessary": daftar_gambar_unnecessary,
        "lorem_ipsum_pages": lorem_ipsum_pages,
        "yyyyy_running_title_pages": yyyyy_running_title_pages,
        "missing_chapter_dividers": missing_chapter_dividers,
        "xxx_figures": xxx_figures,
        "empty_peta_wilayah": empty_peta_wilayah,
        "empty_grafik_jarak": empty_grafik_jarak,
        "raw_template_info": raw_template_info,
        "cover_publisher_not_bilingual": cover_publisher_not_bilingual,
        "cover_publisher_not_arial_bi": cover_publisher_not_arial_bi,
        "catalog_issn_colon_error": catalog_issn_colon_error,
        "catalog_individual_roles": catalog_individual_roles,
        "preface_has_nip": preface_has_nip,
        "team_has_nip": team_has_nip,
        "fig_has_tahun": fig_has_tahun,
        "preface_name_not_bold": preface_name_not_bold,
        "toc_bilingual_slash_error": toc_bilingual_slash_error,
        "biblio_has_template_dots": biblio_has_template_dots,
        # ── Penempatan Halaman Ganjil/Genap & Tata Letak Anatomi ──
        "hju_is_even": hju_is_even,
        "catalog_is_odd": catalog_is_odd,
        "team_is_even": team_is_even,
        "team_merged_with_catalog": team_merged_with_catalog,
        "preface_is_even": preface_is_even,
        "toc_is_even": toc_is_even,
        "toc_table_is_even": toc_table_is_even,
        "toc_figure_is_even": toc_figure_is_even,
        "penjelasan_is_even": penjelasan_is_even,
        "biblio_is_even": biblio_is_even,
        "divider_even_pages": divider_even_pages,
        "cover_catalog_pos_wrong": cover_catalog_pos_wrong,
        "hju_catalog_pos_wrong": hju_catalog_pos_wrong,
        "back_cover_barcode_pos_wrong": back_cover_barcode_pos_wrong,
        "chapter_opening_has_rt": chapter_opening_has_rt,
        # ── Teks Halaman untuk Audit Dwibahasa (Bilingual Compliance) ──
        "team_text": team_text,
        "preface_text": preface_text,
        "preface_en_text": preface_en_text,
        "has_preface_en": (preface_en_idx >= 0) or ("PREFACE" in (preface_text + " " + preface_en_text).upper()),
        "toc_text": toc_text,
        "toc_table_text": pages_text.get(toc_table_idx, "") if toc_table_idx >= 0 else "",
        "toc_figure_text": pages_text.get(toc_figure_idx, "") if toc_figure_idx >= 0 else "",
        "penjelasan_text": pages_text.get(penjelasan_idx, "") if penjelasan_idx >= 0 else "",
        "last_page_text": pages_text.get(num_pages - 1, "") if num_pages > 0 else "",
        "divider_texts": divider_texts,
        "sample_tables": sample_tables,
        # ── Standarisasi Penuh Sesuai Instrumen BPS 2023 (Rows 4-211) ──
        "cover_title_has_tahun_word": cover_title_has_tahun_word,
        "cover_katalog_issn_order_wrong": cover_katalog_issn_order_wrong,
        "hju_katalog_issn_order_wrong": hju_katalog_issn_order_wrong,
        "catalog_roman_is_odd": catalog_roman_is_odd,
        "catalog_pub_no_abbreviated": catalog_pub_no_abbreviated,
        "catalog_numbering_order_wrong": catalog_numbering_order_wrong,
        "toc_subchapter_has_trailing_dot": toc_subchapter_has_trailing_dot,
        "uses_daftar_grafik": uses_daftar_grafik,
        "back_cover_has_abstraction": back_cover_has_abstraction,
        "pre_back_cover_has_leak": pre_back_cover_has_leak,
        "p2_has_leak": p2_has_leak,
        "body_subchapter_has_trailing_dot": body_subchapter_has_trailing_dot,
        "fig_has_trailing_dot": fig_has_trailing_dot,
        "fig_note_has_keterangan": fig_note_has_keterangan,
        "biblio_has_rt": biblio_has_rt,
        "biblio_has_arabic_page": biblio_has_arabic_page,
        "toc_table_has_trailing_dot": toc_table_has_trailing_dot,
        "toc_figure_has_trailing_dot": toc_figure_has_trailing_dot,
        "penjelasan_has_rt": penjelasan_has_rt,
        "team_has_rt": team_has_rt,
        "team_has_page_num": team_has_page_num,
        "uses_daftar_peta": uses_daftar_peta,
        "glosarium_is_even": glosarium_is_even,
        "indeks_is_even": indeks_is_even,
        "lampiran_is_even": lampiran_is_even,
        "section_pages": {
            "kover_depan": 1,
            "hju": (actual_hju_p + 1) if actual_hju_p >= 0 else 3,
            "katalog": (catalog_idx + 1) if catalog_idx >= 0 else 4,
            "tim_penyusun": (team_idx + 1) if team_idx >= 0 else 5,
            "kata_pengantar": (preface_idx + 1) if preface_idx >= 0 else 6,
            "daftar_isi": (toc_idx + 1) if toc_idx >= 0 else 8,
            "daftar_tabel": (toc_table_idx + 1) if toc_table_idx >= 0 else 10,
            "daftar_gambar": (toc_figure_idx + 1) if toc_figure_idx >= 0 else 12,
            "penjelasan_umum": (penjelasan_idx + 1) if penjelasan_idx >= 0 else 14,
            "daftar_pustaka": (biblio_idx + 1) if biblio_idx >= 0 else max(1, num_pages - 1),
            "kover_belakang": num_pages
        }
    }


# ─────────────────────────────────────────────────────────────────────────────
# PHASE 2 — DEFECT STRUCTURING (Exact Anatomi Publikasi BPS from Instrumen)
# ─────────────────────────────────────────────────────────────────────────────

