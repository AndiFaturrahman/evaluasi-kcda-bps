"""
web_app/evaluators/visual_verifier.py
======================================
Modul Penegakan Kaidah Baku Visual: "ABAIKAN YANG TAK KASAT MATA!"

Fungsi Utama:
1. is_block_visually_visible:
   Memverifikasi apakah suatu teks / blok koordinat benar-benar tercetak kasat mata
   pada gambar halaman fisik (bukan teks transparan, bukan ghost text di balik gambar putih,
   dan bukan residu master template tersembunyi).
2. has_visible_header_running_title:
   Memeriksa apakah margin atas halaman (y <= 8.5% tinggi halaman) memuat running title fisik,
   dengan mengecualikan klaster nomor katalog/ISSN di pojok kanan atas pada HJU.
3. has_visible_footer_page_number:
   Memeriksa keberadaan nomor halaman fisik kasat mata di margin bawah (y >= 92% tinggi halaman).
4. inspect_preliminary_running_title:
   Audit kepatuhan Pedoman BPS 2023 Bab 4.3 (hal. 49): Halaman pendahuluan (angka Romawi)
   DILARANG memuat running title pada header atas. Menjamin judul bab/buku di badan halaman
   TIDAK keliru didiagnosis sebagai running title.
5. verify_text_visibility_on_page:
   Memeriksa apakah string/pola tertentu kasat mata di halaman fisik menggunakan OCR visual
   atau uji densitas piksel gelap pada area teks.
"""

import re
import cv2
import numpy as np
import fitz


def is_block_visually_visible(page, bbox, min_dark_pixels=15, dark_threshold=200, dpi=150):
    """
    Memeriksa apakah bounding box (x0, y0, x1, y1) memiliki piksel teks kasat mata (gelap).
    Mengembalikan True jika kasat mata, False jika tak kasat mata (0 atau < min_dark_pixels).
    """
    try:
        r = fitz.Rect(bbox)
        if r.width <= 0 or r.height <= 0:
            return False
        zoom = dpi / 72.0
        # Tambahkan sedikit margin 1 pt
        padded = fitz.Rect(max(0, r.x0 - 1), max(0, r.y0 - 1), min(page.rect.width, r.x1 + 1), min(page.rect.height, r.y1 + 1))
        pix = page.get_pixmap(clip=padded, matrix=fitz.Matrix(zoom, zoom))
        img = cv2.imdecode(np.frombuffer(pix.tobytes("png"), np.uint8), cv2.IMREAD_COLOR)
        if img is None or img.size == 0:
            return False
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        dark_count = int(np.sum(gray < dark_threshold))
        return dark_count >= min_dark_pixels
    except Exception:
        return False


def has_visible_header_running_title(page, max_y_ratio=0.085, exclude_catalog_cluster=False, min_dark_pixels=20):
    """
    Memeriksa apakah margin header atas memuat teks fisik kasat mata (running title).
    Jika exclude_catalog_cluster=True, area pojok kanan atas (x > 40%, y < 25%) dikecualikan.
    """
    try:
        pw, ph = page.rect.width, page.rect.height
        if exclude_catalog_cluster:
            # Potong header sebelah kiri/tengah di luar klaster katalog pojok kanan atas
            rect_header = fitz.Rect(0, 0, pw * 0.45, ph * max_y_ratio)
        else:
            rect_header = fitz.Rect(0, 0, pw, ph * max_y_ratio)

        zoom = 150 / 72.0
        pix = page.get_pixmap(clip=rect_header, matrix=fitz.Matrix(zoom, zoom))
        img = cv2.imdecode(np.frombuffer(pix.tobytes("png"), np.uint8), cv2.IMREAD_COLOR)
        if img is None or img.size == 0:
            return False, ""

        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        dark_pixels = int(np.sum(gray < 200))
        if dark_pixels < min_dark_pixels:
            return False, ""

        # Jika ada piksel gelap, ambil teks kasat mata melalui blok atau OCR
        header_text = page.get_text("text", clip=rect_header).strip()
        return True, header_text
    except Exception:
        return False, ""


def has_visible_footer_page_number(page, min_y_ratio=0.88, min_dark_pixels=15):
    """
    Memeriksa apakah margin footer bawah memuat nomor halaman fisik kasat mata (Arab / Romawi).
    HANYA dianggap nomor halaman fisik jika blok/span nomor halaman tersebut riil kasat mata
    (memiliki piksel gelap, bukan teks vektor tersembunyi / ghost text).
    """
    if page is None:
        return False, ""

    try:
        pw, ph = page.rect.width, page.rect.height
        
        # Pola nomor halaman (Romawi atau Arab)
        roman_pattern = re.compile(r'^(?:[ivxlcdm]+)$', re.I)
        digit_pattern = re.compile(r'^\d{1,4}$')
        
        d = page.get_text("dict")
        for b in d.get("blocks", []):
            for l in b.get("lines", []):
                lx0, ly0, lx1, ly1 = l["bbox"]
                ly_mid = (ly0 + ly1) / 2.0
                if ly_mid < ph * min_y_ratio:
                    continue
                
                line_text = "".join(s.get("text", "") for s in l.get("spans", [])).strip()
                if not line_text:
                    continue
                # Abaikan teks instansi, website, atau alamat yang mungkin berada di footer
                if any(k in line_text.lower() for k in ["bps", "badan pusat", "kabupaten", "kota", "regency", "http", "jl."]):
                    continue
                
                # Cek apakah span berupa nomor halaman
                for s in l.get("spans", []):
                    st = s.get("text", "").strip()
                    if digit_pattern.match(st) or roman_pattern.match(st):
                        # Periksa visibilitas fisik dari bounding box span tersebut
                        if is_block_visually_visible(page, s["bbox"], min_dark_pixels=min_dark_pixels):
                            return True, st
        
        return False, ""
    except Exception:
        return False, ""


def inspect_preliminary_running_title(page, is_hju=False):
    """
    Pemeriksaan Khusus Running Title Halaman Pendahuluan (Angka Romawi):
    Sesuai Pedoman BPS 2023 Bab 4.3 (hal. 49) & Instrumen baris 22, 43, 53, 75, 106.
    
    Kaidah Baku:
    - Running title adalah teks di margin ATAS (header).
    - Judul halaman / subjudul buku di badan halaman ("Kecamatan ... Dalam Angka") BUKAN running title!
    - Teks tersembunyi/ghost text dengan 0 piksel gelap DILARANG dilaporkan sebagai pelanggaran.
    
    Mengembalikan: (has_running_title: bool, header_snippet: str)
    """
    if page is None:
        return False, ""

    # Periksa keberadaan piksel teks kasat mata di margin header atas
    has_visible, txt = has_visible_header_running_title(page, max_y_ratio=0.08, exclude_catalog_cluster=is_hju)
    if not has_visible:
        return False, ""

    # Jika ada piksel gelap di header, pastikan itu bukan noise / garis batas
    ph = page.rect.height
    for b in page.get_text("blocks"):
        # Hanya blok yang berada tepat di header margin atas (y1 <= 8% ph)
        if b[3] <= ph * 0.08:
            txt_b = b[4].strip()
            if not txt_b or "bps.go.id" in txt_b.lower():
                continue
            if is_hju and b[0] > page.rect.width * 0.40:
                continue
            # Verifikasi piksel gelap pada blok tersebut
            if is_block_visually_visible(page, b[:4], min_dark_pixels=15):
                return True, txt_b

    return False, ""


def verify_template_placeholder_is_visible(page, pattern_str):
    """
    Memeriksa apakah pola placeholder template (misal '1102001.xxxx', 'ISSN XXXX -XXXX')
    benar-benar tercetak kasat mata di halaman, bukan residu tak kasat mata di balik gambar.
    """
    try:
        found_block = None
        for b in page.get_text("blocks"):
            if re.search(pattern_str, b[4], re.I):
                found_block = b
                break
        if not found_block:
            return False

        # Uji densitas piksel gelap pada area blok
        return is_block_visually_visible(page, found_block[:4], min_dark_pixels=15)
    except Exception:
        return False
