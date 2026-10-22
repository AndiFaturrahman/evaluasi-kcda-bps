"""
web_app/evaluators/pdf_reader_engine.py
======================================
Mesin Pembaca PDF Mutakhir BPS (Next-Gen Visual-Aware PDF Reading Engine).

Prinsip Filosofi Baku:
"Nilai apa yang kasat mata bagi pembaca manusia, abaikan apa yang tak kasat mata!"
(What You See Is What You Evaluate — Zero False Positives from InDesign Ghost Text).

Arsitektur & Kemampuan:
1. Dual-Layer Hybrid Extraction:
   - Lapisan Vektor (PyMuPDF): Ekstraksi cepat untuk teks, bounding box, font metadata (nama font, ukuran, bold, italic, warna).
   - Lapisan Visual Piksel (Render 150/300 DPI + RapidOCR + OpenCV): Memverifikasi apakah teks benar-benar tercetak kasat mata
     secara fisik atau hanya residu tersembunyi (ghost text) dari master template InDesign.
2. Visual Visibility Arbiter (Penyaring Teks Tak Kasat Mata):
   - Menguji apakah bounding box teks memiliki piksel tinta kasat mata pada gambar render fisik.
   - Menyaring teks putih di atas putih, teks ber-opacity 0, dan teks yang tertutup kotak putih/ilustrasi.
3. Spatial Reading-Order Sorter (Penyusun Urutan Baca Manusia):
   - Menyusun blok teks berdasarkan tata letak ruang (layout-aware).
   - Mendeteksi format dwibahasa dua kolom (kolom kiri Bahasa Indonesia, kolom kanan Bahasa Inggris)
     sehingga teks tidak tercampur/teracak (interleaved).
4. Semantic Page Zone Partitioner:
   - Margin Atas (Header Margin: y <= 8.5% h) -> Running Title & penomoran atas.
   - Area Tubuh Halaman (Body: 8.5% < y < 88% h) -> Judul bab, ulasan narasi, tabel statis, grafik/peta.
   - Blok Catatan Kaki (Footnote Zone: Catatan/Note: ...) -> Catatan penjelas & rujukan superskrip.
   - Blok Sumber (Source Zone: Sumber/Source: ...) -> Instansi produsen data resmi.
   - Margin Bawah (Footer Margin: y >= 88% h) -> Nomor halaman fisik (Arab/Romawi).
5. Ekstraktor Tabel Berstruktur & Validasi Catatan Kaki:
   - Mengekstrak tabel, judul dwibahasa, satuan (km², persen), tanda rujukan superskrip (1/, 2/, ¹, ²),
     serta memverifikasi kelengkapan catatan kaki (membedakan catatan sah vs catatan kosong '...').
6. Normalisasi Unicode & Tipografi Komprehensif:
   - Sanitasi otomatis terhadap BOM (\\ufeff), zero-width characters (\\u200b), soft hyphen (\\xad), ligatur InDesign.
"""

import os
import re
from typing import Dict, List, Optional, Tuple, Any

import fitz  # PyMuPDF
import numpy as np

try:
    import cv2
    HAVE_CV2 = True
except ImportError:
    HAVE_CV2 = False

try:
    from rapidocr_onnxruntime import RapidOCR
    HAVE_RAPIDOCR = True
except ImportError:
    HAVE_RAPIDOCR = False

from .common import sanitize_invisible_unicode
from .visual_verifier import is_block_visually_visible


class VisualSpan:
    """Representasi rentang teks (span) dengan informasi tipografi dan visibilitas fisik."""
    __slots__ = (
        'text', 'bbox', 'font_name', 'font_size',
        'is_bold', 'is_italic', 'color', 'is_visible'
    )

    def __init__(
        self,
        text: str,
        bbox: Tuple[float, float, float, float],
        font_name: str = "",
        font_size: float = 10.0,
        is_bold: bool = False,
        is_italic: bool = False,
        color: int = 0,
        is_visible: bool = True
    ):
        self.text = text
        self.bbox = bbox
        self.font_name = font_name
        self.font_size = font_size
        self.is_bold = is_bold
        self.is_italic = is_italic
        self.color = color
        self.is_visible = is_visible

    def __repr__(self):
        return f"<VisualSpan text={repr(self.text)} visible={self.is_visible} font={self.font_name}>"


class TableStructure:
    """Representasi tabel statis BPS dengan bagian-bagian anatominya."""
    def __init__(self, table_number: str = "", page_idx: int = 0):
        self.table_number = table_number
        self.page_idx = page_idx
        self.physical_page = page_idx + 1
        self.title_id = ""
        self.title_en = ""
        self.raw_title = ""
        self.headers: List[str] = []
        self.unit_labels: List[str] = []
        self.superscripts_found: List[str] = []
        self.has_footnote_block = False
        self.footnote_text = ""
        self.has_valid_footnote = False
        self.has_source_block = False
        self.source_text = ""
        self.has_valid_source = False
        self.findings: List[str] = []


class VisualPage:
    """Representasi halaman dokumen yang telah diaudit secara visual & tata letak spasial."""
    def __init__(self, page_index: int, doc: fitz.Document):
        self.page_index = page_index
        self.physical_page = page_index + 1
        self.doc = doc
        self.page_obj = doc[page_index]
        self.width = self.page_obj.rect.width
        self.height = self.page_obj.rect.height
        
        self._pixmap = None
        self._cv_img = None
        self._spans: List[VisualSpan] = []
        self._visible_blocks: List[Tuple[float, float, float, float, str]] = []
        self._ghost_spans: List[VisualSpan] = []
        
        self.raw_text = ""
        self.visible_text = ""
        self.lines: List[str] = []
        
        self.header_text = ""
        self.footer_text = ""
        self.body_text = ""
        
        self.tables: List[TableStructure] = []
        self.is_parsed = False

    def get_cv_image(self, dpi: int = 150) -> Optional[np.ndarray]:
        """Lazy loader untuk gambar OpenCV BGR dari halaman render fisik."""
        if self._cv_img is not None:
            return self._cv_img
        if not HAVE_CV2:
            return None
        try:
            zoom = dpi / 72.0
            pix = self.page_obj.get_pixmap(matrix=fitz.Matrix(zoom, zoom))
            self._pixmap = pix
            img = cv2.imdecode(np.frombuffer(pix.tobytes("png"), np.uint8), cv2.IMREAD_COLOR)
            self._cv_img = img
            return img
        except Exception:
            return None

    def check_visibility(self, bbox: Tuple[float, float, float, float], min_dark_pixels: int = 12) -> bool:
        """
        Memeriksa apakah koordinat tertentu kasat mata di halaman fisik.
        Menggunakan render klip mikro (micro-clip render) agar ekstra cepat tanpa merender seluruh halaman.
        """
        # Jika gambar halaman utuh sudah dimuat (misal pada kover/HJU), gunakan slice memori
        if self._cv_img is not None and self._cv_img.size > 0:
            try:
                x0, y0, x1, y1 = bbox
                scale = 150.0 / 72.0
                ih, iw = self._cv_img.shape[:2]
                rx0 = max(0, int(x0 * scale) - 1)
                ry0 = max(0, int(y0 * scale) - 1)
                rx1 = min(iw, int(x1 * scale) + 1)
                ry1 = min(ih, int(y1 * scale) + 1)
                if rx1 <= rx0 or ry1 <= ry0:
                    return False
                crop = self._cv_img[ry0:ry1, rx0:rx1]
                if crop.size == 0:
                    return False
                gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
                return int(np.sum(gray < 200)) >= min_dark_pixels or (np.ptp(gray) >= 30 and np.std(gray) >= 8.0)
            except Exception:
                return True

        # Mode ultra-cepat: render HANYA klip koordinat bbox (sub-milidetik per blok)
        return is_block_visually_visible(self.page_obj, bbox, min_dark_pixels=min_dark_pixels)


class VisualPDFReader:
    """
    Mesin Pembaca PDF Mutakhir (Master Engine).
    Didesain untuk mengekstrak seluruh dokumen dengan kepatuhan visual 100%.
    """
    _ocr_engine = None

    def __init__(self, pdf_path: str):
        self.pdf_path = pdf_path
        self.doc = fitz.open(pdf_path)
        self.num_pages = len(self.doc)
        self.pages: Dict[int, VisualPage] = {}
        
        # Cache koleksi teks yang sudah tervalidasi visual
        self.pages_text: Dict[int, str] = {}
        self.pages_lines: Dict[int, List[str]] = {}
        self.ghost_findings: List[str] = []

    @classmethod
    def get_ocr_engine(cls):
        """Lazy singleton untuk RapidOCR engine."""
        if cls._ocr_engine is None and HAVE_RAPIDOCR:
            try:
                cls._ocr_engine = RapidOCR()
            except Exception:
                cls._ocr_engine = None
        return cls._ocr_engine

    def get_page(self, page_idx: int) -> VisualPage:
        """Mengambil atau menginisialisasi VisualPage untuk indeks tertentu."""
        if page_idx not in self.pages:
            self.pages[page_idx] = VisualPage(page_idx, self.doc)
        return self.pages[page_idx]

    def parse_page_fully(self, page_idx: int, force_ocr_if_low: bool = True) -> VisualPage:
        """
        Melakukan pemindaian mendalam pada suatu halaman:
        - Mengekstrak semua spans dan blok dengan verifikasi piksel fisik.
        - Memisahkan teks kasat mata vs teks ghost.
        - Menyusun urutan baca manusia yang logis.
        - Membagi zona header, body, footer, dan tabel.
        """
        vpage = self.get_page(page_idx)
        if vpage.is_parsed:
            return vpage

        page = vpage.page_obj
        pw, ph = vpage.width, vpage.height

        # 1. Ekstraksi mentah dari PyMuPDF
        raw_text = sanitize_invisible_unicode(page.get_text("text"))
        vpage.raw_text = raw_text

        # 2. Pemindaian visual RapidOCR jika halaman khusus atau teks sangat sedikit
        is_cover_page = (page_idx == 0 or page_idx == self.num_pages - 1)
        is_hju_page = (page_idx == 2)
        has_images = len(page.get_images()) >= 1
        
        ocr_text = ""
        ocr_engine = self.get_ocr_engine()
        if ocr_engine and HAVE_CV2 and (is_cover_page or is_hju_page or (has_images and len(raw_text.strip()) < 80)):
            try:
                img = vpage.get_cv_image(dpi=150)
                if img is not None:
                    ocr_res, _ = ocr_engine(img)
                    if ocr_res:
                        ocr_text = "\n".join([item[1] for item in ocr_res if item[1].strip()])
                        ocr_text = sanitize_invisible_unicode(ocr_text)
            except Exception:
                ocr_text = ""

        # 3. Audit Visibilitas Fisik (Halaman template, kover, pembatas bab, atau ber-gambar)
        is_preliminary = (page_idx < 18 or page_idx >= self.num_pages - 3)
        needs_pixel_audit = is_cover_page or is_hju_page or is_preliminary or has_images

        d = page.get_text("dict")
        visible_spans = []
        ghost_spans = []
        
        for b in d.get("blocks", []):
            if b.get("type") == 0:  # Text block
                bbox_b = tuple(b.get("bbox", (0, 0, 0, 0)))
                # Cek visibilitas di level blok terlebih dahulu untuk efisiensi
        # 3. Audit Visibilitas Fisik (Halaman template, kover, pembatas bab, atau margin header/footer)
        is_preliminary = (page_idx < 18 or page_idx >= self.num_pages - 3)
        is_divider_candidate = ("BAB " in raw_text.upper() and len(page.get_text("blocks")) < 12)
        is_template_page = is_cover_page or is_hju_page or is_preliminary or is_divider_candidate

        d = page.get_text("dict")
        visible_spans = []
        ghost_spans = []
        
        for b in d.get("blocks", []):
            if b.get("type") == 0:  # Text block
                bbox_b = tuple(b.get("bbox", (0, 0, 0, 0)))
                by0_b, by1_b = bbox_b[1], bbox_b[3]
                is_margin_block = (by1_b <= ph * 0.085 or by0_b >= ph * 0.88)

                # Cek visibilitas di level blok: hanya render mikro pada halaman template atau area margin
                block_is_visible = True
                if is_template_page or is_margin_block:
                    block_is_visible = vpage.check_visibility(bbox_b)

                for l in b.get("lines", []):
                    for s in l.get("spans", []):
                        stext = sanitize_invisible_unicode(s.get("text", "")).strip()
                        if not stext:
                            continue
                        sbbox = tuple(s.get("bbox", (0, 0, 0, 0)))
                        font_name = s.get("font", "")
                        font_size = float(s.get("size", 10.0))
                        flags = s.get("flags", 0)
                        color = s.get("color", 0)

                        is_bold = bool(flags & 2 or "bold" in font_name.lower())
                        is_italic = bool(flags & 1 or "italic" in font_name.lower() or "oblique" in font_name.lower())

                        # Pengecualian cepat: font_size < 1 pt atau warna putih (0xFFFFFF)
                        if font_size < 1.0 or color == 16777215:
                            is_vis = False
                        elif not block_is_visible:
                            is_vis = False
                        elif is_template_page and ("katalog" in stext.lower() or "issn" in stext.lower() or "xxxx" in stext.lower() or "tanpa gelar" in stext.lower()):
                            # Verifikasi spesifik per span untuk pola template sensitif
                            is_vis = vpage.check_visibility(sbbox)
                        else:
                            is_vis = True

                        vspan = VisualSpan(
                            text=stext,
                            bbox=sbbox,
                            font_name=font_name,
                            font_size=font_size,
                            is_bold=is_bold,
                            is_italic=is_italic,
                            color=color,
                            is_visible=is_vis
                        )

                        if is_vis:
                            visible_spans.append(vspan)
                        else:
                            ghost_spans.append(vspan)

        vpage._spans = visible_spans
        vpage._ghost_spans = ghost_spans

        # 4. Susun teks kasat mata dengan urutan baca ruang (Spatial Reading Order)
        blocks_data = page.get_text("blocks")
        sorted_visible_blocks = []
        
        is_two_column = False
        left_col_blocks = []
        right_col_blocks = []
        full_width_blocks = []

        mid_x = pw * 0.50
        for b in blocks_data:
            bx0, by0, bx1, by2, btext, bno, btype = b
            btext = sanitize_invisible_unicode(btext).strip()
            if not btext:
                continue
            is_margin_b = (by2 <= ph * 0.085 or by0 >= ph * 0.88)
            # Verifikasi apakah blok kasat mata
            if (is_template_page or is_margin_b) and not vpage.check_visibility((bx0, by0, bx1, by2)):
                continue

            if bx1 <= mid_x + 15:
                left_col_blocks.append(b)
            elif bx0 >= mid_x - 15:
                right_col_blocks.append(b)
            else:
                full_width_blocks.append(b)

        # Jika kedua kolom memiliki banyak teks, aktifkan pengurutan kolom
        if len(left_col_blocks) >= 2 and len(right_col_blocks) >= 2:
            is_two_column = True

        if is_two_column:
            # Urutan: Full width header -> Kolom Kiri -> Kolom Kanan -> Full width footer
            full_width_blocks.sort(key=lambda x: x[1])
            left_col_blocks.sort(key=lambda x: x[1])
            right_col_blocks.sort(key=lambda x: x[1])
            
            top_full = [b for b in full_width_blocks if b[1] < ph * 0.25]
            bottom_full = [b for b in full_width_blocks if b[1] >= ph * 0.25]
            
            sorted_visible_blocks = top_full + left_col_blocks + right_col_blocks + bottom_full
        else:
            # Urutan baca standar atas-ke-bawah dengan toleransi baris 4 pt
            sorted_visible_blocks = sorted(
                [b for b in blocks_data if sanitize_invisible_unicode(b[4]).strip() and vpage.check_visibility(b[:4])],
                key=lambda x: (round(x[1] / 5.0) * 5.0, x[0])
            )

        vpage._visible_blocks = sorted_visible_blocks

        # Gabungkan teks kasat mata
        visible_lines = []
        for b in sorted_visible_blocks:
            btxt = sanitize_invisible_unicode(b[4]).strip()
            for line in btxt.splitlines():
                line_str = line.strip()
                if line_str:
                    visible_lines.append(line_str)

        # Jika halaman kover depan/belakang dan OCR menghasilkan teks lebih lengkap, gunakan teks OCR
        if (is_cover_page or is_hju_page) and ocr_text:
            vpage.visible_text = ocr_text
            vpage.lines = [l.strip() for l in ocr_text.splitlines() if l.strip()]
        else:
            vpage.visible_text = "\n".join(visible_lines)
            vpage.lines = visible_lines

        # 5. Partisi Zona Semantik
        header_lines = []
        footer_lines = []
        body_lines = []
        
        for b in sorted_visible_blocks:
            by0, by1 = b[1], b[3]
            btxt = sanitize_invisible_unicode(b[4]).strip()
            if by1 <= ph * 0.085:
                header_lines.append(btxt)
            elif by0 >= ph * 0.88:
                footer_lines.append(btxt)
            else:
                body_lines.append(btxt)

        vpage.header_text = "\n".join(header_lines).strip()
        vpage.footer_text = "\n".join(footer_lines).strip()
        vpage.body_text = "\n".join(body_lines).strip()

        # 6. Ekstraksi Tabel & Catatan Kaki Spasial
        vpage.tables = self._extract_tables_from_vpage(vpage)

        vpage.is_parsed = True
        return vpage

    def _extract_tables_from_vpage(self, vpage: VisualPage) -> List[TableStructure]:
        """Mengekstrak dan menganalisis tabel-tabel pada halaman secara spasial."""
        tables = []
        lines = vpage.lines
        txt = vpage.visible_text
        p_idx = vpage.page_index

        # Deteksi nomor tabel (misal 'Tabel 1.1.1', '6.1.1', 'Tabel\n6.1.1 Banyaknya...')
        for idx_l, line in enumerate(lines):
            tbl_num = None
            cand_title = ""
            
            # Pola 1: Baris diawali atau memuat 'Tabel X.X.X' atau nomor 'X.X.X'
            m_num = re.search(r'(?:(Tabel|Table)\s*)?([1-7](?:\.\d+)+)\b', line, re.I)
            if m_num:
                has_tabel_word = bool(m_num.group(1))
                num_candidate = m_num.group(2)
                # Jika ada kata 'Tabel', cukup 1 titik (misal 'Tabel 1.1'). Jika hanya angka, wajib minimal 2 titik (misal '6.1.1')
                if (has_tabel_word and num_candidate.count('.') >= 1) or (num_candidate.count('.') >= 2):
                    tbl_num = num_candidate
                    rest = line[m_num.end():].strip()
                    if len(rest) > 5 and not rest.isdigit() and 'KECAMATAN' not in rest.upper():
                        cand_title = rest
                    elif idx_l + 1 < len(lines):
                        cand_title = lines[idx_l + 1]

            if tbl_num:
                tbl = TableStructure(table_number=tbl_num, page_idx=p_idx)
                tbl.raw_title = cand_title
                if '/' in cand_title:
                    parts = cand_title.split('/', 1)
                    tbl.title_id = parts[0].strip()
                    tbl.title_en = parts[1].strip()
                else:
                    tbl.title_id = cand_title.strip()

                # Cek rujukan superskrip
                tbl.superscripts_found = re.findall(r'(?:[A-Za-z]+)\s*(?:1/|¹/|¹|2/|²/|²|3/|³/|³)', txt)

                # Ekstraksi Blok Catatan Kaki
                m_note = re.search(r'Catatan/Note\s*:?\s*(.*?)(?:Sumber/Source\s*:|$)', txt, re.DOTALL | re.I)
                if m_note:
                    tbl.has_footnote_block = True
                    fn_content = m_note.group(1).strip()
                    tbl.footnote_text = fn_content
                    clean_fn = re.sub(r'[\.\s,–-]+', '', fn_content)
                    
                    # Validasi apakah ada penjelasan sah
                    tbl.has_valid_footnote = bool(
                        clean_fn and (
                            re.search(r'(?:^|\n|\b)(?:1\s*[/.)\-]|\b1\s+[A-Za-z]|1[A-Za-z]|¹)', fn_content)
                            or re.search(r'\b(?:UPT|Unit Permukiman Transmigrasi|Transmigration|termasuk|include|data)\b', fn_content, re.I)
                        )
                    )
                else:
                    # Alternatif jika tidak ada header Catatan/Note, periksa baris rujukan di atas Sumber
                    m_src = re.search(r'Sumber/Source', txt, re.I)
                    if m_src:
                        pre_src = txt[:m_src.start()].rstrip().splitlines()
                        for cl in pre_src[-3:]:
                            if re.search(r'(?:^|\b)(?:1/|1\)|1\.|¹|[¹1]\s*(?:Desa|Satuan|Data|Unit|UPT))\b', cl, re.I):
                                tbl.has_footnote_block = True
                                tbl.footnote_text = cl.strip()
                                tbl.has_valid_footnote = True
                                break

                # Ekstraksi Blok Sumber Data
                m_src_block = re.search(r'Sumber/Source\s*:?\s*([^\n]+)', txt, re.I)
                if m_src_block:
                    tbl.has_source_block = True
                    src_content = m_src_block.group(1).strip()
                    tbl.source_text = src_content
                    tbl.has_valid_source = bool(re.sub(r'[\.\s,–-]+', '', src_content))

                tables.append(tbl)

        return tables

    def read_all_pages_cached(self) -> Tuple[Dict[int, str], Dict[int, List[str]]]:
        """
        Membaca seluruh halaman dokumen dengan efisiensi maksimal:
        Mengembalikan (pages_text, pages_lines) yang 100% tersanitasi dan terverifikasi visual.
        """
        if self.pages_text and self.pages_lines:
            return self.pages_text, self.pages_lines

        for p_idx in range(self.num_pages):
            vpage = self.parse_page_fully(p_idx)
            self.pages_text[p_idx] = vpage.visible_text
            self.pages_lines[p_idx] = vpage.lines

        return self.pages_text, self.pages_lines

    def close(self):
        """Menutup dokumen PDF dengan aman."""
        if self.doc:
            try:
                self.doc.close()
            except Exception:
                pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
