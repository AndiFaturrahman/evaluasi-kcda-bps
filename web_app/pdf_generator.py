import os
import sys
import datetime
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak, KeepTogether, HRFlowable
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas

class NumberedCanvas(canvas.Canvas):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved_page_states = []

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        num_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self.draw_page_decorations(num_pages)
            super().showPage()
        super().save()

    def draw_page_decorations(self, page_count):
        self.saveState()
        self.setFont('Helvetica', 8)
        self.setFillColor(colors.HexColor('#64748B'))
        
        # Header (Halaman 2 ke atas)
        if self._pageNumber > 1:
            self.drawString(18 * mm, 283 * mm, 'LEMBAR EVALUASI PUBLIKASI BPS 2026')
            self.drawRightString(192 * mm, 283 * mm, 'Standar Baku KcDA / KDA BPS')
            self.setStrokeColor(colors.HexColor('#CBD5E1'))
            self.setLineWidth(0.5)
            self.line(18 * mm, 280 * mm, 192 * mm, 280 * mm)
            
        # Footer (Semua halaman)
        self.setStrokeColor(colors.HexColor('#CBD5E1'))
        self.setLineWidth(0.5)
        self.line(18 * mm, 14 * mm, 192 * mm, 14 * mm)
        self.drawString(18 * mm, 10 * mm, 'Badan Pusat Statistik • Sistem Penjaminan Kualitas Publikasi (Data Mencerdaskan Bangsa)')
        self.drawRightString(192 * mm, 10 * mm, f'Halaman {self._pageNumber} dari {page_count}')
        self.restoreState()


def generate_pdf_report(meta, defects, output_pdf_path):
    """
    Menghasilkan dokumen resmi Laporan Hasil Evaluasi Publikasi BPS dalam format PDF
    dengan standar visual eksekutif, tabel 11 anatomi BPS, dan penomoran resmi.
    """
    total_defects = sum(len(items) for items in defects.values())
    region_name = meta.get('region', 'Wilayah')
    year = meta.get('year', '2026')
    pub_title = meta.get('title', f'Kecamatan {region_name} Dalam Angka {year}')
    
    out_dir = os.path.dirname(output_pdf_path)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)

    doc = SimpleDocTemplate(
        output_pdf_path,
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=18 * mm,
        bottomMargin=18 * mm
    )
    
    styles = getSampleStyleSheet()
    
    title_style = ParagraphStyle(
        'DocTitle',
        parent=styles['Heading1'],
        fontName='Helvetica-Bold',
        fontSize=13.5,
        leading=17,
        textColor=colors.HexColor('#0F172A'),
        spaceAfter=2
    )
    
    sub_style = ParagraphStyle(
        'DocSub',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=8,
        leading=11.5,
        textColor=colors.HexColor('#475569'),
        spaceAfter=8
    )
    
    meta_label = ParagraphStyle(
        'MetaLabel',
        fontName='Helvetica-Bold',
        fontSize=8,
        leading=11,
        textColor=colors.HexColor('#334155')
    )
    
    meta_val = ParagraphStyle(
        'MetaVal',
        fontName='Helvetica',
        fontSize=8,
        leading=11,
        textColor=colors.HexColor('#0F172A')
    )
    
    story = []
    
    # ── 1. KOP SURAT / HEADER RESMI ──
    story.append(Paragraph('BADAN PUSAT STATISTIK', ParagraphStyle('Agency', fontName='Helvetica-Bold', fontSize=9, textColor=colors.HexColor('#004080'), spaceAfter=2)))
    story.append(Paragraph('LEMBAR HASIL EVALUASI KEPATUHAN FORMAT PUBLIKASI', title_style))
    story.append(Paragraph('Berdasarkan Pedoman Pembuatan Publikasi BPS 2023, Master Template KcDA 2026, dan Instrumen Pemeriksaan Publikasi', sub_style))
    story.append(HRFlowable(width='100%', thickness=1.5, color=colors.HexColor('#004080'), spaceAfter=6))
    
    # ── 2. METADATA & STATUS KELAYAKAN ──
    d_mismatch = meta.get("district_mismatch_info", {})
    is_mismatch = d_mismatch.get("is_mismatch", False)

    raw_tpl = meta.get("raw_template_info", {})
    is_clean_all = (total_defects == 0)

    if raw_tpl.get("is_pure_template"):
        status_text = f'<b>DITOLAK TOTAL</b><br/><font size=\"7.5\" color=\"#B91C1C\"><b>TEMPLATE MENTAH</b></font><br/><font size=\"6.5\">Belum Dikerjakan</font>'
        status_bg = colors.HexColor('#FEF2F2')
        status_tc = colors.HexColor('#DC2626')
        status_bc = colors.HexColor('#F87171')
    elif raw_tpl.get("is_raw_template"):
        status_text = f'<b>REVISI TOTAL</b><br/><font size=\"7.5\" color=\"#B91C1C\"><b>RESIDU TEMPLATE</b></font><br/><font size=\"6.5\">Draf Belum Tuntas</font>'
        status_bg = colors.HexColor('#FEF2F2')
        status_tc = colors.HexColor('#DC2626')
        status_bc = colors.HexColor('#F87171')
    elif is_mismatch:
        status_text = f'<b>REVISI TOTAL</b><br/><font size=\"7.5\" color=\"#B91C1C\"><b>FATAL: SALAH WILAYAH</b></font><br/><font size=\"6.5\">Hanya Ganti Kover</font>'
        status_bg = colors.HexColor('#FEF2F2')
        status_tc = colors.HexColor('#DC2626')
        status_bc = colors.HexColor('#F87171')
    elif is_clean_all:
        status_text = '<b>SESUAI STANDAR</b><br/>(SIAP RILIS)<br/><font size=\"7\">Bebas Kesalahan</font>'
        status_bg = colors.HexColor('#F0FDF4')
        status_tc = colors.HexColor('#15803D')
        status_bc = colors.HexColor('#86EFAC')
    else:
        status_text = f'<b>PERLU REVISI</b><br/><font size=\"7.5\">{total_defects} Catatan Temuan</font>'
        status_bg = colors.HexColor('#FFF7ED')
        status_tc = colors.HexColor('#C2410C')
        status_bc = colors.HexColor('#FDBA74')
    
    status_p = Paragraph(status_text, ParagraphStyle('StatusP', fontName='Helvetica-Bold', fontSize=9, leading=13, textColor=status_tc, alignment=1))
    
    today_str = datetime.date.today().strftime('%d %B %Y')
    
    issn_val_str = str(meta.get('issn', '-'))
    if meta.get('issn_cross_page_inconsistent'):
        issn_val_str += ' <font color="#DC2626"><b>[INKONSISTEN]</b></font>'
    elif meta.get('issn_registry_mismatch'):
        issn_val_str += ' <font color="#D97706"><b>[TYPO REGISTRI]</b></font>'

    wilayah_str = f"Kecamatan {region_name}"
    if is_mismatch:
        inner_d_name = d_mismatch.get("dominant_inner_district") or d_mismatch.get("catalog_district") or "Lain"
        wilayah_str += f' <font color="#DC2626"><b>[ISI: KEC. {inner_d_name.upper()}]</b></font>'

    meta_data = [
        [
            Paragraph('<b>Judul Publikasi:</b>', meta_label),
            Paragraph(pub_title, meta_val),
            '',
            '',
            status_p
        ],
        [
            Paragraph('<b>Wilayah/Satker:</b>', meta_label),
            Paragraph(wilayah_str, meta_val),
            Paragraph('<b>Nomor Katalog:</b>', meta_label),
            Paragraph(meta.get('catalog', '-'), meta_val),
            ''
        ],
        [
            Paragraph('<b>Tahun Terbit:</b>', meta_label),
            Paragraph(str(year), meta_val),
            Paragraph('<b>Nomor ISSN:</b>', meta_label),
            Paragraph(issn_val_str, meta_val),
            ''
        ],
        [
            Paragraph('<b>Tgl Evaluasi:</b>', meta_label),
            Paragraph(today_str, meta_val),
            Paragraph('<b>Halaman Fisik:</b>', meta_label),
            Paragraph(f"{meta.get('total_pages', '-')} Halaman", meta_val),
            ''
        ]
    ]
    
    col_widths = [25*mm, 47*mm, 27*mm, 30*mm, 45*mm]
    # Total = 25 + 47 + 27 + 30 + 45 = 174 mm
    meta_table = Table(meta_data, colWidths=col_widths)
    meta_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), colors.HexColor('#F8FAFC')),
        ('BOX', (0,0), (-1,-1), 0.5, colors.HexColor('#CBD5E1')),
        ('INNERGRID', (0,0), (3,-1), 0.5, colors.HexColor('#E2E8F0')),
        ('TOPPADDING', (0,0), (-1,-1), 3),
        ('BOTTOMPADDING', (0,0), (-1,-1), 3),
        ('LEFTPADDING', (0,0), (-1,-1), 4),
        ('RIGHTPADDING', (0,0), (-1,-1), 4),
        ('SPAN', (1,0), (3,0)), # Span Judul Publikasi di kolom 1 s.d. 3
        ('SPAN', (4,0), (4,3)), # Span Status Kelayakan di kolom 4 dari baris 0 s.d. 3
        ('BACKGROUND', (4,0), (4,3), status_bg),
        ('BOX', (4,0), (4,3), 1, status_bc),
        ('VALIGN', (4,0), (4,3), 'MIDDLE'),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
    ]))
    
    story.append(meta_table)
    story.append(Spacer(1, 6))

    # ── FATAL MISMATCH WARNING BANNER (INKONSISTENSI WILAYAH KOVER VS ISI) ──
    if is_mismatch:
        cov_d = d_mismatch.get("cover_district", region_name)
        inner_d = d_mismatch.get("dominant_inner_district") or d_mismatch.get("catalog_district") or "Wilayah Lain"
        reasons_bullet = "<br/>• ".join(d_mismatch.get("reasons", []))
        warning_p = Paragraph(
            f'<b>PERINGATAN FATAL: INDIKASI KETIDAKSESUAIAN IDENTITAS WILAYAH (KOVER VS ISI)</b><br/>'
            f'Buku ini menggunakan kover <b>"{cov_d}"</b>, namun batang tubuh dan ulasan data di dalamnya terdeteksi merupakan publikasi <b>"{inner_d}"</b>.<br/>'
            f'<b>Bukti Ketidaksesuaian Terdeteksi:</b><br/>• {reasons_bullet}<br/>'
            f'<b>Rekomendasi Wajib:</b> Publikasi TIDAK LAYAK TERBIT. Ganti seluruh naskah bab 1 s.d. 7, ulasan, dan data tabel dengan data asli wilayah {cov_d}.',
            ParagraphStyle('FatalWarnP', fontName='Helvetica', fontSize=7.8, leading=11, textColor=colors.HexColor('#991B1B'))
        )
        warn_tbl = Table([[warning_p]], colWidths=[174*mm])
        warn_tbl.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,-1), colors.HexColor('#FEF2F2')),
            ('BOX', (0,0), (-1,-1), 1.2, colors.HexColor('#DC2626')),
            ('TOPPADDING', (0,0), (-1,-1), 5),
            ('BOTTOMPADDING', (0,0), (-1,-1), 5),
            ('LEFTPADDING', (0,0), (-1,-1), 8),
            ('RIGHTPADDING', (0,0), (-1,-1), 8),
        ]))
        story.append(warn_tbl)
        story.append(Spacer(1, 6))
    
    # ── 3. RINCIAN EVALUASI PER SEKSI (11 ANATOMI RESMI) ──
    sec_title_style = ParagraphStyle(
        'SecTitle',
        fontName='Helvetica-Bold',
        fontSize=9,
        leading=12,
        textColor=colors.HexColor('#FFFFFF')
    )
    sec_badge_style = ParagraphStyle(
        'SecBadge',
        fontName='Helvetica-Bold',
        fontSize=8,
        leading=11,
        textColor=colors.HexColor('#FFFFFF'),
        alignment=2
    )
    
    defect_num_style = ParagraphStyle(
        'DefectNum',
        fontName='Helvetica-Bold',
        fontSize=8.5,
        leading=12,
        textColor=colors.HexColor('#004080'),
        alignment=1
    )
    defect_text_style = ParagraphStyle(
        'DefectText',
        fontName='Helvetica',
        fontSize=8.5,
        leading=12,
        textColor=colors.HexColor('#1E293B')
    )
    
    clean_text_style = ParagraphStyle(
        'CleanText',
        fontName='Helvetica-Oblique',
        fontSize=8.5,
        leading=12,
        textColor=colors.HexColor('#166534')
    )
    
    sec_num = 1
    for sec_name, items in defects.items():
        clean_sec_name = sec_name.replace(':', '').replace('-', '').trim() if hasattr(sec_name, 'trim') else sec_name.replace(':', '').replace('-', '').strip()
        is_clean = len(items) == 0
        badge_txt = '✓ Bebas Kesalahan' if is_clean else f'{len(items)} Catatan Temuan'
        header_bg = colors.HexColor('#0F172A') if is_clean else colors.HexColor('#004080')
        
        # Section Header Table
        sec_header = Table([
            [Paragraph(f'<b>{sec_num}. {clean_sec_name}</b>', sec_title_style), Paragraph(badge_txt, sec_badge_style)]
        ], colWidths=[130*mm, 44*mm])
        sec_header.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,-1), header_bg),
            ('TOPPADDING', (0,0), (-1,-1), 3.5),
            ('BOTTOMPADDING', (0,0), (-1,-1), 3.5),
            ('LEFTPADDING', (0,0), (-1,-1), 6),
            ('RIGHTPADDING', (0,0), (-1,-1), 6),
        ]))
        
        flowables = [sec_header]
        
        if is_clean:
            clean_tbl = Table([
                [Paragraph('✓ Bagian ini telah memenuhi standar baku BPS (tanpa temuan kesalahan). Sesuai aturan evaluasi resmi, kolom catatan evaluasi dikosongkan.', clean_text_style)]
            ], colWidths=[174*mm])
            clean_tbl.setStyle(TableStyle([
                ('BACKGROUND', (0,0), (-1,-1), colors.HexColor('#F0FDF4')),
                ('BOX', (0,0), (-1,-1), 0.5, colors.HexColor('#86EFAC')),
                ('TOPPADDING', (0,0), (-1,-1), 4),
                ('BOTTOMPADDING', (0,0), (-1,-1), 4),
                ('LEFTPADDING', (0,0), (-1,-1), 8),
                ('RIGHTPADDING', (0,0), (-1,-1), 8),
            ]))
            flowables.append(clean_tbl)
        else:
            rows = []
            row_styles = []
            for idx_d, defect in enumerate(items, start=1):
                is_fatal = "[FATAL" in defect
                is_aesthetic = "[SARAN ESTETIKA" in defect
                if is_fatal:
                    d_color = colors.HexColor('#991B1B')
                    n_color = colors.HexColor('#DC2626')
                elif is_aesthetic:
                    d_color = colors.HexColor('#0F766E')
                    n_color = colors.HexColor('#0D9488')
                else:
                    d_color = colors.HexColor('#1E293B')
                    n_color = colors.HexColor('#004080')

                d_style = ParagraphStyle(f'DefectText_{sec_num}_{idx_d}', parent=defect_text_style, textColor=d_color)
                num_style = ParagraphStyle(f'DefectNum_{sec_num}_{idx_d}', parent=defect_num_style, textColor=n_color)
                rows.append([
                    Paragraph(f'<b>[{idx_d}]</b>', num_style),
                    Paragraph(defect, d_style)
                ])
                if is_fatal:
                    row_styles.append(('BACKGROUND', (0, idx_d-1), (-1, idx_d-1), colors.HexColor('#FEF2F2')))
                    row_styles.append(('LINEBELOW', (0, idx_d-1), (-1, idx_d-1), 0.6, colors.HexColor('#FCA5A5')))
                elif is_aesthetic:
                    row_styles.append(('BACKGROUND', (0, idx_d-1), (-1, idx_d-1), colors.HexColor('#F0FDFA')))
                    row_styles.append(('LINEBELOW', (0, idx_d-1), (-1, idx_d-1), 0.5, colors.HexColor('#99F6E4')))

            defect_table = Table(rows, colWidths=[12*mm, 162*mm])
            base_styles = [
                ('BACKGROUND', (0,0), (-1,-1), colors.HexColor('#FFFFFF')),
                ('BOX', (0,0), (-1,-1), 0.5, colors.HexColor('#CBD5E1')),
                ('INNERGRID', (0,0), (-1,-1), 0.5, colors.HexColor('#F1F5F9')),
                ('TOPPADDING', (0,0), (-1,-1), 3.5),
                ('BOTTOMPADDING', (0,0), (-1,-1), 3.5),
                ('LEFTPADDING', (0,0), (-1,-1), 4),
                ('RIGHTPADDING', (0,0), (-1,-1), 4),
                ('VALIGN', (0,0), (-1,-1), 'TOP')
            ]
            defect_table.setStyle(TableStyle(base_styles + row_styles))
            flowables.append(defect_table)
            
        flowables.append(Spacer(1, 6))
        story.extend(flowables)
        sec_num += 1
        
    # ── 4. LEMBAR TANDA TANGAN / PENGESAHAN EVALUASI ──
    sig_data = [
        [
            Paragraph('<b>Catatan Tindak Lanjut Satker / Penulis Naskah:</b><br/><br/>....................................................................................................<br/>....................................................................................................', meta_val),
            Paragraph(f'Salakan, {today_str}<br/><b>Tim Evaluator & Penjamin Kualitas BPS</b><br/><br/><br/><br/>( ............................................................ )<br/>NIP. ....................................................', ParagraphStyle('SigRight', parent=meta_val, alignment=1))
        ]
    ]
    sig_table = Table(sig_data, colWidths=[100*mm, 74*mm])
    sig_table.setStyle(TableStyle([
        ('BOX', (0,0), (-1,-1), 0.5, colors.HexColor('#94A3B8')),
        ('BACKGROUND', (0,0), (-1,-1), colors.HexColor('#F8FAFC')),
        ('TOPPADDING', (0,0), (-1,-1), 6),
        ('BOTTOMPADDING', (0,0), (-1,-1), 6),
        ('LEFTPADDING', (0,0), (-1,-1), 6),
        ('RIGHTPADDING', (0,0), (-1,-1), 6),
        ('VALIGN', (0,0), (-1,-1), 'TOP')
    ]))
    story.append(Spacer(1, 4))
    story.append(KeepTogether([sig_table]))
    
    doc.build(story, canvasmaker=NumberedCanvas)
    return output_pdf_path
