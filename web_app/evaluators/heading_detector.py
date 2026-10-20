"""
web_app/evaluators/heading_detector.py
======================================
Modul Pendeteksi Judul Bagian Anatomi (Section Heading & Boundary Detector).

Tujuan:
1. Menemukan halaman fisik yang BENAR-BENAR merupakan awal dari suatu bagian anatomi
   (Kata Pengantar, Tim Penyusun, Daftar Isi, Daftar Tabel, Daftar Gambar, Penjelasan Umum, Daftar Pustaka).
2. Mencegah terjebak oleh entri daftar isi (*Table of Contents reference line*).
   Contoh: "Penjelasan Umum / General Notes .......... xi" pada Daftar Isi TIDAK BOLEH
   dideteksi sebagai halaman Penjelasan Umum itu sendiri.
3. Memastikan blok judul berada di area atas halaman fisik (y < 180 pt) sebagai judul utama bab/bagian.
"""

import re
import fitz


def is_toc_listing_line(text, keyword):
    """
    Memeriksa apakah kemunculan keyword pada text hanyalah entri baris daftar isi
    yang diikuti deretan titik-titik (elipsis) dan rujukan nomor halaman.
    Contoh: 'Penjelasan Umum / General Notes .................... xi' -> True
    """
    if not text:
        return False
    # Bersihkan spasi berlebih
    escaped_kw = re.escape(keyword)
    return bool(re.search(rf'{escaped_kw}[^\n\.]*\.{{3,}}\s*(?:\d+|[ivxlcdm]+)', text, re.I))


def is_page_a_table_of_contents(text):
    """
    Memeriksa apakah halaman tertentu merupakan halaman Daftar Isi / Daftar Tabel
    berdasarkan densitas deretan titik-titik perujuk halaman (>= 3 baris elipsis).
    """
    if not text:
        return False
    dot_matches = len(re.findall(r'\.{4,}\s*(?:\d+|[ivxlcdm]+)', text, re.I))
    return dot_matches >= 3


def find_true_section_page(doc, title_kw, start_page=0, end_page=None, max_y=200):
    """
    Mencari indeks halaman fisik tempat judul bagian anatomi tercetak sebagai HEADING UTAMA:
    1. Memindai blok-blok teks di halaman dari start_page sampai end_page.
    2. Menolak halaman jika kemunculan keyword hanyalah baris entri daftar isi dengan titik-titik.
    3. Memvalidasi bahwa blok judul berada di area atas halaman fisik (y0 < max_y pt).
    """
    total = len(doc)
    if total == 0 or start_page >= total:
        return -1
    if end_page is None or end_page > total:
        end_page = total
    if start_page < 0:
        start_page = 0

    title_kw_up = title_kw.upper().strip()

    for p in range(start_page, end_page):
        page_txt = doc[p].get_text("text")
        if title_kw_up not in page_txt.upper():
            continue

        # Jika halaman ini adalah Daftar Isi dan keyword diikuti titik-titik rujukan halaman, lewati!
        if is_toc_listing_line(page_txt, title_kw):
            continue

        # Periksa blok-blok teks di halaman: blok judul harus berada di bagian atas
        for b in doc[p].get_text("blocks"):
            b_txt = b[4].strip().upper()
            if title_kw_up in b_txt and b[1] <= max_y:
                # Pastikan blok tersebut bukan baris rujukan berelipsis
                if not is_toc_listing_line(b[4], title_kw):
                    return p

    # Fallback pencarian standar jika tidak ditemukan blok di atas (misal layout khusus)
    for p in range(start_page, end_page):
        page_txt = doc[p].get_text("text")
        if title_kw_up in page_txt.upper() and not is_toc_listing_line(page_txt, title_kw):
            return p

    return -1
