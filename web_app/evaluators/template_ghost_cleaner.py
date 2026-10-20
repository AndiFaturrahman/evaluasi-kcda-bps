"""
web_app/evaluators/template_ghost_cleaner.py
============================================
Pembersih Residu Teks & Template Tersembunyi (Ghost Text & Master Template Cleaner)

Tujuan:
1. Memastikan kaidah: "Nilai apa yang kasat mata bagi pembaca, abaikan apa yang tak kasat mata".
2. Meneliti apakah pola-pola template yang dicurigai (misal '1102001.xxxx', 'ISSN XXXX -XXXX',
   'Volume XX', 'KABUPATEN/KOTA', 'NAMA TANPA GELAR', 'xxxxx • xxxxx', 'Lorem ipsum'):
   - Benar-benar kasat mata (tercetak dengan piksel gelap yang terlihat pembaca).
   - ATAU hanya teks residu transparan di balik gambar latar belakang / kanvas putih.
3. Membersihkan variabel halaman dan naskah dokumen sehingga teks tersembunyi tidak
   memicu alarm palsu pada modul evaluasi lainnya.
"""

import re
import fitz
from .visual_verifier import is_block_visually_visible


def filter_visible_template_markers(doc, pattern_regex, min_dark_pixels=15):
    """
    Mencari seluruh halaman di mana pola template tertentu benar-benar KASAT MATA.
    Jika pola hanya ada di text layer PDF tetapi di gambar rendered memiliki 0 piksel gelap
    (tak kasat mata / tertutup gambar putih), maka halaman tersebut DIABAIKAN.
    
    Mengembalikan: list nomor halaman fisik (1-indexed) yang memuat teks kasat mata.
    """
    visible_pages = []
    total = len(doc)
    compiled_pat = re.compile(pattern_regex, re.IGNORECASE) if isinstance(pattern_regex, str) else pattern_regex

    for p in range(total):
        page_txt = doc[p].get_text("text")
        if not compiled_pat.search(page_txt):
            continue

        # Periksa setiap blok yang cocok dengan pola
        has_visible_match = False
        blocks = doc[p].get_text("blocks")
        for b in blocks:
            b_txt = b[4]
            if compiled_pat.search(b_txt):
                if is_block_visually_visible(doc[p], b[:4], min_dark_pixels=min_dark_pixels):
                    has_visible_match = True
                    break

        if has_visible_match:
            visible_pages.append(p + 1)

    return visible_pages


def sanitize_text_for_page(page, raw_text, placeholder_patterns):
    """
    Membersihkan teks dari string placeholder yang tak kasat mata.
    Jika suatu placeholder ditemukan di raw_text tetapi terbukti tak kasat mata di halaman fisik,
    placeholder tersebut dihapus dari teks representasi halaman.
    """
    cleaned_text = raw_text
    blocks = page.get_text("blocks")

    for pat in placeholder_patterns:
        compiled = re.compile(pat, re.IGNORECASE) if isinstance(pat, str) else pat
        matches = list(compiled.finditer(cleaned_text))
        if not matches:
            continue

        # Cari blok tempat teks tersebut berada
        is_visible = False
        for b in blocks:
            if compiled.search(b[4]):
                if is_block_visually_visible(page, b[:4], min_dark_pixels=15):
                    is_visible = True
                    break

        # Jika tak kasat mata, hapus dari cleaned_text
        if not is_visible:
            cleaned_text = compiled.sub("", cleaned_text)

    return cleaned_text
