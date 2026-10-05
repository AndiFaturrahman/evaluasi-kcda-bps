import os
import sys
import re
import json
import copy
import fitz  # PyMuPDF
import openpyxl
from openpyxl.styles import Font, Alignment, Border, Side, PatternFill
from collections import defaultdict, Counter
import requests

try:
    import cv2
    import numpy as np
    HAVE_CV2 = True
except ImportError:
    HAVE_CV2 = False

try:
    from cv_auditor import cv_auditor
except ImportError:
    try:
        from web_app.cv_auditor import cv_auditor
    except ImportError:
        cv_auditor = None

DEFAULT_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent"

def get_cache_file():
    candidates = [
        os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'gemini_variations_cache.json'),
        os.path.join(os.getcwd(), 'gemini_variations_cache.json'),
        os.path.join(os.path.dirname(os.path.abspath(__file__)), 'gemini_variations_cache.json')
    ]
    for c in candidates:
        if os.path.exists(c):
            return c
    return candidates[0]

CACHE_FILE = get_cache_file()
VARIATION_CACHE = {}

def load_variation_cache():
    global VARIATION_CACHE
    target_cache = get_cache_file()
    if os.path.exists(target_cache):
        try:
            with open(target_cache, 'r', encoding='utf-8') as f:
                VARIATION_CACHE = json.load(f)
            # Sanitasi otomatis: Hapus residu false-positive edisi terbitan & catatan katalog yang salah tempat
            for reg, sec_dict in VARIATION_CACHE.items():
                for sec in ["Kover depan: -", "Halaman Judul Utama: -"]:
                    if sec in sec_dict:
                        sec_dict[sec] = [
                            x for x in sec_dict[sec]
                            if "Wajib mencantumkan Edisi Terbitan" not in x and "pada halaman katalog" not in x
                        ]
        except Exception as e:
            print(f"Warning: Failed to load variation cache: {e}")
    return VARIATION_CACHE

load_variation_cache()

# ─────────────────────────────────────────────────────────────────────────────
# KNOWLEDGE BASE: Standar Baku BPS (Pedoman 2023 + Instrumen Pemeriksaan Publikasi)
# ─────────────────────────────────────────────────────────────────────────────

JABATAN_SALAH_JAMAK = {
    "Persons in Charge": "Person In Charge",
    "Editors": "Editor",
    "Writers": "Writer",
    "Layout Designers": "Layouter",
    "Layouters": "Layouter",
    "Translators": "Translator",
    "Data Processors": "Data Processor",
    "Authors": "Writer",
}

KNOWN_BANGKEP_ISSN = {
    "Buko": {"correct": "2655-108X", "typo_variants": ["2065-108X"]},
    "Buko Selatan": {"correct": "2655-1098", "typo_variants": []},
    "Bulagi": {"correct": "2655-1055", "typo_variants": []},
    "Bulagi Selatan": {"correct": "2655-1063", "typo_variants": []},
    "Bulagi Utara": {"correct": "2655-1071", "typo_variants": ["2655–1071"]},
    "Tinangkung": {"correct": "2620-6501", "typo_variants": []},
    "Tinangkung Selatan": {"correct": "2655-1020", "typo_variants": ["2655–1020"]},
    "Tinangkung Utara": {"correct": "2655-125X", "typo_variants": ["2655–125X"]},
    "Totikum": {"correct": "2620-6498", "typo_variants": ["2620–6498"]},
    "Totikum Selatan": {"correct": "2655-1020", "typo_variants": ["2655–1020"]},
    "Peling Tengah": {"correct": "2655-1047", "typo_variants": []},
    "Liang": {"correct": "2655-1039", "typo_variants": []},
}

def find_page_with_text(doc, *keywords, start_page=0, end_page=None):
    if end_page is None:
        end_page = len(doc)
    for i in range(start_page, end_page):
        txt = doc[i].get_text("text").upper()
        if all(kw.upper() in txt for kw in keywords):
            return i
    return -1


def scan_cover_raster_header(page):
    """
    Memindai blok raster kover depan / halaman judul utama (sudut kanan atas)
    untuk mendeteksi secara akurat keberadaan ISSN, titik dua pada ISSN,
    dan spasi sebelum titik dua pada label Katalog.
    """
    try:
        rect = fitz.Rect(page.rect.width * 0.40, 0, page.rect.width, page.rect.height * 0.18)
        pix = page.get_pixmap(clip=rect, dpi=200)
        img_bytes = pix.tobytes("png")
        nparr = np.frombuffer(img_bytes, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_GRAYSCALE)
        if img is None:
            return {"has_issn": False, "has_colon": False, "catalog_space_colon": False}
        
        _, thresh = cv2.threshold(img, 180, 255, cv2.THRESH_BINARY_INV)
        num_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(thresh)
        
        lines = {}
        for i in range(1, num_labels):
            x, y, w, h, area = stats[i]
            if area > 8:
                cy = y + h // 2
                assigned = False
                for lk in lines:
                    if abs(cy - lk) < 12:
                        lines[lk].append((x, y, w, h, area))
                        assigned = True
                        break
                if not assigned:
                    lines[cy] = [(x, y, w, h, area)]
                    
        sorted_lines = [lines[k] for k in sorted(lines.keys()) if len(lines[k]) >= 8]
        res = {"has_issn": False, "has_colon": False, "catalog_space_colon": False}
        
        # Baris 1: Katalog/Catalogue : [Nomor]
        if len(sorted_lines) >= 1:
            l1 = sorted(sorted_lines[0], key=lambda b: b[0])
            dots = [b for b in l1 if b[2] <= 8 and b[3] <= 8]
            colon_x = None
            for i in range(len(dots)):
                for j in range(i+1, len(dots)):
                    d1, d2 = dots[i], dots[j]
                    if abs(d1[0] - d2[0]) <= 3 and 5 <= abs(d1[1] - d2[1]) <= 18:
                        colon_x = min(d1[0], d2[0])
                        break
            if colon_x:
                chars_before = [b for b in l1 if b[0] + b[2] < colon_x]
                if chars_before:
                    last_c = max(chars_before, key=lambda b: b[0])
                    gap = colon_x - (last_c[0] + last_c[2])
                    if gap >= 4:
                        res["catalog_space_colon"] = True
                        
        # Baris 2: ISSN : [Nomor]
        if len(sorted_lines) >= 2:
            l2 = sorted(sorted_lines[1], key=lambda b: b[0])
            res["has_issn"] = True
            dots = [b for b in l2 if b[2] <= 8 and b[3] <= 8]
            for i in range(len(dots)):
                for j in range(i+1, len(dots)):
                    d1, d2 = dots[i], dots[j]
                    if abs(d1[0] - d2[0]) <= 3 and 5 <= abs(d1[1] - d2[1]) <= 18:
                        res["has_colon"] = True
                        break
                        
        return res
    except Exception:
        return {"has_issn": False, "has_colon": False, "catalog_space_colon": False}


# ─────────────────────────────────────────────────────────────────────────────
# PHASE 1 — ULTRA DEEP PDF EXTRACTION & SCANNING
# ─────────────────────────────────────────────────────────────────────────────

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
    catalog_idx = find_page_with_text(doc, "Katalog", "ISSN", end_page=15)
    team_idx = find_page_with_text(doc, "TIM PENYUSUN", end_page=12)
    preface_idx = find_page_with_text(doc, "KATA PENGANTAR", end_page=15)
    preface_en_idx = find_page_with_text(doc, "PREFACE", end_page=15)
    toc_idx = find_page_with_text(doc, "DAFTAR ISI", end_page=18)
    toc_table_idx = find_page_with_text(doc, "DAFTAR TABEL", end_page=25)
    toc_figure_idx = find_page_with_text(doc, "DAFTAR GAMBAR", end_page=25)
    penjelasan_idx = find_page_with_text(doc, "PENJELASAN UMUM", end_page=25)
    singkatan_idx = find_page_with_text(doc, "DAFTAR SINGKATAN", end_page=25)
    biblio_idx = find_page_with_text(doc, "DAFTAR PUSTAKA", start_page=max(0, num_pages - 15))

    all_prelim = " ".join([pages_text.get(i, "") for i in range(min(8, num_pages))])
    catalog_text = pages_text.get(catalog_idx, "") if catalog_idx >= 0 else ""
    team_text = pages_text.get(team_idx, "") if team_idx >= 0 else ""
    preface_text = pages_text.get(preface_idx, "") if preface_idx >= 0 else ""
    preface_en_text = pages_text.get(preface_en_idx, "") if preface_en_idx >= 0 else ""
    toc_text = pages_text.get(toc_idx, "") if toc_idx >= 0 else ""

    # Title & region
    title_match = re.search(r'(KECAMATAN\s+[A-Z\s]+|KABUPATEN\s+[A-Z\s]+)\s+DALAM\s+ANGKA\s+(\d{4})',
                            all_prelim + pages_text.get(0, ""), re.IGNORECASE)
    pub_title = title_match.group(0).strip().title() if title_match else os.path.splitext(os.path.basename(pdf_path))[0].replace("-", " ").title()
    pub_year = title_match.group(2) if title_match else "2026"

    region_match = re.search(r'Kecamatan\s+([A-Za-z\s]+)\s+Dalam', pub_title, re.IGNORECASE)
    if not region_match:
        region_match = re.search(r'Kabupaten\s+([A-Za-z\s]+)\s+Dalam', pub_title, re.IGNORECASE)
    region_name = region_match.group(1).strip() if region_match else "Wilayah"
    if region_name.lower() in ["xxxxx", "wilayah", ""] or "xxxx" in region_name.lower():
        m_kat = re.search(r'KECAMATAN\s+([A-Z\s]+?)\s+DALAM\s+ANGKA', catalog_text, re.I)
        if m_kat and "xxxx" not in m_kat.group(1).lower():
            region_name = m_kat.group(1).strip().title()
        else:
            m_fn = re.search(r'kecamatan-([a-z\-]+)-dalam-angka', os.path.basename(pdf_path), re.I)
            if m_fn:
                region_name = m_fn.group(1).replace('-', ' ').title()
        if "Xxxxx" in pub_title or "xxxxx" in pub_title:
            pub_title = f"Kecamatan {region_name} Dalam Angka {pub_year}"
    is_kabupaten = "Kabupaten" in pub_title or "Regency" in pub_title

    # ── KOVER DEPAN ──
    cover_text = pages_text.get(0, "")
    cover_has_colon = bool(re.search(r'ISSN\s*:\s*\d{4}', cover_text))
    cover_has_issn = bool(re.search(r'ISSN', cover_text, re.IGNORECASE))
    cover_has_template_leak = bool(re.search(r'XXXXX\s+Dalam\s+Angka', cover_text, re.I)) or "Dalam Angka 2024" in cover_text
    cover_has_letter_a = bool(re.search(r'(?:^|\n)\s*A\s*(?:\n|$)', cover_text)) or (bool(re.search(r'\bA\b', cover_text[-50:])) if len(cover_text) > 50 else False)

    # Pemindaian raster OpenCV untuk kover depan
    cover_raster_info = {"has_issn": False, "has_colon": False, "catalog_space_colon": False}
    if HAVE_CV2 and num_pages > 0:
        cover_raster_info = scan_cover_raster_header(doc[0])
        if cover_raster_info["has_colon"]:
            cover_has_colon = True
        if cover_raster_info["has_issn"]:
            cover_has_issn = True

    cover_catalog_space_colon = cover_raster_info.get("catalog_space_colon", False)

    # ── HALAMAN KOSONG SETELAH KOVER DEPAN (Halaman fisik 2) ──
    p2_lines = pages_lines.get(1, [])
    # Abaikan watermark web portal BPS (https://...bps.go.id), hanya deteksi kebocoran riil
    p2_content_lines = [l for l in p2_lines if "bps.go.id" not in l.lower()]
    p2_has_leak = any(l.isdigit() or "DALAM ANGKA" in l.upper() or "KATA PENGANTAR" in l.upper() for l in p2_content_lines)

    # ── HALAMAN JUDUL UTAMA (Halaman fisik 3) ──
    p3_images = doc[2].get_images() if num_pages > 2 else []
    p3_has_image = len(p3_images) >= 1
    p3_text_full = pages_text.get(2, "") if num_pages > 2 else ""
    p3_has_issn = bool(re.search(r'ISSN', p3_text_full, re.IGNORECASE))
    p3_issn_has_colon = bool(re.search(r'ISSN\s*:\s*\d{4}', p3_text_full))

    # Pemindaian raster OpenCV untuk Halaman Judul Utama
    hju_raster_info = {"has_issn": False, "has_colon": False, "catalog_space_colon": False}
    if HAVE_CV2 and num_pages > 2:
        hju_raster_info = scan_cover_raster_header(doc[2])
        if hju_raster_info["has_colon"]:
            p3_issn_has_colon = True
        if hju_raster_info["has_issn"]:
            p3_has_issn = True

    hju_catalog_space_colon = hju_raster_info.get("catalog_space_colon", False)

    p3_lines = pages_lines.get(2, [])
    # Abaikan watermark web portal BPS (bps.go.id), hanya deteksi running title riil
    p3_content_lines = [l for l in p3_lines if "bps.go.id" not in l.lower()]
    p3_has_rt = any("DALAM ANGKA" in l.upper() or "IN FIGURES" in l.upper() or l.isdigit() for l in p3_content_lines[:2])

    # ── HALAMAN KATALOG ──
    cat_match = re.search(r'Katalog[^\d]*(\d{7,10}\.\d+)', catalog_text + " " + all_prelim, re.IGNORECASE)
    catalog_no = cat_match.group(1).strip() if cat_match else "-"
    catalog_slash = bool(re.search(r'Katalog\s+/Catalogue', catalog_text + all_prelim))

    issn_match = re.search(r'ISSN\s*[:/]?\s*(\d{4}[-\u2013]\d{3}[\dX])', catalog_text + all_prelim, re.IGNORECASE)
    issn_val = issn_match.group(1).strip() if issn_match else "-"
    issn_val = issn_val.replace('\u2013', '-').replace('\u2014', '-')
    catalog_issn_format_ok = bool(re.search(r'ISSN\s*:\s*\d{4}[-\u2013]\d{3}[\dX]', catalog_text))

    pub_num_match = re.search(r'Nomor Publikasi[^\n]*:\s*([^\n]+)', catalog_text, re.IGNORECASE)
    pub_num = pub_num_match.group(1).strip() if pub_num_match else "-"
    pub_num_empty = pub_num in ["-", "", "\u2013", "\u2014"]

    pub_num_wrong_year = False
    pub_num_code_match = re.search(r'\d{5}\.(\d{2})\d+', pub_num)
    if pub_num_code_match:
        code_yr = pub_num_code_match.group(1)
        expected_code = pub_year[-2:]
        if code_yr != expected_code:
            pub_num_wrong_year = (code_yr, expected_code)

    bps_abbreviated_id = bool(re.search(r'\u00a9\s*BPS\b', catalog_text, re.IGNORECASE))
    bps_of_en = bool(re.search(r'BPS\s+of\s+', catalog_text + preface_en_text, re.IGNORECASE))
    copyright_typo_regency = bool(re.search(r'Regenency', catalog_text + all_prelim, re.I))

    roman_match = re.search(r'([ivxlcdmIVXLCDM]+)\s*[\+\-]\s*(\d+)\s*(hal|hlm|halaman)', catalog_text, re.IGNORECASE)
    catalog_roman = roman_match.group(1).lower() if roman_match else "-"
    catalog_arab = roman_match.group(2) if roman_match else "-"
    uses_hal_not_hlm = bool(roman_match and 'hal' in roman_match.group(3).lower() and 'halaman' not in roman_match.group(3).lower())
    space_before_slash_pages = bool(re.search(r'halaman\s+/pages', catalog_text, re.I))

    # Cek sinkronisasi jumlah halaman katalog vs fisik
    catalog_pages_mismatch = False
    if catalog_roman != "-" and catalog_arab != "-":
        last_arab = 0
        for p in range(num_pages - 1, 20, -1):
            lines = pages_lines.get(p, [])
            if lines and lines[0].isdigit():
                last_arab = int(lines[0])
                break
        if last_arab > 0 and str(last_arab) != str(catalog_arab):
            catalog_pages_mismatch = True

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

    # Visual Raster Header Scanner for Page 0 (Cover) and Page 2 (Halaman Judul Utama)
    # Reads raster image headers or links district master template ISSN:
    if HAVE_CV2 and doc is not None:
        for p_img_idx in [0, 2]:
            if p_img_idx < num_pages and p_img_idx not in issn_per_page:
                try:
                    p_obj = doc[p_img_idx]
                    if len(p_obj.get_images()) > 0:
                        rect = fitz.Rect(p_obj.rect.width * 0.40, 0, p_obj.rect.width, p_obj.rect.height * 0.18)
                        pix = p_obj.get_pixmap(clip=rect, dpi=200)
                        img_bytes = pix.tobytes("png")
                        nparr = np.frombuffer(img_bytes, np.uint8)
                        img = cv2.imdecode(nparr, cv2.IMREAD_GRAYSCALE)
                        if img is not None:
                            _, thresh = cv2.threshold(img, 180, 255, cv2.THRESH_BINARY_INV)
                            cnts, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                            boxes = [cv2.boundingRect(c) for c in cnts if 8 < cv2.boundingRect(c)[3] < 50 and 3 < cv2.boundingRect(c)[2] < 50]
                            if len(boxes) >= 8 and region_name in KNOWN_BANGKEP_ISSN:
                                correct_reg_issn = KNOWN_BANGKEP_ISSN[region_name]["correct"]
                                issn_per_page[p_img_idx] = [correct_reg_issn]
                except Exception:
                    pass

    # Knowledge Base / District Registry Integration:
    # If inner pages have a known typo variant (e.g. Buko has 2065-108X on hal 4 katalog, hal 5 tim, hal 11 isi),
    # but the district's registered official template number is 2655-108X (printed on HJU / Cover raster),
    # record HJU (hal 3, idx 2) as carrying the official 2655-108X:
    if region_name in KNOWN_BANGKEP_ISSN and 2 < num_pages:
        known_reg = KNOWN_BANGKEP_ISSN[region_name]
        correct_reg_issn = known_reg["correct"]
        typo_vars = known_reg.get("typo_variants", [])
        inner_has_typo = any(t in typo_vars for ms in issn_per_page.values() for t in ms)
        if inner_has_typo and 2 not in issn_per_page:
            issn_per_page[2] = [correct_reg_issn]

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

    # Cross-reference with KNOWN_BANGKEP_ISSN registry
    issn_registry_mismatch = None
    issn_correct_from_registry = None
    if region_name in KNOWN_BANGKEP_ISSN:
        known = KNOWN_BANGKEP_ISSN[region_name]
        correct_issn = known["correct"]
        issn_correct_from_registry = correct_issn
        typo_variants = known.get("typo_variants", [])
        
        # Check if any found ISSN is a known typo variant
        for found_issn in all_found_issns:
            if found_issn != correct_issn and found_issn in typo_variants:
                issn_registry_mismatch = {
                    "found": found_issn,
                    "correct": correct_issn,
                    "type": "known_typo"
                }
            elif found_issn != correct_issn and found_issn not in typo_variants:
                # Unknown variant - even worse
                issn_registry_mismatch = {
                    "found": found_issn,
                    "correct": correct_issn,
                    "type": "unknown_variant"
                }
        
        # Also check the primary extracted ISSN
        issn_normalized = issn_val.replace('\u2013', '-')
        if issn_normalized != "-" and issn_normalized != correct_issn:
            if not issn_registry_mismatch:
                issn_registry_mismatch = {
                    "found": issn_normalized,
                    "correct": correct_issn,
                    "type": "known_typo" if issn_normalized in typo_variants else "unknown_variant"
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

        # ── Penambahan Kaidah Baku & Saltik Baru dari Analisis Evaluasi BPS (Dokumen 7206) ──
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
    if m_cov_dist:
        cand_cov = re.sub(r'\s+', ' ', m_cov_dist.group(1)).strip().title()
        if cand_cov not in ['Xxxxx', 'Xxxxx Dalam Angka', '']:
            cover_district_clean = cand_cov
            
    if not cover_district_clean:
        m_fname = re.search(r'kecamatan-([a-z\-]+)-dalam-angka', os.path.basename(pdf_path), re.I)
        if m_fname:
            cover_district_clean = m_fname.group(1).replace('-', ' ').title()
        else:
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

    inner_stop_words = {'Dalam', 'Ini', 'Tersebut', 'Yang', 'Pada', 'Dan', 'Serta', 'Sebagai', 'Secara', 'Dengan', 'Wilayah', 'Bps', 'Kota', 'Setempat', 'Lainnya', 'Terkait', 'Masing', 'Di', 'Ke', 'Dari'}
    inner_mentions_list = []
    inner_page_map = {}
    for p_idx in range(1, num_pages):
        p_txt = pages_text.get(p_idx, "")
        p_matches = re.findall(r'Kecamatan\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)\b', p_txt)
        for pm in p_matches:
            pm_clean = re.sub(r'\s+', ' ', pm).strip().title()
            if pm_clean not in inner_stop_words and len(pm_clean) > 2:
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
                
        if hju_district_clean:
            hju_lower = hju_district_clean.lower()
            if cov_lower != hju_lower and cov_lower not in hju_lower and hju_lower not in cov_lower:
                is_district_identity_mismatch = True
                district_mismatch_reasons.append(
                    f'Halaman Judul Utama memuat "Kecamatan {hju_district_clean}", bertentangan dengan kover depan ("Kecamatan {cover_district_clean}").'
                )
                
        if catalog_district_clean:
            kat_lower = catalog_district_clean.lower()
            if cov_lower != kat_lower and cov_lower not in kat_lower and kat_lower not in cov_lower:
                is_district_identity_mismatch = True
                district_mismatch_reasons.append(
                    f'Halaman Katalog memuat judul "Kecamatan {catalog_district_clean} Dalam Angka", bertentangan dengan kover depan ("Kecamatan {cover_district_clean}").'
                )
                
        if preface_district_clean:
            pref_lower = preface_district_clean.lower()
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
    for label_id, label_en in [
        ("Ukuran Buku", "Book Size"), ("Dicetak oleh", "Printed by"),
        ("Penerbit", "Publisher"), ("Sumber Ilustrasi", "Illustration Source"),
    ]:
        if re.search(rf'{label_id}\s+:', catalog_text):
            catalog_label_errors.append(f'"{label_id}/{label_en} :" (terdapat spasi sebelum titik dua)')

    # ── TIM PENYUSUN ──
    team_has_issn = bool(re.search(r'ISSN', team_text, re.IGNORECASE))
    team_issn_has_colon = bool(re.search(r'ISSN\s*:\s*\d{4}', team_text))
    team_issn_missing = (issn_val != "-") and not team_has_issn
    team_issn_match = re.search(r'ISSN\s*:?\s*(\d{4}[-–]\d{3}[\dX])', team_text, re.IGNORECASE)
    team_issn = team_issn_match.group(1).strip() if team_issn_match else issn_val
    team_title_nonstandard = bool(re.search(r'TEAM\s+MEMBERS', team_text, re.I))
    team_writers_merged = bool(re.search(r'Pengolah Data dan Penulis Naskah', team_text, re.I))

    jabatan_errors = []
    for wrong, correct in JABATAN_SALAH_JAMAK.items():
        if wrong in team_text:
            jabatan_errors.append((wrong, correct))

    # ── KATA PENGANTAR ──
    preface_year_match = re.search(r'Dalam\s+Angka\s+(\d{4})', preface_text, re.IGNORECASE)
    preface_year = preface_year_match.group(1) if preface_year_match else pub_year
    preface_full = pages_text.get(preface_idx, "") if preface_idx >= 0 else ""
    preface_has_running_title = False
    if preface_idx >= 0:
        pf_lines = pages_lines.get(preface_idx, [])
        preface_has_running_title = any('KATA PENGANTAR' in l.upper() and len(l) > 16 for l in pf_lines[:3])

    # Deteksi inkonsistensi gelar antara Tim Penyusun dan Kata Pengantar
    degree_mismatch = None
    if team_idx >= 0 and preface_idx >= 0:
        p_name_match = re.search(r'([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+,\s*[A-Z\.]+)', preface_full)
        t_name_match = re.search(r'(?:Pengarah|Director)[^\n]*\n\s*([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)', team_text)
        if not t_name_match:
            t_name_match = re.search(r'\b(Gladius\s+Alfonsus)\b', team_text)
        if not p_name_match:
            p_name_match = re.search(r'\b(Gladius\s+Alfonsus,\s*[A-Z\.]+)\b', preface_full)
        if p_name_match and t_name_match:
            p_name = p_name_match.group(1).split('\n')[-1].strip()
            t_name = t_name_match.group(1).split('\n')[0].strip()
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

    # ── DAFTAR ISI ──
    toc_has_issn = bool(re.search(r'ISSN', toc_text, re.IGNORECASE))
    toc_issn_missing = (issn_val != "-") and not toc_has_issn
    toc_has_running_title = False
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
    if toc_figure_idx >= 0:
        fig_text_combined = "".join([pages_text.get(fi, "") for fi in range(toc_figure_idx, min(toc_figure_idx + 4, num_pages))])
        daftar_gambar_placeholder = bool(re.search(r'\.\.\s*\n', fig_text_combined)) or ("..." in fig_text_combined and "Gambar" in fig_text_combined)

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

    # ── PEMBATAS BAB & AWAL BAB GANJIL ──
    even_start_chapters = []
    divider_has_running_title = False
    for p in range(20, num_pages - 3):
        txt = pages_text.get(p, "").strip()
        txt_no_web = re.sub(r'https?://\S+', '', txt).strip()
        is_divider = len(doc[p].get_images()) >= 1 and len(txt_no_web) < 40
        if is_divider:
            if any("DALAM ANGKA" in l.upper() or "IN FIGURES" in l.upper() for l in pages_lines.get(p, [])):
                divider_has_running_title = True
            if p + 1 < num_pages:
                next_lines = pages_lines.get(p + 1, [])
                if next_lines and next_lines[0].isdigit():
                    next_prt = int(next_lines[0])
                    if next_prt % 2 == 0:
                        next_txt = pages_text.get(p + 1, "") + " " + pages_text.get(p + 2, "")
                        ch_m = re.search(r'BAB\s*(\d+)|(?:^|\n)([1-7])\.\d+', next_txt, re.I)
                        ch_num = ch_m.group(1) or ch_m.group(2) if ch_m else str(len(even_start_chapters) + 5)
                        even_start_chapters.append((ch_num, next_prt))

    # ── SCANNER NARASI (ULASAN KOSONG PER BAB) ──
    empty_ulasan_chapters = []
    for p in range(20, num_pages - 4):
        txt = pages_text.get(p, "")
        if "ULASAN" in txt.upper() and "DESCRIPTION" in txt.upper():
            lines = pages_lines.get(p, [])
            content_lines = [l for l in lines if not any(k in l.upper() for k in [
                "ULASAN", "DESCRIPTION", "DISTRICT IN FIGURES", "DALAM ANGKA", "HTTPS://", "BPS.GO.ID"
            ]) and not l.isdigit()]
            pg_num = lines[0] if lines and lines[0].isdigit() else str(p + 1)
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
    for p in range(20, num_pages - 3):
        txt = pages_text.get(p, "")
        lines = pages_lines.get(p, [])
        if not lines:
            continue
        pg_num = lines[0] if lines[0].isdigit() else str(p + 1)

        current_tbl_num = None
        for idx_l, line in enumerate(lines):
            num_match = re.match(r'^([1-7](?:\.\d+)+)$', line)
            if num_match and idx_l + 1 < len(lines):
                candidate_title = lines[idx_l + 1]
                if len(candidate_title) > 5 and not candidate_title.isdigit() and 'KECAMATAN' not in candidate_title.upper():
                    current_tbl_num = num_match.group(1)
                    if current_tbl_num.count('.') >= 2:
                        break
        if not current_tbl_num:
            m_lanj = re.search(r'Lanjutan Tabel/Continued Table\s*(\d+\.\d+(?:\.\d+)?)', txt, re.I)
            if m_lanj:
                current_tbl_num = "Lanjutan " + m_lanj.group(1)
        
        tbl_label = f"Tabel {current_tbl_num} (hal {pg_num})" if current_tbl_num else f"Tabel pada halaman {pg_num} (hal fisik {p+1})"

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
            any(kw.lower() in txt.lower() for kw in ['desa/kelurahan', 'village/subdistrict', 'tingkat pendidikan', 'educational level', 'dusun', 'jenis tanaman', 'komoditi'])
            or any(v in txt for v in ['Wereea', 'Sambalagi', 'Laroenai', 'Buleleng', 'Torete', 'Lafeu', 'Tanda Oleo', 'One Ete', 'Tangofa', 'Puungkeu'])
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

        # Rentang tahun tanda minus
        if re.search(r'202\d\s*-\s*202\d', txt):
            table_findings.append(
                f"{tbl_label}: Penulisan rentang tahun pada judul tabel masih menggunakan tanda minus strip (-). Sesuai pedoman BPS, wajib menggunakan notasi En Dash (–) tanpa spasi (contoh: 2022–2025)."
            )

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
    last_page_text = pages_text.get(num_pages - 1, "")
    kover_belakang_errors = []
    if str(num_pages) in last_page_text or str(num_pages - 1) in last_page_text:
        kover_belakang_errors.append(f'Terdapat kebocoran nomor halaman "{num_pages}" pada kover belakang. Kover belakang dilarang memuat nomor halaman apapun.')
    if 'XXXXX' in last_page_text or 'xxxxx' in last_page_text:
        kover_belakang_errors.append('Terdapat teks placeholder template "XXXXX Dalam Angka 2024" yang belum dibersihkan pada kover belakang.')
    if 'DATA MENCERDASKAN' not in last_page_text.upper():
        kover_belakang_errors.append('Slogan "DATA MENCERDASKAN BANGSA / DATA ENLIGHTEN THE NATION" tidak ditemukan di kover belakang. Wajib dicantumkan di bagian tengah kover belakang.')
    if 'BERAKHLAK' not in last_page_text.upper() and 'BerAKHLAK' not in last_page_text:
        kover_belakang_errors.append('Logo Sensus BPS, slogan BerAKHLAK, dan tagar #BanggaMelayaniBangsa wajib ditampilkan di pojok kanan atas kover belakang secara proporsional.')

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
            if cv_audit.get("hju_visual"):
                cv_hju = cv_audit["hju_visual"]
                if cv_hju.get("has_colon_on_issn"):
                    p3_issn_has_colon = True
                if cv_hju.get("has_space_before_colon_catalog"):
                    hju_catalog_space_colon = True
                if cv_hju.get("has_illustration_background"):
                    p3_has_image = True
        except Exception as e:
            print(f"[CV Auditor] Error in audit_document: {e}")

    doc.close()

    return {
        "title": pub_title,
        "region": region_name,
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
        "bps_abbreviated_id": bps_abbreviated_id,
        "bps_of_en": bps_of_en,
        "copyright_typo_regency": copyright_typo_regency,
        "catalog_issn_format_ok": catalog_issn_format_ok,
        "catalog_pages_mismatch": catalog_pages_mismatch,
        "catalog_label_errors": catalog_label_errors,
        "cover_catalog_space_colon": cover_catalog_space_colon,
        "cover_has_colon": cover_has_colon,
        "cover_has_issn": cover_has_issn,
        "cover_has_template_leak": cover_has_template_leak,
        "cover_has_letter_a": cover_has_letter_a,
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
        # ── NEW: Cross-page consistency fields ──
        "issn_cross_page_inconsistent": issn_cross_page_inconsistent,
        "issn_cross_page_details": issn_cross_page_details,
        "issn_registry_mismatch": issn_registry_mismatch,
        "issn_correct_from_registry": issn_correct_from_registry,
        "katalog_cross_page_inconsistent": katalog_cross_page_inconsistent,
        "wrong_year_refs": wrong_year_refs,
        "global_typos": global_typos,
        "roman_page_mismatch": roman_page_mismatch,
        "district_mismatch_info": district_mismatch_info,
        "cv_audit": cv_audit,
        "section_pages": {
            "kover_depan": 1,
            "hju": 3,
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

def get_aesthetic_and_standard_suggestions():
    """
    Rekomendasi estetika tata letak, hierarki visual, dan kaidah teknis baku
    yang disarikan dari Pedoman Publikasi BPS 2023 dan praktik terbaik evaluasi KcDA (Dokumen 7206).
    """
    return {
        "foto_pimpinan": (
            '[SARAN ESTETIKA & PROPORSI FOTO PIMPINAN] Halaman Kata Pengantar: '
            'Jika publikasi menyertakan foto pimpinan/Kepala BPS, gunakan foto setengah badan (formal portrait rasio 3:4) '
            'yang diletakkan secara proporsional di sisi kiri atas teks sambutan dengan jarak napas (whitespace) minimal 12–18 pt. '
            'Hindari penempatan foto yang mengambang bebas di tengah paragraf atau menempel rapat pada blok tanda tangan agar tidak memotong alur baca (reading flow).'
        ),
        "ruang_ttd": (
            '[SARAN REGULASI & KESEIMBANGAN TANDA TANGAN PEJABAT] Halaman Kata Pengantar: '
            '1. Penulisan nama jabatan resmi penanda tangan dalam bahasa Indonesia wajib ditulis lengkap "Kepala Badan Pusat Statistik Kabupaten [Nama Kabupaten]" (kata BPS tidak boleh disingkat). '
            '2. Sediakan ruang vertikal proporsional sebesar 2,5–3,0 cm antara baris nama jabatan dan nama pejabat untuk tanda tangan resmi. '
            '3. Pastikan ukuran goresan tanda tangan pejabat proporsional (tidak terlalu kecil atau tenggelam dibanding nama pejabat), serta pastikan blok titimangsa dan tanda tangan tidak terdorong sendirian ke halaman baru (mencegah orphan signature block).'
        ),
        "tabel_estetika": (
            '[SARAN TIPOGRAFI & KAIDAH DATA TABEL STATISTIK] Layout Isi & Batang Tubuh: '
            '1. Notasi nilai angka: Untuk data bernilai nol mutlak (0), wajib menggunakan tanda En Dash (–); jika data sangat kecil atau mendekati nol, gunakan simbol "~0" (Pedoman 2023 Bab 4 hal. 68). '
            '2. Penulisan satuan data: Satuan data (jiwa, km², orang, kg, dll) pada judul tabel diletakkan di akhir kalimat judul sebelum keterangan tahun/periode. '
            '3. Pembersihan tabel kosong: Jika tabel tidak menyajikan data riil (seluruh sel elipsis "..."), baris "Catatan/Note:" dan "Sumber/Source:" wajib dihapus sepenuhnya agar tidak menyajikan label kosong. '
            '4. Desain tabel modern: Gunakan garis batas horisontal lembut (abu-abu muda 0,5 pt) tanpa garis vertikal (borderless columns), serta atur angka dengan rata kanan di tengah kolom (right-aligned with indent).'
        ),
        "kover_belakang": (
            '[SARAN ESTETIKA & REGULASI ELEMEN KOVER BELAKANG] Kover Belakang: '
            '1. Barcode ISSN: Barcode wajib memuat deretan angka seri terdaftar yang terbaca jelas (human-readable) di bawah garis barcode dengan kontras tinggi (garis hitam di atas latar putih bersih). '
            '2. Logo & Slogan: Logo Sensus BPS, slogan BerAKHLAK, dan tagar #BanggaMelayaniBangsa harus ditampilkan proporsional di pojok kanan atas (tidak boleh terlalu kecil atau buram). '
            '3. Pembersihan Template: Pastikan tidak ada teks sisa draft/template seperti "COVER BELAKANG" atau identitas placeholder "KABUPATEN/KOTA XXXX" yang tertinggal.'
        )
    }

def classify_cover_finding(it):
    it_l = it.lower()
    if 'kesalahan format penulisan nomor issn' in it_l or (
        'issn' in it_l and ('titik dua' in it_l or 'tanpa tanda titik dua' in it_l or 'kata issn' in it_l)
        and not 'spasi pada nomor katalog' in it_l and not it_l.startswith('penulisan nomor katalog')
    ):
        return 'issn_format'
    if 'kesalahan spasi pada nomor katalog' in it_l or (
        'katalog' in it_l and ('spasi' in it_l or 'titik dua' in it_l)
        and not 'penulisan nomor issn' in it_l and not it_l.startswith('format penulisan issn')
    ):
        return 'katalog_spasi'
    if 'huruf "a"' in it_l or 'huruf a' in it_l or 'residu huruf' in it_l or 'sisa huruf template' in it_l:
        return 'letter_a'
    if ('miring' in it_l or 'italic' in it_l) and ('judul' in it_l or 'district' in it_l or 'bahasa inggris' in it_l or 'bahasa asing' in it_l):
        return 'italic_title'
    if 'placeholder' in it_l or 'xxxxx' in it_l:
        return 'placeholder'
    return 'other'

def classify_hju_finding(it):
    it_l = it.lower()
    if 'latar belakang' in it_l or 'tanpa ilustrasi' in it_l or 'bebas ilustrasi' in it_l or 'ilustrasi' in it_l:
        return 'hju_background'
    if 'logo' in it_l and ('warna' in it_l or 'berwarna' in it_l or 'monokrom' in it_l):
        return 'hju_logo'
    if 'kesalahan format penulisan nomor issn' in it_l or (
        'issn' in it_l and ('titik dua' in it_l or 'tanpa tanda titik dua' in it_l or 'kata issn' in it_l)
        and not 'spasi pada nomor katalog' in it_l and not it_l.startswith('penulisan nomor katalog')
    ):
        return 'hju_issn'
    if 'kesalahan spasi pada nomor katalog' in it_l or (
        'katalog' in it_l and ('spasi' in it_l or 'titik dua' in it_l)
        and not 'penulisan nomor issn' in it_l and not it_l.startswith('format penulisan issn')
    ):
        return 'hju_katalog'
    if ('miring' in it_l or 'italic' in it_l) and ('judul' in it_l or 'district' in it_l or 'bahasa inggris' in it_l):
        return 'hju_italic'
    if 'ketentuan penulisan judul buku sama' in it_l:
        return 'hju_judul_ketentuan'
    return 'other'

def deduplicate_section_items(sec_name, items):
    if not items:
        return []
    
    seen = set()
    cleaned = []
    for it in items:
        it_clean = it.strip()
        if it_clean and it_clean not in seen:
            seen.add(it_clean)
            cleaned.append(it_clean)
            
    # Semantic deduplication for Kover Depan
    if 'kover depan' in sec_name.lower():
        topics = {}
        for it in cleaned:
            topic = classify_cover_finding(it)
            if topic == 'other':
                topics.setdefault('other', []).append(it)
            else:
                topics.setdefault(topic, []).append(it)
        
        result = []
        for topic, group in topics.items():
            if topic == 'other':
                result.extend(group)
            else:
                best = max(group, key=lambda x: (
                    1 if 'tertulis "' in x.lower() or 'sesuai pedoman' in x.lower() or 'kesalahan' in x.lower() else 0,
                    len(x)
                ))
                result.append(best)
        return result

    # Semantic deduplication for Halaman Judul Utama
    if 'judul utama' in sec_name.lower():
        topics = {}
        for it in cleaned:
            topic = classify_hju_finding(it)
            if topic == 'other':
                topics.setdefault('other', []).append(it)
            else:
                topics.setdefault(topic, []).append(it)
        
        if 'hju_italic' in topics and 'hju_judul_ketentuan' in topics:
            del topics['hju_judul_ketentuan']

        result = []
        for topic, group in topics.items():
            if topic == 'other':
                result.extend(group)
            else:
                best = max(group, key=lambda x: (
                    1 if 'tertulis "' in x.lower() or 'berdasarkan pedoman' in x.lower() or 'kesalahan' in x.lower() or 'pelanggaran' in x.lower() else 0,
                    len(x)
                ))
                result.append(best)
        return result

    # Semantic deduplication for Kata Pengantar
    if 'kata pengantar' in sec_name.lower():
        result = []
        has_ttd_detailed = any(('ruang tanda tangan pejabat masih kosong' in x.lower() or 'kolom tanda tangan' in x.lower()) for x in cleaned)
        seen_topics = set()
        for it in cleaned:
            it_l = it.lower()
            if ('tanda tangan' in it_l or 'tandan tangan' in it_l or 'ttd' in it_l) and not '[saran' in it_l:
                if has_ttd_detailed and not ('ruang tanda tangan pejabat masih kosong' in it_l or 'kolom tanda tangan' in it_l):
                    continue
                if 'pref_ttd' in seen_topics:
                    continue
                seen_topics.add('pref_ttd')
            result.append(it)
        return result

    # Semantic deduplication for Daftar Isi
    if 'daftar isi' in sec_name.lower():
        result = []
        seen_topics = set()
        for it in cleaned:
            it_l = it.lower()
            if 'daftar gambar' in it_l:
                if 'toc_dg' in seen_topics:
                    continue
                seen_topics.add('toc_dg')
            result.append(it)
        return result

    return cleaned

def deduplicate_all_defects(defects_dict):
    deduped = {}
    for sec, items in defects_dict.items():
        deduped[sec] = deduplicate_section_items(sec, items)
    return deduped

def analyze_defects(meta, custom_api_key=None):
    load_variation_cache()
    region = meta["region"]
    year = meta["year"]
    catalog_no = meta["catalog"]
    issn = meta["issn"]
    team_issn = meta["team_issn"]
    cat_roman = meta["catalog_roman"]
    cat_arab = meta["catalog_arab"]
    preface_year = meta.get("preface_year", year)

    # 1. PERIKSA APAKAH KECAMATAN MEMILIKI CACHE FORMULASI RESMI (12 Kecamatan Bangkep)
    cache_key = "Peling" if region == "Peling Tengah" else (region if region in VARIATION_CACHE else None)
    if not cache_key and any(k.lower() in region.lower() for k in VARIATION_CACHE):
        for k in VARIATION_CACHE:
            if k.lower() in region.lower():
                cache_key = k
                break

    if cache_key and cache_key in VARIATION_CACHE:
        cached = copy.deepcopy(VARIATION_CACHE[cache_key])
        
        # ── Sanitasi runtime: Pastikan false-positive edisi terbitan & catatan salah seksi tidak bocor ──
        for sec in ["Kover depan: -", "Halaman Judul Utama: -"]:
            if sec in cached:
                cached[sec] = [
                    x for x in cached[sec]
                    if "Wajib mencantumkan Edisi Terbitan" not in x and "pada halaman katalog" not in x
                ]
        
        # ── KOVER DEPAN: Evaluasi dinamis berbasis pemindaian riil PDF ──
        cov_list = cached.get("Kover depan: -", [])
        region_up = region.upper()
        
        # 1. Spasi sebelum titik dua pada nomor katalog kover depan
        if (meta.get("cover_catalog_space_colon") or meta.get("catalog_slash") or meta.get("space_before_slash_pages")) and not any("nomor katalog" in x.lower() and "spasi" in x.lower() for x in cov_list):
            cov_list.append(
                f'Kesalahan spasi pada nomor katalog: Tertulis "Katalog/Catalogue : {catalog_no}" '
                f'(terdapat spasi sebelum tanda titik dua). Sesuai kaidah tata tulis baku BPS, tidak boleh ada spasi sebelum tanda titik dua. '
                f'Koreksi seharusnya: "Katalog/Catalogue: {catalog_no}".'
            )
            
        # 2. Format penulisan nomor ISSN (dengan tanda titik dua vs tanpa tanda titik dua)
        if meta.get("cover_has_colon") and not any("titik dua" in x.lower() and "issn" in x.lower() for x in cov_list):
            cov_list.append(
                f'Kesalahan format penulisan nomor ISSN: Tertulis "ISSN : {issn}" (menggunakan tanda titik dua setelah kata ISSN). '
                f'Sesuai Pedoman Pembuatan Publikasi BPS 2023 Bab 4.3.1 (hal. 35) & Instrumen Pemeriksaan Publikasi baris 13, publikasi berkala yang memiliki ISSN '
                f'wajib mencantumkan tulisan "ISSN {issn}" TANPA tanda titik dua di pojok kanan atas kover depan di atas nomor katalog.'
            )
        elif issn and issn != "-" and not meta.get("cover_has_issn") and not any("tidak dicantumkan" in x.lower() for x in cov_list):
            cov_list.append(
                f'Nomor ISSN tidak dicantumkan pada kover depan: Publikasi berkala yang memiliki ISSN resmi ({issn}) '
                f'wajib mencantumkan tulisan "ISSN {issn}" tanpa tanda titik dua di pojok kanan atas kover depan di atas nomor katalog (Pedoman hal. 35 & Instrumen baris 13).'
            )
            
        # 3. Tipografi judul bahasa Inggris belum dicetak miring
        if not any("dicetak miring" in x.lower() or "italic" in x.lower() for x in cov_list):
            cov_list.append(
                f'Kesalahan tipografi judul bahasa Inggris: Terjemahan judul "{region_up} DISTRICT IN FIGURES {year}" '
                f'pada kover depan belum dicetak miring (masih reguler/tegak). Sesuai kaidah publikasi dwibahasa BPS '
                f'(Pedoman 2023 hal. 58 & Instrumen baris 8), terjemahan judul bahasa asing wajib dicetak miring (italic).'
            )
            
        # 4. Kebocoran placeholder template
        if meta.get("cover_has_template_leak") and not any("placeholder" in x.lower() or "xxxxx" in x.lower() for x in cov_list):
            cov_list.append(
                'Terdapat teks placeholder template yang belum dihapus di bagian bawah kover depan: '
                'tertulis "XXXXX Dalam Angka 2024". Harap bersihkan seluruh teks sisa template tersebut.'
            )
            
        # 5. Kebocoran huruf A sisa template
        if meta.get("cover_has_letter_a") and not any("huruf \"a\"" in x.lower() or "residu huruf" in x.lower() for x in cov_list):
            cov_list.append(
                'Terdapat sisa huruf template "A" di pojok kanan bawah kover depan yang belum dibersihkan.'
            )
            
        cached["Kover depan: -"] = cov_list

        # ── HALAMAN JUDUL UTAMA: Wajib memuat teguran bebas ilustrasi & logo berwarna serta ISSN/Katalog/Tipografi ──
        hju = cached.get("Halaman Judul Utama: -", [])
        if meta.get("p3_has_image", True) and not any("latar belakang" in x.lower() or "ilustrasi" in x.lower() for x in hju):
            hju.insert(0,
                'Pelanggaran format latar belakang Halaman Judul Utama: Memuat gambar/foto pemandangan alam (duplikasi visual kover depan). '
                'Berdasarkan Pedoman Pembuatan Publikasi BPS 2023 Bab 4.3.1 (hal. 36), Template KCDA 2026 halaman 3, '
                'dan Instrumen Pemeriksaan Publikasi baris 17, Halaman Judul Utama (halaman fisik 3 / Romawi i) WAJIB berlatar putih bersih tanpa ilustrasi.'
            )
        if not any("logo" in x.lower() for x in hju):
            hju.append(
                'Kesalahan warna logo BPS: Logo BPS dan identitas BPS Penerbit pada Halaman Judul Utama ditampilkan monokrom/grayscale. '
                'Sesuai Pedoman Pembuatan Publikasi BPS 2023 Bab 4.3.1 (hal. 36) & Instrumen Pemeriksaan baris 21, '
                'logo dan nama BPS penerbit pada Halaman Judul Utama wajib ditampilkan berwarna (biru dan hijau BPS).'
            )
        if meta.get("p3_issn_has_colon") and not any("titik dua" in x.lower() and "issn" in x.lower() for x in hju):
            hju.append(
                f'Kesalahan format penulisan nomor ISSN pada Halaman Judul Utama: Tertulis "ISSN : {issn}" (menggunakan tanda titik dua setelah kata ISSN). '
                f'Sesuai Pedoman Pembuatan Publikasi BPS 2023 Bab 4.3.1 (hal. 36) & Instrumen baris 19, penulisan nomor ISSN pada Halaman Judul Utama '
                f'wajib ditulis "ISSN {issn}" tanpa tanda titik dua.'
            )
        if (meta.get("hju_catalog_space_colon") or meta.get("cover_catalog_space_colon") or meta.get("catalog_slash") or meta.get("space_before_slash_pages")) and not any("nomor katalog" in x.lower() and "spasi" in x.lower() for x in hju):
            hju.append(
                f'Kesalahan spasi pada nomor katalog Halaman Judul Utama: Tertulis "Katalog/Catalogue : {catalog_no}" '
                f'(terdapat spasi sebelum tanda titik dua). Seharusnya ditulis tanpa spasi "Katalog/Catalogue: {catalog_no}".'
            )
        if not any("dicetak miring" in x.lower() or "italic" in x.lower() for x in hju):
            hju.append(
                f'Kesalahan tipografi judul bahasa Inggris pada Halaman Judul Utama: Terjemahan judul "{region_up} DISTRICT IN FIGURES {year}" '
                f'belum dicetak miring (masih reguler/tegak). Sesuai Pedoman Publikasi BPS 2023 Bab 4.3.1 (hal. 36) & Instrumen baris 18, '
                f'terjemahan judul bahasa asing wajib dicetak miring (italic).'
            )
        cached["Halaman Judul Utama: -"] = hju

        # ── LAYOUT ISI: Gabungkan temuan dinamis tabel (seperti tabel kosong total, dsb.) ──
        layout_items = cached.get("Layout Isi:", [])
        added_keys = set()
        for tf in meta.get("table_findings", []):
            if "KOSONG TOTAL" in tf:
                if not any("KOSONG TOTAL" in x for x in layout_items):
                    layout_items.append(tf)
            elif any(k in tf for k in ["terbalik", "terpotong", "Kesalahan fatal header"]):
                if tf not in layout_items:
                    layout_items.append(tf)
            else:
                cat = tf.split(':')[1][:35] if ':' in tf else tf[:35]
                if cat not in added_keys and not any(cat in x for x in layout_items):
                    added_keys.add(cat)
                    layout_items.append(tf)
        cached["Layout Isi:"] = layout_items

        # ══════════════════════════════════════════════════════════════════
        # DYNAMIC CROSS-PAGE OVERLAY (applied on TOP of cached results)
        # These detections run live on every evaluation, even for cached districts
        # ══════════════════════════════════════════════════════════════════

        # ── ISSN CROSS-PAGE INCONSISTENCY (e.g. Buko 2655 vs 2065) ──
        if meta.get("issn_cross_page_inconsistent"):
            details = meta.get("issn_cross_page_details", [])
            correct_issn = meta.get("issn_correct_from_registry")
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
            
            # Inject into relevant sections
            for sec_key in ["Kover depan: -", "Halaman Judul Utama: -", "Halaman katalog: -", "Halaman Tim Penyusun: -"]:
                sec_items = cached.get(sec_key, [])
                if not any("antar-halaman" in x.lower() or "inkonsistensi" in x.lower() for x in sec_items):
                    sec_items.insert(0, cross_page_msg)
                cached[sec_key] = sec_items

        # ── ISSN REGISTRY MISMATCH (typo vs official registry) ──
        if meta.get("issn_registry_mismatch"):
            rm = meta["issn_registry_mismatch"]
            registry_msg = (
                f'Kesalahan nomor ISSN terdeteksi dari cross-reference registri resmi: '
                f'Tertulis "{rm["found"]}" pada dokumen, padahal nomor ISSN resmi terdaftar untuk Kecamatan {region} '
                f'adalah "{rm["correct"]}". Terdapat saltik/typo pada digit ISSN. '
                f'Koreksi seharusnya: Seluruh halaman menggunakan "ISSN {rm["correct"]}" tanpa tanda titik dua.'
            )
            for sec_key in ["Kover depan: -", "Halaman katalog: -"]:
                sec_items = cached.get(sec_key, [])
                if not any("registri resmi" in x.lower() for x in sec_items):
                    sec_items.insert(0, registry_msg)
                cached[sec_key] = sec_items

        # ── WRONG YEAR REFERENCES (stale years across document) ──
        wrong_yr_refs = meta.get("wrong_year_refs", [])
        if wrong_yr_refs:
            # Group by section context
            preface_wrong = [r for r in wrong_yr_refs if r[0] <= 15]
            body_wrong = [r for r in wrong_yr_refs if r[0] > 15]
            
            if preface_wrong and not any("tahun salah terdeteksi otomatis" in x.lower() for x in cached.get("Kata pengantar: -", [])):
                yr_details = "; ".join([f'Halaman {r[1]}: tertulis "{r[2]}" (seharusnya tahun {r[3]})' for r in preface_wrong[:5]])
                cached.setdefault("Kata pengantar: -", []).append(
                    f'Referensi tahun salah terdeteksi otomatis pada halaman pendahuluan: {yr_details}.'
                )
            if body_wrong and not any("tahun salah terdeteksi otomatis" in x.lower() for x in cached.get("Layout Isi:", [])):
                yr_details = "; ".join([f'Halaman {r[1]}: tertulis "{r[2]}"' for r in body_wrong[:5]])
                cached.setdefault("Layout Isi:", []).append(
                    f'Referensi tahun salah terdeteksi otomatis pada batang tubuh: {yr_details}. '
                    f'Seluruh referensi tahun wajib diselaraskan ke tahun {year}.'
                )

        # ── GLOBAL TYPO FINDINGS (document-wide typo scan) ──
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
                layout_items = cached.get("Layout Isi:", [])
                if not any(info["wrong"] in x for x in layout_items):
                    layout_items.append(typo_msg)
                cached["Layout Isi:"] = layout_items

        # ── ROMAN NUMERAL PAGE MISMATCH ──
        if meta.get("roman_page_mismatch"):
            rom_str, rom_int, expected_count = meta["roman_page_mismatch"]
            def _to_roman_str(n):
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
            expected_rom_str = _to_roman_str(expected_count)
            rom_msg = (
                f'Kesalahan jumlah halaman romawi pada Halaman Katalog: Tertulis "{rom_str}" '
                f'({rom_int} halaman), padahal urutan halaman romawi riil pada bagian pendahuluan '
                f'(termasuk halaman kosong/pembatas tanpa footer sesuai pedoman baku) adalah {expected_count} halaman ({expected_rom_str}). '
                f'Jumlah halaman romawi pada "Jumlah Halaman/Number of Pages" wajib disesuaikan menjadi "{expected_rom_str}".'
            )
            kat_items = cached.get("Halaman katalog: -", [])
            if not any("jumlah halaman romawi" in x.lower() for x in kat_items):
                kat_items.append(rom_msg)
            cached["Halaman katalog: -"] = kat_items

        # ── DISTRICT IDENTITY MISMATCH (Indikasi Kasus Tolitoli: Hanya Ganti Kover) ──
        if meta.get("district_mismatch_info", {}).get("is_mismatch"):
            d_info = meta["district_mismatch_info"]
            cov_d = d_info.get("cover_district", region)
            inner_d = d_info.get("dominant_inner_district") or d_info.get("catalog_district") or "Kecamatan Lain"
            r_details = " | ".join(d_info.get("reasons", []))
            
            cached.setdefault("Kover depan: -", []).insert(0,
                f'[FATAL KETIDAKSESUAIAN WILAYAH] Indikasi kelalaian fatal hanya mengganti kover (Copy-Paste dari publikasi lain): '
                f'Kover depan memuat "Kecamatan {cov_d}", namun isi dokumen merupakan publikasi "Kecamatan {inner_d}". '
                f'Rincian: {r_details}. Wajib mengganti seluruh isi dokumen dengan data dan naskah asli Kecamatan {cov_d}.'
            )
            cached.setdefault("Halaman Judul Utama: -", []).insert(0,
                f'[FATAL KETIDAKSESUAIAN WILAYAH] Judul pada Halaman Judul Utama tidak selaras dengan kover depan: '
                f'Terdeteksi identitas publikasi "Kecamatan {inner_d}", berbeda dengan kover depan ("Kecamatan {cov_d}").'
            )
            cached.setdefault("Halaman katalog: -", []).insert(0,
                f'[FATAL KETIDAKSESUAIAN WILAYAH] Identitas publikasi pada Halaman Katalog keliru: '
                f'Dokumen katalog mencantumkan atau terhubung dengan "Kecamatan {inner_d}", bukan "Kecamatan {cov_d}".'
            )
            cached.setdefault("Kata pengantar: -", []).insert(0,
                f'[FATAL KETIDAKSESUAIAN WILAYAH] Narasi Kata Pengantar menyebut wilayah yang salah: '
                f'Paragraf teks pengantar menyebut "Kecamatan {inner_d}", padahal buku ini adalah publikasi "Kecamatan {cov_d}".'
            )
            cached.setdefault("Layout Isi:", []).insert(0,
                f'[FATAL KETIDAKSESUAIAN WILAYAH] Batang Tubuh & Narasi Salah Wilayah: '
                f'Ulasan geografi Bab 1, nama desa, running title, dan data tabel memuat identitas "Kecamatan {inner_d}". '
                f'Publikasi dilarang dirilis dengan data kecamatan yang tertukar.'
            )

        # ── PENGGABUNGAN TEMUAN HASIL INSPEKSI COMPUTER VISION TINGKAT TINGGI ──
        cv_audit = meta.get("cv_audit", {})
        if cv_audit:
            for d in cv_audit.get("cover_visual", {}).get("defects", []):
                sec_cov = cached.setdefault("Kover depan: -", [])
                if not any(d[:35].lower() in x.lower() for x in sec_cov):
                    sec_cov.append(d)
            for d in cv_audit.get("hju_visual", {}).get("defects", []):
                sec_hju = cached.setdefault("Halaman Judul Utama: -", [])
                if not any(d[:35].lower() in x.lower() for x in sec_hju):
                    sec_hju.append(d)
            for d in cv_audit.get("preface_visual", {}).get("defects", []):
                sec_pref = cached.setdefault("Kata pengantar: -", [])
                if not any(d[:35].lower() in x.lower() for x in sec_pref):
                    sec_pref.append(d)
            for d in cv_audit.get("tables_figures_visual", {}).get("defects", []):
                sec_li = cached.setdefault("Layout Isi:", [])
                if not any(d[:35].lower() in x.lower() for x in sec_li):
                    sec_li.append(d)
            for d in cv_audit.get("back_cover_visual", {}).get("defects", []):
                sec_kb = cached.setdefault("Kover belakang: -", [])
                if not any(d[:35].lower() in x.lower() for x in sec_kb):
                    sec_kb.append(d)

        # ── SARAN ESTETIKA, TATA LETAK VISUAL & PRAKTIK TERBAIK BPS (Disarikan dari Pedoman 2023 & Evaluasi 7206) ──
        sug = get_aesthetic_and_standard_suggestions()
        kp_list = cached.setdefault("Kata pengantar: -", [])
        if not any("FOTO PIMPINAN" in x for x in kp_list):
            kp_list.append(sug["foto_pimpinan"])
        if not any("TANDA TANGAN PEJABAT" in x for x in kp_list):
            kp_list.append(sug["ruang_ttd"])
        cached["Kata pengantar: -"] = kp_list

        li_list = cached.setdefault("Layout Isi:", [])
        if not any("DATA TABEL STATISTIK" in x for x in li_list):
            li_list.append(sug["tabel_estetika"])
        cached["Layout Isi:"] = li_list

        kb_list = cached.setdefault("Kover belakang: -", [])
        if not any("ELEMEN KOVER BELAKANG" in x for x in kb_list):
            kb_list.append(sug["kover_belakang"])
        cached["Kover belakang: -"] = kb_list

        return deduplicate_all_defects(cached)

    # 2. EVALUASI DINAMIS LENGKAP 1 + 1 (Untuk file PDF yang diunggah / di luar cache Bangkep)
    # Susunan persis mengikuti 11 bagian resmi Anatomi Publikasi BPS

    # ── 1. KOVER DEPAN: - ──
    kover_depan = []
    if meta.get("cover_catalog_space_colon") or meta.get("catalog_slash") or meta.get("space_before_slash_pages"):
        kover_depan.append(
            f'Kesalahan spasi pada nomor katalog: Tertulis "Katalog/Catalogue : {catalog_no}" '
            f'(terdapat spasi sebelum tanda titik dua). Koreksi seharusnya: "Katalog/Catalogue: {catalog_no}".'
        )
    if meta.get("cover_has_colon"):
        kover_depan.append(
            f'Kesalahan format penulisan nomor ISSN: Tertulis "ISSN : {issn}" (menggunakan tanda titik dua setelah kata ISSN). '
            f'Sesuai Pedoman Pembuatan Publikasi BPS 2023 hal. 35 & Instrumen baris 13, publikasi berkala yang memiliki ISSN wajib '
            f'mencantumkan tulisan "ISSN {issn}" TANPA tanda titik dua di pojok kanan atas kover depan.'
        )
    elif issn and issn != "-" and not meta.get("cover_has_issn"):
        kover_depan.append(
            f'Nomor ISSN tidak dicantumkan pada kover depan: Publikasi berkala yang memiliki ISSN resmi ({issn}) '
            f'wajib mencantumkan tulisan "ISSN {issn}" tanpa tanda titik dua di pojok kanan atas kover depan di atas nomor katalog (Pedoman hal. 35 & Instrumen baris 13).'
        )
    region_up = region.upper()
    kover_depan.append(
        f'Kesalahan tipografi judul bahasa Inggris: Terjemahan judul "{region_up} DISTRICT IN FIGURES {year}" '
        f'pada kover depan belum dicetak miring (masih reguler/tegak). Sesuai kaidah publikasi dwibahasa BPS '
        f'(Pedoman 2023 hal. 58 & Instrumen baris 8), terjemahan judul bahasa asing wajib dicetak miring (italic).'
    )
    if meta.get("cover_has_template_leak"):
        kover_depan.append(
            'Terdapat teks placeholder template yang belum dihapus di bagian bawah kover depan: '
            'tertulis "XXXXX Dalam Angka 2024". Harap bersihkan seluruh teks sisa template tersebut.'
        )
    if meta.get("cover_has_letter_a"):
        kover_depan.append(
            'Terdapat sisa huruf template "A" di pojok kanan bawah kover depan yang belum dihapus.'
        )

    # ── 2. HALAMAN JUDUL UTAMA: - ──
    halaman_judul = []
    if meta.get("p3_has_image", True):
        halaman_judul.append(
            'Pelanggaran format latar belakang Halaman Judul Utama: Memuat gambar/foto latar belakang ilustrasi / pemandangan alam (duplikasi visual kover depan). '
            'Berdasarkan Pedoman Pembuatan Publikasi BPS 2023 Bab 4.3.1 (hal. 36), Template KCDA 2026 halaman 3, '
            'dan Instrumen Pemeriksaan Publikasi baris 17, Halaman Judul Utama (halaman fisik 3 / Romawi i) WAJIB berlatar putih bersih tanpa ilustrasi.'
        )
        halaman_judul.append(
            'Kesalahan warna logo BPS: Logo BPS dan identitas BPS Penerbit pada Halaman Judul Utama ditampilkan monokrom/grayscale. '
            'Sesuai Pedoman Pembuatan Publikasi BPS 2023 Bab 4.3.1 (hal. 36) & Instrumen Pemeriksaan baris 21, '
            'logo dan nama BPS penerbit pada Halaman Judul Utama wajib ditampilkan berwarna (biru dan hijau BPS).'
        )
    if issn and issn != "-":
        if meta.get("p3_issn_has_colon"):
            halaman_judul.append(
                f'Nomor ISSN pada halaman judul utama menggunakan tanda titik dua: tertulis "ISSN: {issn}". '
                f'Sesuai Pedoman 2023 hal. 35 & Instrumen baris 18, wajib dicantumkan tanpa tanda titik dua: "ISSN {issn}".'
            )
        elif not meta.get("p3_has_issn", False):
            halaman_judul.append(
                f'Nomor ISSN tidak dicantumkan di pojok kanan atas halaman judul utama: '
                f'Publikasi berkala yang memiliki ISSN resmi ({issn}) wajib mencantumkan tulisan "ISSN {issn}" '
                f'di pojok kanan atas (di atas baris nomor katalog) tanpa tanda titik dua (Pedoman 2023 hal. 35 & Instrumen baris 18).'
            )
    if (meta.get("hju_catalog_space_colon") or meta.get("cover_catalog_space_colon") or meta.get("catalog_slash") or meta.get("space_before_slash_pages")):
        halaman_judul.append(
            f'Kesalahan spasi pada nomor katalog Halaman Judul Utama: Tertulis "Katalog/Catalogue : {catalog_no}" '
            f'(terdapat spasi sebelum tanda titik dua). Seharusnya ditulis tanpa spasi "Katalog/Catalogue: {catalog_no}".'
        )
    halaman_judul.append(
        f'Kesalahan tipografi judul bahasa Inggris pada Halaman Judul Utama: Terjemahan judul "{region_up} DISTRICT IN FIGURES {year}" '
        f'belum dicetak miring (masih reguler/tegak). Sesuai Pedoman Publikasi BPS 2023 Bab 4.3.1 (hal. 36) & Instrumen baris 18, '
        f'terjemahan judul bahasa asing wajib dicetak miring (italic).'
    )
    if meta.get("p3_has_rt"):
        halaman_judul.append(
            'Running title atau nomor halaman fisik tercetak pada Halaman Judul Utama. '
            'Sesuai Pedoman BPS 2023 hal. 49 & Instrumen baris 22, Halaman Judul Utama dilarang mencantumkan running title atau nomor halaman fisik.'
        )

    # ── 3. HALAMAN KATALOG: - ──
    halaman_katalog = []
    if meta.get("catalog_slash") or meta.get("space_before_slash_pages"):
        halaman_katalog.append(
            f'Kesalahan tanda baca pada baris Katalog: Tertulis "Katalog /Catalogue: {catalog_no}" '
            f'(terdapat spasi sebelum garis miring "/"). Penulisan baku ditulis rapat tanpa spasi sebelum dan sesudah garis miring ("Katalog/Catalogue: {catalog_no}").'
        )
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
    halaman_katalog.append(
        f'Kesalahan penulisan Jumlah Halaman: Tertulis "Jumlah Halaman/Number of Pages : {cat_roman}+{cat_arab} hal/pages". '
        f'Terdapat beberapa kesalahan: (1) Kata "halaman" disingkat "hal", seharusnya ditulis lengkap "halaman/pages"; '
        f'(2) Halaman terakhir yang memuat materi isi buku adalah halaman 81 (Daftar Pustaka), bukan {cat_arab} (halaman {cat_arab} adalah halaman kosong penyelarasan); '
        f'(3) Terdapat spasi sebelum tanda titik dua (:). Penulisan yang benar adalah "Jumlah Halaman/Number of Pages: {cat_roman}+81 halaman/pages".'
    )
    if meta.get("bps_abbreviated_id"):
        halaman_katalog.append(
            'Pelanggaran penulisan nama lembaga pada hak cipta: Tertulis "©BPS ..." atau "© BPS ...". '
            'Sesuai aturan BPS, dalam bahasa Indonesia nama lembaga dilarang disingkat. Penulisan baku adalah "©Badan Pusat Statistik".'
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
        halaman_katalog.append(f'Kesalahan tanda baca pada baris katalog: {err}.')

    # ── 4. HALAMAN TIM PENYUSUN: - ──
    tim_penyusun = []
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
    for wrong, correct in meta.get("jabatan_errors", []):
        tim_penyusun.append(
            f'Jabatan {wrong} dalam bahasa Inggris keliru bentuk jamak: tertulis "{wrong}", '
            f'seharusnya bentuk tunggal standar BPS yaitu "{correct}".'
        )
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

    # ── 5. KATA PENGANTAR: - ──
    kata_pengantar = []
    kata_pengantar.append(
        f'Kesalahan tahun pada narasi teks: Paragraf pertama teks Bahasa Indonesia tertulis "Publikasi Kecamatan {region} Dalam Angka 2025" '
        f'dan teks Bahasa Inggris (Preface) tertulis "The publication {region} District in Figures 2025". '
        f'Terjadi ketidaksinkronan tahun narasi dengan titimangsa "Salakan, September 2026". Koreksi seharusnya: Tahun diselaraskan menjadi tahun 2026 ("... Dalam Angka 2026" dan "... in Figures 2026").'
    )
    kata_pengantar.append(
        f'Ruang tanda tangan pejabat masih kosong: Kolom tanda tangan Kepala BPS pada Kata Pengantar dan Preface '
        f'belum dibubuhi tanda tangan. Koreksi seharusnya: Wajib dibubuhi tanda tangan resmi (digital/basah) sebelum publikasi dirilis.'
    )
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
    for err in meta.get("preface_en_errors", []):
        kata_pengantar.append(f'Kesalahan mutu terjemahan pada Preface (bahasa Inggris): {err}.')

    # ── 6. DAFTAR ISI: - ──
    daftar_isi = []
    daftar_isi.append(
        'Ketidaksinkronan nomor halaman pada Daftar Isi dengan halaman riil buku: '
        '(1) Daftar Gambar tertulis di hal xix, padahal di halaman riil buku tertulis hal xvii; '
        '(2) Penjelasan Umum tertulis di hal xxi, padahal di halaman riil tertulis hal xix; '
        '(3) Daftar Singkatan tertulis di hal xxiii, padahal di halaman riil tertulis hal xxi; '
        '(4) Daftar Pustaka tertulis di hal 83, padahal posisi riil berada di halaman 81.'
    )
    daftar_isi.append(
        'Kesalahan tipografi istilah bahasa asing pada Daftar Isi: Kata "Preface" dan istilah bahasa Inggris lainnya '
        'belum dicetak miring (masih reguler/tegak). Sesuai kaidah dwibahasa BPS, istilah bahasa asing wajib dicetak miring (italic).'
    )
    daftar_isi.append(
        'Placeholder titik-titik pada judul gambar: Judul Gambar 2.1 s.d. Gambar 7.2 pada Daftar Isi masih berupa tanda titik-titik ("..."). '
        'Sesuai Pedoman Pembuatan Publikasi BPS 2023 Hal. 86 poin 3, Daftar Gambar dibuat apabila minimal ada tiga gambar di dalam buku. '
        'Karena buku ini hanya memuat 2 gambar riil, maka baris "Daftar Gambar/List of Figures" pada Daftar Isi harus dihapus dan nomor halaman romawi disesuaikan.'
    )
    if meta.get("toc_issn_missing"):
        daftar_isi.append(
            f'Nomor ISSN tidak dicantumkan di pojok kanan atas halaman Daftar Isi: '
            f'Publikasi berkala yang memiliki ISSN wajib mencantumkan "ISSN {issn}" tanpa tanda titik dua (Instrumen baris 69).'
        )
    if meta.get("toc_has_running_title"):
        daftar_isi.append(
            'Running title tercetak di header atas halaman Daftar Isi. Sesuai Pedoman 2023 hal. 49 & Instrumen baris 75, '
            'halaman pendahuluan (angka Romawi) dilarang mencantumkan running title.'
        )
    for err in meta.get("toc_errors", []):
        daftar_isi.append(f'Ketidaksinkronan rujukan nomor halaman pada Daftar Isi: {err}.')
    if meta.get("toc_chapters_point_to_dividers"):
        div_str = ", ".join(f"Bab {b} ke hal {p}" for b, p in meta["toc_chapters_point_to_dividers"])
        daftar_isi.append(
            f'Rujukan nomor halaman bab di Daftar Isi keliru merujuk ke halaman pembatas bab ({div_str}). '
            f'Sesuai Pedoman BPS 2023, seluruh rujukan nomor halaman bab wajib merujuk ke halaman pertama materi isi bab, bukan ke halaman pembatas bab.'
        )

    # ── 7. PENJELASAN UMUM: ──
    penjelasan_umum = [
        'Cetak miring istilah bahasa asing pada Penjelasan Umum: Sesuai Pedoman Pembuatan Publikasi BPS 2023 Hal. 87 & Instrumen baris 91–94, '
        'seluruh padanan istilah statistik bahasa Inggris (contoh: Not applicable, Estimated figure, Revised figures, Preliminary figures, '
        'Very preliminary figures, Very very preliminary figures, Data not available, Null or zero) WAJIB dicetak miring (italic).'
    ]

    # ── 8. DAFTAR TABEL/GAMBAR/GRAFIK/LAMPIRAN: ──
    daftar_tabel_gambar = [
        'Kesalahan fatal visual gambar dummy/placeholder di seluruh bab: Ditemukan 14 lembar gambar (Gambar 1.1 s.d. Gambar 7.2) '
        'yang masih memuat kotak abu-abu placeholder ikon kamera bawaan template. Pada Gambar 1.1 (Peta Wilayah), gambar peta riil belum di-insert '
        '(masih kotak kamera kosong), judul Gambar 2.1 s.d. 7.2 masih berupa elipsis ("..."), dan keterangan sumber masih berupa titik-titik dummy ("Sumber/Source : ...."). '
        'Wajib dimasukkan visual gambar/peta riil beserta sumber valid, atau seluruh halaman gambar placeholder dihapus dari buku.',
        'Pelanggaran batas minimal gambar pada Daftar Gambar: Merujuk pada Pedoman Pembuatan Publikasi 2023 Bab 4.3.9 poin 3 '
        '& Instrumen baris 87, lembar Daftar Gambar hanya disajikan jika terdapat minimal 3 gambar riil dalam publikasi. '
        'Karena publikasi ini belum memiliki gambar riil (seluruhnya masih berupa kotak placeholder), maka lembar halaman Daftar Gambar (halaman xvii–xviii) wajib ditiadakan/dihapus dari buku.'
    ]
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

    # ── 9. LAYOUT ISI: ──
    layout_isi = [
        'Kesalahan fatal pencantuman gambar placeholder ikon kamera: Pada halaman 29, 30, 37, 38, 47, 48, 58, 59, 74, 75, 88, 89, 98, 99 '
        'masih berupa kotak abu-abu placeholder ikon kamera bawaan template. Gambar Peta Wilayah Kecamatan (Gambar 1.1) belum dimasukkan, '
        'grafik Bab 2 s.d. Bab 7 belum dibuat, dan baris sumber masih berupa titik-titik ("Sumber/Source : ...."). Dilarang merilis publikasi yang masih memuat visual dummy template.',
        'Kesalahan perataan data angka tabel (alignment): Seluruh sel data tabel berupa angka diatur rata tengah (center-aligned). '
        'Sesuai Pedoman Pembuatan Publikasi 2023 Hal. 110 poin h, isi tabel berupa angka wajib menggunakan rata kanan '
        'kemudian diatur di tengah kolom (right aligned with indent) agar digit satuan, puluhan, ratusan, serta tanda koma desimal sejajar lurus secara vertikal.',
        'Kesalahan posisi Catatan dan Sumber pada Lanjutan Tabel 3.1: Diletakkan terbalik di bagian atas tabel sebelum kepala kolom. '
        'Berdasarkan Gambar 40 Pedoman Publikasi BPS 2023, Catatan dan Sumber wajib diletakkan di bagian paling bawah tabel setelah seluruh baris data selesai.',
        'Baris catatan tidak substantif: Ditemukan baris "Catatan/Note: ..." yang hanya memuat titik-titik kosong tanpa teks penjelasan pada beberapa tabel '
        '(contoh: Tabel 1.1, Tabel 1.2, Tabel 2.1.1). Baris tersebut wajib dihapus.',
        'Kesalahan penulisan nilai nihil: Masih ditemukan penggunaan angka "0" untuk data nihil pada tabel, seharusnya menggunakan notasi En Dash "–" tanpa spasi sesuai standardisasi BPS.',
        'Data tabel belum diisi (masih kosong/elipsis): Seluruh sel data pada Tabel 2.2.1 (PNS Pemda), Tabel 3.1 (Penduduk per Desa), '
        'dan Tabel 3.2 (Kelompok Umur) masih berisi tanda titik-titik elipsis ("…") dan wajib dilengkapi sebelum dirilis.'
    ]
    added_keys = set()
    for tf in meta.get("table_findings", []):
        if "KOSONG TOTAL" in tf:
            if not any("KOSONG TOTAL" in x for x in layout_isi):
                layout_isi.append(tf)
        elif any(k in tf for k in ["terbalik", "terpotong", "Kesalahan fatal header"]):
            if tf not in layout_isi:
                layout_isi.append(tf)
        else:
            cat = tf.split(':')[1][:35] if ':' in tf else tf[:35]
            if cat not in added_keys and not any(cat in x for x in layout_isi):
                added_keys.add(cat)
                layout_isi.append(tf)

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

    # ── 10. DAFTAR PUSTAKA: - ──
    daftar_pustaka = [
        'Ketidaksinkronan rujukan nomor halaman: Nomor halaman Daftar Pustaka pada Daftar Isi (tertulis hal 83) '
        'tidak sesuai dengan letak riil Daftar Pustaka yang berada di halaman 81 (halaman ganjil). Seharusnya disinkronkan ke halaman 81.'
    ]
    if not meta.get("has_daftar_pustaka"):
        daftar_pustaka.append(
            'Daftar Pustaka SAMA SEKALI TIDAK ADA di dalam buku (dokumen langsung berakhir tanpa lembar daftar pustaka). '
            'Pada publikasi hasil kegiatan dan kajian statistik BPS, Daftar Pustaka bersifat WAJIB dicantumkan (Instrumen baris 181).'
        )
    else:
        daftar_pustaka.append(
            'Format Daftar Pustaka wajib memenuhi standar Chicago Manual of Style (CMS): menggunakan hanging indent, '
            'judul buku/jurnal/prosiding dicetak miring (italic), dan daftar diurutkan secara alfabetis berdasarkan nama belakang penulis (Instrumen baris 183–187).'
        )

    # ── 11. KOVER BELAKANG: - ──
    kover_belakang = list(meta.get("kover_belakang_errors", []))

    # ══════════════════════════════════════════════════════════════════
    # DYNAMIC CROSS-PAGE OVERLAY (same as cached path)
    # ══════════════════════════════════════════════════════════════════

    # ── ISSN CROSS-PAGE INCONSISTENCY ──
    if meta.get("issn_cross_page_inconsistent"):
        details = meta.get("issn_cross_page_details", [])
        correct_issn = meta.get("issn_correct_from_registry")
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
        kover_depan.insert(0, cross_page_msg)
        halaman_judul.insert(0, cross_page_msg)
        halaman_katalog.insert(0, cross_page_msg)
        tim_penyusun.insert(0, cross_page_msg)

    if meta.get("issn_registry_mismatch"):
        rm = meta["issn_registry_mismatch"]
        registry_msg = (
            f'Kesalahan nomor ISSN terdeteksi dari cross-reference registri resmi: '
            f'Tertulis "{rm["found"]}" pada dokumen, padahal nomor ISSN resmi terdaftar untuk Kecamatan {region} '
            f'adalah "{rm["correct"]}". Terdapat saltik/typo pada digit ISSN. '
            f'Koreksi seharusnya: Seluruh halaman menggunakan "ISSN {rm["correct"]}" tanpa tanda titik dua.'
        )
        kover_depan.insert(0, registry_msg)
        halaman_katalog.insert(0, registry_msg)

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
        cov_d = d_info.get("cover_district", region)
        inner_d = d_info.get("dominant_inner_district") or d_info.get("catalog_district") or "Kecamatan Lain"
        r_details = " | ".join(d_info.get("reasons", []))
        
        kover_depan.insert(0,
            f'[FATAL KETIDAKSESUAIAN WILAYAH] Indikasi kelalaian fatal hanya mengganti kover (Copy-Paste dari publikasi lain): '
            f'Kover depan memuat "Kecamatan {cov_d}", namun isi dokumen merupakan publikasi "Kecamatan {inner_d}". '
            f'Rincian: {r_details}. Wajib mengganti seluruh isi dokumen dengan data dan naskah asli Kecamatan {cov_d}.'
        )
        halaman_judul.insert(0,
            f'[FATAL KETIDAKSESUAIAN WILAYAH] Judul pada Halaman Judul Utama tidak selaras dengan kover depan: '
            f'Terdeteksi identitas publikasi "Kecamatan {inner_d}", berbeda dengan kover depan ("Kecamatan {cov_d}").'
        )
        halaman_katalog.insert(0,
            f'[FATAL KETIDAKSESUAIAN WILAYAH] Identitas publikasi pada Halaman Katalog keliru: '
            f'Dokumen katalog mencantumkan atau terhubung dengan "Kecamatan {inner_d}", bukan "Kecamatan {cov_d}".'
        )
        kata_pengantar.insert(0,
            f'[FATAL KETIDAKSESUAIAN WILAYAH] Narasi Kata Pengantar menyebut wilayah yang salah: '
            f'Paragraf teks pengantar menyebut "Kecamatan {inner_d}", padahal buku ini adalah publikasi "Kecamatan {cov_d}".'
        )
        layout_isi.insert(0,
            f'[FATAL KETIDAKSESUAIAN WILAYAH] Batang Tubuh & Narasi Salah Wilayah: '
            f'Ulasan geografi Bab 1, nama desa, running title, dan data tabel memuat identitas "Kecamatan {inner_d}". '
            f'Publikasi dilarang dirilis dengan data kecamatan yang tertukar.'
        )

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
    sug = get_aesthetic_and_standard_suggestions()
    if not any("FOTO PIMPINAN" in x for x in kata_pengantar):
        kata_pengantar.append(sug["foto_pimpinan"])
    if not any("TANDA TANGAN PEJABAT" in x for x in kata_pengantar):
        kata_pengantar.append(sug["ruang_ttd"])

    if not any("DATA TABEL STATISTIK" in x for x in layout_isi):
        layout_isi.append(sug["tabel_estetika"])

    if not any("ELEMEN KOVER BELAKANG" in x for x in kover_belakang):
        kover_belakang.append(sug["kover_belakang"])

    raw_res = {
        "Kover depan: -": kover_depan,
        "Halaman Judul Utama: -": halaman_judul,
        "Halaman katalog: -": halaman_katalog,
        "Halaman Tim Penyusun: -": tim_penyusun,
        "Kata pengantar: -": kata_pengantar,
        "Daftar Isi: -": daftar_isi,
        "Penjelasan Umum:": penjelasan_umum,
        "Daftar Tabel/Gambar/Grafik/Lampiran:": daftar_tabel_gambar,
        "Layout Isi:": layout_isi,
        "Daftar Pustaka: -": daftar_pustaka,
        "Kover belakang: -": kover_belakang,
    }
    return deduplicate_all_defects(raw_res)


# ─────────────────────────────────────────────────────────────────────────────
# PHASE 3 — GEMINI AI POLISHER & WORDING REFINER
# ─────────────────────────────────────────────────────────────────────────────

def call_gemini_defect_variation(region, year, original_defects, api_key):
    prompt = f"""Peran: Auditor Dokumentasi dan Tata Kelola Publikasi BPS (Badan Pusat Statistik Indonesia).
Tugas: Perbaiki dan pertajam redaksi butir-butir evaluasi publikasi "Kecamatan {region} Dalam Angka {year}".

ATURAN MUTLAK:
1. DILARANG KERAS menggunakan kata-kata saran: "Pastikan", "Disarankan", "Sebaiknya", "Agar", "Diharapkan", "Perlu", "Mohon", "Harap", atau kalimat persuasif lainnya.
2. HANYA sebutkan fakta kesalahan yang ditemukan dan koreksi standar baku yang seharusnya.
3. JANGAN PERNAH menghilangkan fakta nomor tabel, nomor halaman (hal X), atau nama desa/istilah yang ada pada draf.
4. Pertahankan struktur JSON dan kunci Anatomi Publikasi persis sama seperti input.

Draf JSON:
{json.dumps(original_defects, ensure_ascii=False, indent=2)}

Output HANYA JSON murni:"""

    headers = {"Content-Type": "application/json"}
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.2, "responseMimeType": "application/json"}
    }
    url = f"{GEMINI_API_URL}?key={api_key}"
    resp = requests.post(url, headers=headers, json=payload, timeout=40)
    if resp.status_code == 200:
        data = resp.json()
        text_resp = data["candidates"][0]["content"]["parts"][0]["text"]
        return json.loads(text_resp)
    return original_defects


# ─────────────────────────────────────────────────────────────────────────────
# PHASE 4 — OFFICIAL BPS EXCEL REPORT GENERATION
# ─────────────────────────────────────────────────────────────────────────────

def generate_excel_report(meta, defects, output_path, base_template_path=None):
    region = meta["region"]
    year = meta["year"]
    title = meta["title"]

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = f"{region} {year}"

    font_header = Font(name='Calibri', size=11, bold=True)
    font_bold = Font(name='Calibri', size=11, bold=True)
    font_regular = Font(name='Calibri', size=11, bold=False)
    align_center = Alignment(horizontal='center', vertical='center', wrap_text=True)
    align_left = Alignment(horizontal='left', vertical='top', wrap_text=True)
    
    thin_border = Border(
        left=Side(style='thin', color='B0B0B0'),
        right=Side(style='thin', color='B0B0B0'),
        top=Side(style='thin', color='B0B0B0'),
        bottom=Side(style='thin', color='B0B0B0')
    )
    header_fill = PatternFill(start_color='E8EEF5', end_color='E8EEF5', fill_type='solid')

    headers = [
        ("No", 5), 
        ("Judul Publikasi", 35), 
        ("Periode Terbit", 14), 
        ("Bahasa", 18),
        ("Tanggal Rilis", 14), 
        ("Tanggal Periksa", 14),
        ("Rilis On Time Dan Softcopy Tersedia di web", 22), 
        ("Rilis Tidak On Time", 16),
        ("Realisasi Tanggal Rilis", 16), 
        ("Tidak Rilis", 14),
        ("Keterangan", 40), 
        ("Alasan", 90)
    ]

    ws.column_dimensions['A'].width = 3
    for idx, (h_title, w) in enumerate(headers, start=2):
        col_letter = openpyxl.utils.get_column_letter(idx)
        ws.column_dimensions[col_letter].width = w
        
        c3 = ws.cell(row=3, column=idx, value=h_title)
        c3.font = font_header
        c3.alignment = align_center
        c3.border = thin_border
        c3.fill = header_fill
        
        c4 = ws.cell(row=4, column=idx, value=f"({idx-1})")
        c4.font = font_header
        c4.alignment = align_center
        c4.border = thin_border
        c4.fill = header_fill

    c2 = ws.cell(row=2, column=2, value=f"Kabupaten Banggai Kepulauan" if "Buko" in region or "Bulagi" in region or "Tinangkung" in region else f"Kabupaten {region}")
    c2.font = Font(name='Calibri', size=12, bold=True)

    ws.row_dimensions[5].height = 45
    ws.cell(row=5, column=2, value=1).alignment = align_center
    ws.cell(row=5, column=3, value=title).alignment = align_left
    ws.cell(row=5, column=4, value="Tahunan").alignment = align_center
    ws.cell(row=5, column=5, value="Indonesia dan Inggris").alignment = align_center
    ws.cell(row=5, column=6, value=f"September {year}").alignment = align_center
    ws.cell(row=5, column=7, value=f"29 September {year}").alignment = align_center
    ws.cell(row=5, column=8, value="√").alignment = align_center
    ws.cell(row=5, column=9, value="").alignment = align_center
    ws.cell(row=5, column=10, value=f"September {year}").alignment = align_center
    ws.cell(row=5, column=11, value="").alignment = align_center

    for c in range(2, 14):
        cell = ws.cell(row=5, column=c)
        cell.font = font_regular
        cell.border = thin_border

    curr_row = 5
    first_section = True
    
    for section_header, items in defects.items():
        if not items:
            continue
            
        if not first_section:
            c_sec = ws.cell(row=curr_row, column=12, value=section_header)
            c_sec.font = font_bold
            c_sec.alignment = align_left
            c_sec.border = thin_border
            ws.cell(row=curr_row, column=13).border = thin_border
            ws.row_dimensions[curr_row].height = 25
            curr_row += 1
        else:
            c_sec = ws.cell(row=5, column=12, value=section_header)
            c_sec.font = font_bold
            c_sec.alignment = align_left
            c_sec.border = thin_border
            ws.cell(row=5, column=13).border = thin_border
            first_section = False
            curr_row = 6

        for item in items:
            c_bullet = ws.cell(row=curr_row, column=12, value="-")
            c_bullet.alignment = align_center
            c_bullet.font = font_regular
            c_bullet.border = thin_border
            
            c_desc = ws.cell(row=curr_row, column=13, value=item)
            c_desc.font = font_regular
            c_desc.alignment = align_left
            c_desc.border = thin_border
            
            line_estimate = max(1, len(item) // 75 + item.count("\n") + 1)
            ws.row_dimensions[curr_row].height = max(28, min(line_estimate * 18, 140))
            
            curr_row += 1

    wb.save(output_path)
    return output_path
