"""
Modul Fondasi & Utilitas Bersama Evaluator Publikasi BPS
Memuat konfigurasi, cache variasi AI, database wilayah, ISO 3297 ISSN validator,
dan utilitas deduplikasi temuan.
"""
import os
import sys
import re
import json
import copy
import fitz  # PyMuPDF
import openpyxl
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


# ─────────────────────────────────────────────────────────────────────────────
# MASTER DATA WILAYAH BPS SE-INDONESIA (38 PROVINSI, 514 KABUPATEN/KOTA, 7.200+ KECAMATAN)
# ─────────────────────────────────────────────────────────────────────────────
WILAYAH_DATA_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "indonesia_wilayah.json")
KECAMATAN_TO_KABUPATEN = {}
URL_SUBDOMAIN_TO_KABUPATEN = {}
ALL_REGENCIES_MAP = {}
DUPLICATE_KECAMATAN_MAP = {}
WILAYAH_METADATA = {}

if os.path.exists(WILAYAH_DATA_PATH):
    try:
        with open(WILAYAH_DATA_PATH, "r", encoding="utf-8") as f:
            _wil_data = json.load(f)
            KECAMATAN_TO_KABUPATEN = _wil_data.get("kecamatan_to_kabupaten", {})
            URL_SUBDOMAIN_TO_KABUPATEN = _wil_data.get("subdomain_to_kabupaten", {})
            ALL_REGENCIES_MAP = _wil_data.get("regencies", {})
            DUPLICATE_KECAMATAN_MAP = _wil_data.get("duplicate_kecamatan", {})
            WILAYAH_METADATA = _wil_data.get("metadata", {})
    except Exception:
        pass
# Fallback dasar jika file data belum termuat
if not KECAMATAN_TO_KABUPATEN:
    KECAMATAN_TO_KABUPATEN = {
        'baolan': 'Kabupaten Tolitoli', 'basidondo': 'Kabupaten Tolitoli', 'dako pemean': 'Kabupaten Tolitoli',
        'dondo': 'Kabupaten Tolitoli', 'dampal selatan': 'Kabupaten Tolitoli', 'dampal utara': 'Kabupaten Tolitoli',
        'galang': 'Kabupaten Tolitoli', 'lampasio': 'Kabupaten Tolitoli', 'ogodeide': 'Kabupaten Tolitoli', 'tolitoli utara': 'Kabupaten Tolitoli',
        'bahodopi': 'Kabupaten Morowali', 'bumi raya': 'Kabupaten Morowali', 'bungku barat': 'Kabupaten Morowali',
        'bungku pesisir': 'Kabupaten Morowali', 'bungku selatan': 'Kabupaten Morowali', 'bungku tengah': 'Kabupaten Morowali',
        'bungku timur': 'Kabupaten Morowali', 'menui kepulauan': 'Kabupaten Morowali', 'wita ponda': 'Kabupaten Morowali',
        'buko': 'Kabupaten Banggai Kepulauan', 'buko selatan': 'Kabupaten Banggai Kepulauan', 'bulagi': 'Kabupaten Banggai Kepulauan',
        'bulagi selatan': 'Kabupaten Banggai Kepulauan', 'bulagi utara': 'Kabupaten Banggai Kepulauan', 'tinangkung': 'Kabupaten Banggai Kepulauan',
        'tinangkung selatan': 'Kabupaten Banggai Kepulauan', 'tinangkung utara': 'Kabupaten Banggai Kepulauan', 'liang': 'Kabupaten Banggai Kepulauan',
        'peling tengah': 'Kabupaten Banggai Kepulauan', 'totikum': 'Kabupaten Banggai Kepulauan', 'totikum selatan': 'Kabupaten Banggai Kepulauan',
        'petasia': 'Kabupaten Morowali Utara', 'petasia timur': 'Kabupaten Morowali Utara', 'petasia barat': 'Kabupaten Morowali Utara',
        'lembo': 'Kabupaten Morowali Utara', 'lembo raya': 'Kabupaten Morowali Utara', 'mori atas': 'Kabupaten Morowali Utara',
        'mori utara': 'Kabupaten Morowali Utara', 'soyo jaya': 'Kabupaten Morowali Utara', 'bungku utara': 'Kabupaten Morowali Utara',
        'mamosalato': 'Kabupaten Morowali Utara',
        'balantak': 'Kabupaten Banggai', 'batui': 'Kabupaten Banggai', 'bualemo': 'Kabupaten Banggai', 'bunta': 'Kabupaten Banggai',
        'luwuk': 'Kabupaten Banggai', 'luwuk selatan': 'Kabupaten Banggai', 'toili': 'Kabupaten Banggai',
        'banggai': 'Kabupaten Banggai Laut', 'banggai selatan': 'Kabupaten Banggai Laut', 'banggai tengah': 'Kabupaten Banggai Laut',
        'banggai utara': 'Kabupaten Banggai Laut', 'labobo': 'Kabupaten Banggai Laut', 'bangkurung': 'Kabupaten Banggai Laut',
        'bokan kepulauan': 'Kabupaten Banggai Laut',
        'biau': 'Kabupaten Buol', 'bokat': 'Kabupaten Buol', 'momunu': 'Kabupaten Buol',
        'banawa': 'Kabupaten Donggala', 'sindue': 'Kabupaten Donggala', 'sojol': 'Kabupaten Donggala',
        'parigi': 'Kabupaten Parigi Moutong', 'moutong': 'Kabupaten Parigi Moutong', 'tinombo': 'Kabupaten Parigi Moutong',
        'lage': 'Kabupaten Poso', 'lore barat': 'Kabupaten Poso', 'pamona utara': 'Kabupaten Poso', 'poso kota': 'Kabupaten Poso',
        'dolo': 'Kabupaten Sigi', 'kulawi': 'Kabupaten Sigi', 'marawola': 'Kabupaten Sigi',
        'ampana kota': 'Kabupaten Tojo Una-Una', 'una-una': 'Kabupaten Tojo Una-Una',
        'mantikulore': 'Kota Palu', 'palu barat': 'Kota Palu', 'palu timur': 'Kota Palu'
    }

if not URL_SUBDOMAIN_TO_KABUPATEN:
    URL_SUBDOMAIN_TO_KABUPATEN = {
        'tolitoli': 'Kabupaten Tolitoli', 'morowali': 'Kabupaten Morowali', 'morowaliutara': 'Kabupaten Morowali Utara',
        'morut': 'Kabupaten Morowali Utara', 'banggaikep': 'Kabupaten Banggai Kepulauan', 'bangkep': 'Kabupaten Banggai Kepulauan',
        'banggailaut': 'Kabupaten Banggai Laut', 'banglai': 'Kabupaten Banggai Laut', 'banggai': 'Kabupaten Banggai',
        'donggala': 'Kabupaten Donggala', 'poso': 'Kabupaten Poso', 'buol': 'Kabupaten Buol', 'palu': 'Kota Palu',
        'parigimoutong': 'Kabupaten Parigi Moutong', 'parigi': 'Kabupaten Parigi Moutong', 'tojounauna': 'Kabupaten Tojo Una-Una',
        'sigi': 'Kabupaten Sigi'
    }

def detect_kabupaten_name(pdf_path=None, pages_text=None, region_name="Wilayah", pub_title="", is_kabupaten=False):
    """
    Deteksi nama Kabupaten/Kota secara 100% dinamis dan universal untuk SELURUH INDONESIA
    (38 Provinsi, 514 Kabupaten/Kota, dan 6.700+ Kecamatan).
    Prioritas tertinggi:
    1. Teks riil publikasi (Penerbit Katalog, URL Subdomain portal BPS, identitas Satker BPS pada kover/HJU/pengantar).
    2. Master Database Wilayah BPS Nasional (indonesia_wilayah.json) untuk mencocokkan kecamatan dengan kabupatennya.
    3. Derivasi dinamis untuk kabupaten/kota manapun di Indonesia.
    """
    if is_kabupaten:
        rn = region_name.strip()
        if rn.lower().startswith("kabupaten") or rn.lower().startswith("kota"):
            return rn
        is_title_kota = bool(pub_title and re.search(r'\bKota\s+', pub_title, re.I))
        is_title_kab = bool(pub_title and re.search(r'\bKabupaten\s+', pub_title, re.I))
        if is_title_kota:
            for reg_name in ALL_REGENCIES_MAP.values():
                if reg_name.lower() == f"kota {rn.lower()}":
                    return reg_name
            return f"Kota {rn}"
        elif is_title_kab:
            for reg_name in ALL_REGENCIES_MAP.values():
                if reg_name.lower() == f"kabupaten {rn.lower()}":
                    return reg_name
            return f"Kabupaten {rn}"
        for reg_name in ALL_REGENCIES_MAP.values():
            if reg_name.lower() == f"kota {rn.lower()}":
                return reg_name
            if reg_name.lower() == f"kabupaten {rn.lower()}":
                return reg_name
        return f"Kabupaten {rn}"

    # 1. Ekstraksi teks awal dokumen (Kover, HJU, Katalog, Pengantar)
    all_text = ""
    if pages_text and isinstance(pages_text, dict):
        all_text = " ".join([str(v) for k, v in sorted(pages_text.items(), key=lambda x: int(x[0]) if str(x[0]).isdigit() else 999) if (str(k).isdigit() and int(k) < 15)])
    elif pdf_path and os.path.exists(pdf_path):
        try:
            doc = fitz.open(pdf_path)
            all_text = " ".join([doc[i].get_text() for i in range(min(15, len(doc)))])
            doc.close()
        except Exception:
            pass

    if all_text:
        # A. Penerbit resmi pada Halaman Katalog (Published by BPS Kabupaten/Kota ...)
        m_pub = re.search(r'(?:Penerbit|Diterbitkan oleh|Published by)[^:\n]*[:\n]\s*(?:Badan Pusat Statistik|BPS)\s+(Kabupaten|Kota)\s+([A-Za-z\s]+?)(?:/|,|\n|\.|\r|$)', all_text, re.I)
        if m_pub:
            kb_type = m_pub.group(1).title()
            kb_name = m_pub.group(2).strip().title()
            if "xxxx" not in kb_name.lower() and len(kb_name) >= 3 and kb_name.lower() not in ['indonesia', 'provinsi']:
                return f"{kb_type} {kb_name}"

        # B. URL portal resmi BPS Kabupaten/Kota (https://[kab]kab.bps.go.id atau https://[kota]kota.bps.go.id)
        m_url = re.search(r'https?://([a-z0-9\-]+)(?:kab|kota)?\.bps\.go\.id', all_text, re.I)
        if m_url:
            sub = m_url.group(1).lower().replace('-', '')
            # Cek kamus subdomain terdaftar nasional (diurutkan dari kunci terpanjang)
            for k in sorted(URL_SUBDOMAIN_TO_KABUPATEN.keys(), key=len, reverse=True):
                if k in sub:
                    return URL_SUBDOMAIN_TO_KABUPATEN[k]
            # Derivasi dinamis untuk kabupaten/kota manapun di Indonesia
            clean_sub = sub.replace('kab', '').replace('kota', '').strip()
            if clean_sub and len(clean_sub) >= 3 and "xxxx" not in clean_sub:
                kb_type = "Kota" if "kota" in sub else "Kabupaten"
                return f"{kb_type} {clean_sub.title()}"

        # C. Identitas Satker BPS pada Kover / HJU / Pengantar
        m_bps = re.search(r'(?:Badan Pusat Statistik|BPS)\s+(Kabupaten|Kota)\s+([A-Za-z\s]+?)(?:/|,|\n|\.|\r|$)', all_text, re.I)
        if m_bps:
            kb_type = m_bps.group(1).title()
            kb_name = m_bps.group(2).strip().title()
            kb_name = re.sub(r'\s+(Dalam|Tahun|Untuk|Pada|Di|Serta|Dan)$', '', kb_name, flags=re.I).strip()
            if "xxxx" not in kb_name.lower() and len(kb_name) >= 3 and kb_name.lower() not in ['indonesia', 'provinsi', 'sulawesi tengah']:
                return f"{kb_type} {kb_name}"

        # D. BPS-Statistics of [Regency] Regency/Municipality
        m_stat = re.search(r'BPS[-–—\s]*Statistics\s+of\s+([A-Za-z\s]+?)\s+(?:Regency|Municipality)', all_text, re.I)
        if m_stat:
            kb_name = m_stat.group(1).strip().title()
            if "xxxx" not in kb_name.lower() and len(kb_name) >= 3:
                return f"Kabupaten {kb_name}"

        # E. Kata Pengantar Kepala BPS Kabupaten/Kota
        m_kepala = re.search(r'Kepala\s+(?:Badan Pusat Statistik|BPS)\s+(Kabupaten|Kota)\s+([A-Za-z\s]+?)(?:/|,|\n|\.|\r|$)', all_text, re.I)
        if m_kepala:
            kb_type = m_kepala.group(1).title()
            kb_name = m_kepala.group(2).strip().title()
            if "xxxx" not in kb_name.lower() and len(kb_name) >= 3 and kb_name.lower() not in ['indonesia', 'provinsi']:
                return f"{kb_type} {kb_name}"

    # 2. Master Database Wilayah BPS Nasional (Pencocokan Kecamatan se-Indonesia):
    rn_clean = (region_name or "").lower().strip()
    if rn_clean in KECAMATAN_TO_KABUPATEN:
        return KECAMATAN_TO_KABUPATEN[rn_clean]

    if rn_clean.startswith("kecamatan "):
        sub_rn = rn_clean.replace("kecamatan ", "").strip()
        if sub_rn in KECAMATAN_TO_KABUPATEN:
            return KECAMATAN_TO_KABUPATEN[sub_rn]

    # Cek jika region_name adalah nama kabupaten/kota itu sendiri
    for reg_name in ALL_REGENCIES_MAP.values():
        if rn_clean in reg_name.lower():
            return reg_name

    return f"Kabupaten {region_name}"

def find_page_with_text(doc, *keywords, start_page=0, end_page=None):
    total = len(doc)
    if total == 0 or start_page >= total:
        return -1
    if end_page is None or end_page > total:
        end_page = total
    if start_page < 0:
        start_page = 0
    for i in range(start_page, end_page):
        txt = doc[i].get_text("text").upper()
        if all(kw.upper() in txt for kw in keywords):
            return i
    return -1


def validate_issn_checksum(issn_str):
    """
    Validasi Check Digit Standar Internasional ISO 3297 (Modulo 11).
    Digunakan secara resmi oleh BRIN (Badan Riset dan Inovasi Nasional) /
    Pusat Data dan Dokumentasi Ilmiah (PDDI) untuk seluruh nomor ISSN di Indonesia.
    Setiap nomor ISSN terdiri dari 8 karakter: 7 digit data + 1 check digit (0-9 atau X).
    Rumus: Sum((9 - i) * d_i) mod 11 == 0.
    """
    clean = re.sub(r'[^0-9X]', '', issn_str.upper())
    if len(clean) != 8:
        return False, None
    weights = [8, 7, 6, 5, 4, 3, 2, 1]
    total = 0
    for i in range(7):
        if not clean[i].isdigit():
            return False, None
        total += int(clean[i]) * weights[i]
    
    last = clean[7]
    val = 10 if last == 'X' else int(last) if last.isdigit() else -1
    if val == -1:
        return False, None
    total += val * weights[7]
    
    is_valid = (total % 11 == 0)
    expected_rem = (total - val) % 11
    expected_check = 0 if expected_rem == 0 else (11 - expected_rem)
    expected_char = 'X' if expected_check == 10 else str(expected_check)
    return is_valid, expected_char


def scan_cover_raster_header(page):
    """
    Memindai blok kover depan / halaman judul utama (sudut kanan atas)
    untuk mendeteksi secara akurat keberadaan ISSN, titik dua pada ISSN,
    dan spasi sebelum titik dua pada label Katalog.
    """
    try:
        rect = fitz.Rect(page.rect.width * 0.40, 0, page.rect.width, page.rect.height * 0.22)
        has_images = len(page.get_images()) >= 1

        # Jika halaman memuat objek gambar (raster/cover template), selalu prioritaskan pemindaian visual OCR
        # untuk menghindari tertipu oleh text layer tak kasat mata (ghost text) di balik gambar.
        if has_images:
            try:
                from rapidocr_onnxruntime import RapidOCR
                if not hasattr(scan_cover_raster_header, '_rapid_engine'):
                    scan_cover_raster_header._rapid_engine = RapidOCR()
                engine = scan_cover_raster_header._rapid_engine
                pix = page.get_pixmap(clip=rect, dpi=200)
                img = cv2.imdecode(np.frombuffer(pix.tobytes("png"), np.uint8), cv2.IMREAD_COLOR)
                if img is not None:
                    ocr_res, _ = engine(img)
                    if ocr_res:
                        ocr_texts = [r[1] for r in ocr_res]
                        combined_ocr = " ".join(ocr_texts)
                        has_issn = bool(re.search(r'\bISSN\b', combined_ocr, re.IGNORECASE))
                        has_colon = bool(re.search(r'\bISSN\s*:', combined_ocr, re.IGNORECASE))
                        catalog_space_colon = bool(re.search(r'(?:Katalog|Catalogue)\s+:', combined_ocr, re.IGNORECASE))
                        return {
                            "has_issn": has_issn,
                            "has_colon": has_colon,
                            "catalog_space_colon": catalog_space_colon
                        }
            except Exception:
                pass

        txt_clip = page.get_text("text", clip=rect)
        if txt_clip and any(c.isalnum() for c in txt_clip):
            has_issn = bool(re.search(r'\bISSN\b', txt_clip, re.IGNORECASE))
            has_colon = bool(re.search(r'\bISSN\s*:', txt_clip, re.IGNORECASE))
            catalog_space_colon = bool(re.search(r'(?:Katalog|Catalogue)\s+:', txt_clip, re.IGNORECASE))
            return {
                "has_issn": has_issn,
                "has_colon": has_colon,
                "catalog_space_colon": catalog_space_colon
            }

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
                        
        # Baris ISSN (pada layout raster, minimal 3 baris jika label & nomor katalog terpisah baris)
        if len(sorted_lines) >= 3:
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
            '2. Pembersihan Template: Pastikan tidak ada teks sisa draft/template seperti "COVER BELAKANG" atau identitas placeholder "KABUPATEN/KOTA XXXX" yang tertinggal.'
        )
    }

def classify_cover_finding(it):
    it_l = it.lower()
    if 'kesalahan format penulisan nomor issn' in it_l or (
        'issn' in it_l and ('titik dua' in it_l or 'tanpa tanda titik dua' in it_l or 'kata issn' in it_l)
        and not 'spasi pada nomor katalog' in it_l and not it_l.startswith('penulisan nomor katalog')
    ):
        return 'issn_format'
    if 'nomor issn pada kover depan belum dicantumkan' in it_l or 'xxxx -xxxx' in it_l or 'issn xxxx' in it_l:
        return 'issn_placeholder'
    if 'nomor katalog pada kover depan masih berupa' in it_l or '1102001.xxxx' in it_l:
        return 'catalog_placeholder'
    if 'volume terbitan pada kover depan' in it_l or 'volume xx' in it_l:
        return 'volume_placeholder'
    if 'opsi ganda template' in it_l or 'kabupaten/kota' in it_l:
        return 'agency_dual'
    if 'kesalahan spasi pada nomor katalog' in it_l or (
        'katalog' in it_l and ('spasi' in it_l or 'titik dua' in it_l)
        and not 'penulisan nomor issn' in it_l and not it_l.startswith('format penulisan issn')
    ):
        return 'katalog_spasi'
    if 'huruf "a"' in it_l or 'huruf a' in it_l or 'residu huruf' in it_l or 'sisa huruf template' in it_l:
        return 'letter_a'
    if ('miring' in it_l or 'italic' in it_l) and ('judul' in it_l or 'district' in it_l or 'bahasa inggris' in it_l or 'bahasa asing' in it_l):
        return 'italic_title'
    if 'xxxxx' in it_l or 'residu teks placeholder' in it_l:
        return 'placeholder'
    if 'logo' in it_l and ('warna' in it_l or 'berwarna' in it_l or 'monokrom' in it_l or 'outline' in it_l or 'stroke' in it_l or 'bayangan' in it_l or 'shadow' in it_l):
        return 'cover_logo'
    return 'other'

def classify_hju_finding(it):
    it_l = it.lower()
    if 'residu teks template' in it_l or 'format template master' in it_l or '1102001.xxxx' in it_l or 'issn xxxx' in it_l or 'teks template tersembunyi' in it_l:
        return 'hju_template'
    if 'latar belakang' in it_l or 'tanpa ilustrasi' in it_l or 'bebas ilustrasi' in it_l or 'duplikasi visual kover depan' in it_l:
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
    if 'saltik spasi' in it_l or 'kecamata n' in it_l:
        return 'hju_typo_spasi'
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


def sanitize_invisible_unicode(s):
    """
    Menghilangkan seluruh karakter tak kasat mata (invisible unicode), zero-width characters,
    soft hyphens, dan byte-order-marks yang secara visual tidak tampak oleh manusia,
    tetapi kerap mengacaukan pembacaan regex dan evaluasi teks PDF.
    """
    if not s or not isinstance(s, str):
        return ""
    # Hapus BOM, zero-width characters, soft hyphens, dan invisible directional marks
    clean = (
        s.replace('\ufeff', '')   # BOM / Zero-width no-break space
         .replace('\u200b', '')   # Zero-width space
         .replace('\u200c', '')   # Zero-width non-joiner
         .replace('\u200d', '')   # Zero-width joiner
         .replace('\u00ad', '')   # Soft hyphen (InDesign layout hyphenation)
         .replace('\u2060', '')   # Word joiner
         .replace('\u200e', '')   # LTR mark
         .replace('\u200f', '')   # RTL mark
         .replace('\xa0', ' ')    # Non-breaking space -> regular space
         .replace('\u202f', ' ')  # Narrow no-break space -> regular space
         .replace('\u2009', ' ')  # Thin space -> regular space
         .replace('\u200a', ' ')  # Hair space -> regular space
    )
    # Normalisasi ligatur tipografi umum (InDesign font ligatures)
    clean = (
        clean.replace('\ufb01', 'fi')
             .replace('\ufb02', 'fl')
             .replace('\ufb00', 'ff')
             .replace('\ufb03', 'ffi')
             .replace('\ufb04', 'ffl')
    )
    return clean

