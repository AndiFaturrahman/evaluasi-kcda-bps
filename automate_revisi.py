import sys, os, copy, shutil, base64, json, requests
import openpyxl
from openpyxl.styles import Font, Alignment, Border, Side
from web_app.evaluator import extract_pdf_metadata, analyze_defects

# Configure stdout for UTF-8
sys.stdout.reconfigure(encoding='utf-8')

excel_path = '7201_Evaluasi publikasi KcDA September 2025.xlsx'
backup_path = '7201_Evaluasi publikasi KcDA September 2025_backup.xlsx'
cache_file = 'gemini_variations_cache.json'
api_key = os.environ.get('GEMINI_API_KEY', '')

# Load cache if exists
variation_cache = {}
if os.path.exists(cache_file):
    try:
        with open(cache_file, 'r', encoding='utf-8') as f:
            variation_cache = json.load(f)
        print(f"Loaded existing AI variations cache with {len(variation_cache)} districts.")
    except Exception as e:
        print(f"Warning: Failed to load cache: {e}")

# Read cleanly from backup_path if exists, otherwise from excel_path
source_path = backup_path if os.path.exists(backup_path) else excel_path
print(f"Loading source workbook from: '{source_path}'")
wb = openpyxl.load_workbook(source_path)
print("Starting Strict Defect-Only BPS Review Automation (With Placeholder Image Inspection)...")
print("Original sheets count:", len(wb.sheetnames))

# Define subdistrict metadata for all 12 subdistricts
districts_data = [
    {
        'key': 'Buko',
        'sheet_2025': 'Buko 2025',
        'sheet_2026': 'Buko 2026',
        'name': 'Buko',
        'title': 'Kecamatan Buko Dalam Angka',
        'catalog': '1102001.7201070',
        'issn_pdf': '2065-108X',
        'issn_correct': '2655-108X',
        'pages_roman_pdf': 'xxii',
        'pages_arab_pdf': '82',
        'is_issn_typo': True,
        'is_roman_typo': False,
    },
    {
        'key': 'Buko Selatan',
        'sheet_2025': 'Buko Selatan 2025',
        'sheet_2026': 'Buko Selatan 2026',
        'name': 'Buko Selatan',
        'title': 'Kecamatan Buko Selatan Dalam Angka',
        'catalog': '1102001.7201071',
        'issn_pdf': '2655-1098',
        'issn_correct': '2655-1098',
        'pages_roman_pdf': 'xxii',
        'pages_arab_pdf': '82',
        'is_issn_typo': False,
        'is_roman_typo': False,
    },
    {
        'key': 'Bulagi',
        'sheet_2025': 'Bulagi 2025',
        'sheet_2026': 'Bulagi 2026',
        'name': 'Bulagi',
        'title': 'Kecamatan Bulagi Dalam Angka',
        'catalog': '1102001.7201060',
        'issn_pdf': '2655-1055',
        'issn_correct': '2655-1055',
        'pages_roman_pdf': 'xxii',
        'pages_arab_pdf': '82',
        'is_issn_typo': False,
        'is_roman_typo': False,
    },
    {
        'key': 'Bulagi Selatan',
        'sheet_2025': 'Bulagi Selatan 2025',
        'sheet_2026': 'Bulagi Selatan 2026',
        'name': 'Bulagi Selatan',
        'title': 'Kecamatan Bulagi Selatan Dalam Angka',
        'catalog': '1102001.7201061',
        'issn_pdf': '2655-1063',
        'issn_correct': '2655-1063',
        'pages_roman_pdf': 'xxii',
        'pages_arab_pdf': '82',
        'is_issn_typo': False,
        'is_roman_typo': False,
    },
    {
        'key': 'Bulagi Utara',
        'sheet_2025': 'Bulagi Utara 2025',
        'sheet_2026': 'Bulagi Utara 2026',
        'name': 'Bulagi Utara',
        'title': 'Kecamatan Bulagi Utara Dalam Angka',
        'catalog': '1102001.7201062',
        'issn_pdf': '2655-1071',
        'issn_correct': '2655-1071',
        'pages_roman_pdf': 'xii',
        'pages_arab_pdf': '82',
        'is_issn_typo': False,
        'is_roman_typo': True,
    },
    {
        'key': 'Tinangkung',
        'sheet_2025': 'Tinangkung 2025',
        'sheet_2026': 'Tinangkung 2026',
        'name': 'Tinangkung',
        'title': 'Kecamatan Tinangkung Dalam Angka',
        'catalog': '1102001.7201040',
        'issn_pdf': '2620-6501',
        'issn_correct': '2620-6501',
        'pages_roman_pdf': 'xii',
        'pages_arab_pdf': '82',
        'is_issn_typo': False,
        'is_roman_typo': True,
    },
    {
        'key': 'Tinangkung Selatan',
        'sheet_2025': 'Tinangkung Selatan 2025',
        'sheet_2026': 'Tinangkung Selatan 2026',
        'name': 'Tinangkung Selatan',
        'title': 'Kecamatan Tinangkung Selatan Dalam Angka',
        'catalog': '1102001.7201041',
        'issn_pdf': '2655-1020',
        'issn_correct': '2655-1020',
        'pages_roman_pdf': 'xxii',
        'pages_arab_pdf': '82',
        'is_issn_typo': False,
        'is_roman_typo': False,
    },
    {
        'key': 'Tinangkung Utara',
        'sheet_2025': 'Tinangkung Utara 2025',
        'sheet_2026': 'Tinangkung Utara 2026',
        'name': 'Tinangkung Utara',
        'title': 'Kecamatan Tinangkung Utara Dalam Angka',
        'catalog': '1102001.7201042',
        'issn_pdf': '2655-125X',
        'issn_correct': '2655-125X',
        'pages_roman_pdf': 'xii',
        'pages_arab_pdf': '82',
        'is_issn_typo': False,
        'is_roman_typo': True,
    },
    {
        'key': 'Totikum',
        'sheet_2025': 'Totikum 2025',
        'sheet_2026': 'Totikum 2026',
        'name': 'Totikum',
        'title': 'Kecamatan Totikum Dalam Angka',
        'catalog': '1102001.7201030',
        'issn_pdf': '2620-6498',
        'issn_correct': '2620-6498',
        'pages_roman_pdf': 'xxii',
        'pages_arab_pdf': '82',
        'is_issn_typo': False,
        'is_roman_typo': False,
    },
    {
        'key': 'Totikum Selatan',
        'sheet_2025': 'Totikum Selatan 2025',
        'sheet_2026': 'Totikum Selatan 2026',
        'name': 'Totikum Selatan',
        'title': 'Kecamatan Totikum Selatan Dalam Angka',
        'catalog': '1102001.7201031',
        'issn_pdf': '2655-1020',
        'issn_correct': '2655-1012',
        'pages_roman_pdf': 'xxii',
        'pages_arab_pdf': '82',
        'is_issn_typo': True,
        'is_roman_typo': False,
    },
    {
        'key': 'Peling',
        'sheet_2025': 'Peling 2025',
        'sheet_2026': 'Peling 2026',
        'name': 'Peling Tengah',
        'title': 'Kecamatan Peling Tengah Dalam Angka',
        'catalog': '1102001.7201051',
        'issn_pdf': '2655-1047',
        'issn_correct': '2655-1047',
        'pages_roman_pdf': 'xxii',
        'pages_arab_pdf': '82',
        'is_issn_typo': False,
        'is_roman_typo': False,
    },
    {
        'key': 'Liang',
        'sheet_2025': 'Liang 2025',
        'sheet_2026': 'Liang 2026',
        'name': 'Liang',
        'title': 'Kecamatan Liang Dalam Angka',
        'catalog': '1102001.7201050',
        'issn_pdf': '2655-1039',
        'issn_correct': '2655-1039',
        'pages_roman_pdf': 'xxii',
        'pages_arab_pdf': '82',
        'is_issn_typo': False,
        'is_roman_typo': False,
    }
]

# Step 1: Rename old sheets to xxx 2025
renames = {
    'Buko Selatan': 'Buko Selatan 2025',
    'Bulagi': 'Bulagi 2025',
    'Bulagi Utara': 'Bulagi Utara 2025',
    'Tinangkung Selatan': 'Tinangkung Selatan 2025',
    'Tinangkung ': 'Tinangkung 2025',
    'Tinangkung': 'Tinangkung 2025',
    'Tinangkung Utara': 'Tinangkung Utara 2025',
    'Totikum': 'Totikum 2025',
    'Totikum Selatan': 'Totikum Selatan 2025',
    'Peling': 'Peling 2025',
    'Liang': 'Liang 2025'
}

for old_name, new_name in renames.items():
    if old_name in wb.sheetnames:
        wb[old_name].title = new_name
        print(f"Renamed sheet '{old_name}' -> '{new_name}'")

# Step 2: Ensure all 2026 sheets exist by duplicating 2025 sheets if missing
for d in districts_data:
    s2025_name = d['sheet_2025']
    s2026_name = d['sheet_2026']
    
    if s2026_name not in wb.sheetnames:
        if s2025_name in wb.sheetnames:
            cp = wb.copy_worksheet(wb[s2025_name])
            cp.title = s2026_name
            print(f"Created duplicate sheet '{s2026_name}' from '{s2025_name}'")
        else:
            print(f"Error: Base sheet '{s2025_name}' not found!")

# Styling definitions
font_meta = Font(name='Calibri', size=9, bold=False)
font_sec = Font(name='Calibri', size=9, bold=True)
font_dash = Font(name='Calibri', size=9, bold=False)
font_item = Font(name='Calibri', size=9, bold=False)

align_center = Alignment(horizontal='center', vertical='center')
align_left = Alignment(horizontal='left', vertical='top')
align_wrap = Alignment(horizontal='left', vertical='top', wrap_text=True)

thin_side = Side(style='thin')
double_side = Side(style='double')

def get_evaluator_sections_for_district(d):
    name_clean = d['name'].lower().replace(' ', '-')
    cand_files = [
        f"kecamatan-{name_clean}-dalam-angka-2026.pdf",
        f"kecamatan-{d['key'].lower().replace(' ', '-')}-dalam-angka-2026.pdf"
    ]
    pdf_path = None
    for cf in cand_files:
        p = os.path.join('PUBLIKASI BANGKEP', cf)
        if os.path.exists(p):
            pdf_path = p
            break
            
    if not pdf_path:
        print(f"Warning: PDF not found for {d['name']}")
        return []

    print(f"  [Evaluator] Extracting real defects from {os.path.basename(pdf_path)}...")
    meta = extract_pdf_metadata(pdf_path)
    raw = analyze_defects(meta)

    # 11 official sections mapped directly from the factual evaluator
    sections = [
        ('Kover depan: -', raw.get('Kover depan: -', raw.get('Kover Depan:', []))),
        ('Halaman Judul Utama: -', raw.get('Halaman Judul Utama: -', raw.get('Halaman Judul Utama:', []))),
        ('Halaman katalog: -', raw.get('Halaman katalog: -', raw.get('Halaman Katalog:', []))),
        ('Halaman Tim Penyusun: -', raw.get('Halaman Tim Penyusun: -', raw.get('Tim Penyusun:', []))),
        ('Kata pengantar: -', raw.get('Kata pengantar: -', raw.get('Kata Pengantar:', []))),
        ('Daftar Isi: -', raw.get('Daftar Isi: -', raw.get('Daftar Isi:', []))),
        ('Penjelasan Umum:', raw.get('Penjelasan Umum:', raw.get('Penjelasan Teknis:', []))),
        ('Daftar Tabel/Gambar/Grafik/Lampiran:', raw.get('Daftar Tabel/Gambar/Grafik/Lampiran:', raw.get('Daftar Tabel:', []) + raw.get('Daftar Gambar:', []))),
        ('Layout Isi:', raw.get('Layout Isi:', raw.get('Pembatas Bab:', []) + raw.get('Narasi:', []) + raw.get('Running Title:', []) + raw.get('Tabel:', []) + raw.get('Gambar:', []))),
        ('Daftar Pustaka: -', raw.get('Daftar Pustaka: -', raw.get('Daftar Pustaka:', []))),
        ('Kover belakang: -', raw.get('Kover belakang: -', raw.get('Kover Belakang:', [])))
    ]
    return sections

# Step 3: Populate each 2026 sheet
for d in districts_data:
    sname = d['sheet_2026']
    sheet = wb[sname]
    print(f"\nProcessing sheet: '{sname}'...")
    
    # 3a. Remove existing merges in rows >= 5 using unmerge_cells
    merges_to_remove = [str(rng) for rng in list(sheet.merged_cells.ranges) if rng.min_row >= 5]
    for rng_str in merges_to_remove:
        sheet.unmerge_cells(rng_str)
        
    # 3b. Clear content and borders in rows 5 to max(120, sheet.max_row)
    max_r = max(120, sheet.max_row)
    for r in range(5, max_r + 1):
        for c in range(2, 15):
            cell = sheet.cell(r, c)
            if not isinstance(cell, openpyxl.cell.cell.MergedCell):
                cell.value = None
                cell.font = font_item
                cell.alignment = align_left
                cell.border = Border()
            
    # 3c. Set Row 5 metadata
    sheet.cell(5, 2, 1.0)
    sheet.cell(5, 2).font = font_meta
    sheet.cell(5, 2).alignment = align_center
    
    sheet.cell(5, 3, d['title'])
    sheet.cell(5, 3).font = font_meta
    sheet.cell(5, 3).alignment = align_left
    
    sheet.cell(5, 4, 'Tahunan')
    sheet.cell(5, 4).font = font_meta
    sheet.cell(5, 4).alignment = align_center
    
    sheet.cell(5, 5, 'Indonesia ')
    sheet.cell(5, 5).font = font_meta
    sheet.cell(5, 5).alignment = align_center
    
    sheet.cell(5, 6, 'Sept')
    sheet.cell(5, 6).font = font_meta
    sheet.cell(5, 6).alignment = align_center
    
    sheet.cell(5, 7, '28/09/2026')
    sheet.cell(5, 7).font = font_meta
    sheet.cell(5, 7).alignment = align_center
    
    sheet.cell(5, 8, '√')
    sheet.cell(5, 8).font = font_meta
    sheet.cell(5, 8).alignment = align_center
    
    sheet.cell(5, 9, None)
    
    sheet.cell(5, 10, 'Sept')
    sheet.cell(5, 10).font = font_meta
    sheet.cell(5, 10).alignment = align_center
    
    sheet.cell(5, 11, None)
    sheet.cell(5, 14, None)
    
    # 3d. Populate Review Sections (Strictly Error Only from Evaluator)
    sections = get_evaluator_sections_for_district(d)
    curr_r = 5
    first_sec = True
    
    for sec_title, items in sections:
        if not first_sec:
            curr_r += 1
        else:
            first_sec = False
            
        # Section title in L:M
        sheet.cell(curr_r, 12, sec_title)
        sheet.cell(curr_r, 12).font = font_sec
        sheet.cell(curr_r, 12).alignment = align_left
        sheet.merge_cells(start_row=curr_r, start_column=12, end_row=curr_r, end_column=13)
        
        # Items under section (ONLY WRITTEN IF REAL ERRORS EXIST)
        for it in items:
            curr_r += 1
            sheet.cell(curr_r, 12, '-')
            sheet.cell(curr_r, 12).font = font_dash
            sheet.cell(curr_r, 12).alignment = align_center
            
            sheet.cell(curr_r, 13, it)
            sheet.cell(curr_r, 13).font = font_item
            sheet.cell(curr_r, 13).alignment = align_wrap
            
    last_r = curr_r
    print(f"  Populated review items up to row {last_r}")
    
    # 3e. Apply clean table borders for rows 5 to last_r
    for r in range(5, last_r + 1):
        is_last = (r == last_r)
        b_bottom = double_side if is_last else None
        
        # Col B (2)
        sheet.cell(r, 2).border = Border(left=thin_side, right=thin_side, bottom=b_bottom)
        # Col C (3)
        sheet.cell(r, 3).border = Border(left=None, right=thin_side, bottom=b_bottom)
        # Col D (4)
        sheet.cell(r, 4).border = Border(left=None, right=thin_side, bottom=b_bottom)
        # Col E (5)
        sheet.cell(r, 5).border = Border(left=None, right=thin_side, bottom=b_bottom)
        # Col F (6)
        sheet.cell(r, 6).border = Border(left=None, right=thin_side, bottom=b_bottom)
        # Col G (7)
        sheet.cell(r, 7).border = Border(left=None, right=thin_side, bottom=b_bottom)
        # Col H (8)
        sheet.cell(r, 8).border = Border(left=None, right=thin_side, bottom=b_bottom)
        # Col I (9)
        sheet.cell(r, 9).border = Border(left=None, right=thin_side, bottom=b_bottom)
        # Col J (10)
        sheet.cell(r, 10).border = Border(left=None, right=thin_side, bottom=b_bottom)
        # Col K (11)
        sheet.cell(r, 11).border = Border(left=None, right=thin_side, bottom=b_bottom)
        
        # Col L (12) & Col M (13)
        sheet.cell(r, 12).border = Border(left=thin_side, right=None, bottom=b_bottom)
        sheet.cell(r, 13).border = Border(left=thin_side, right=thin_side, bottom=b_bottom)
        
        # Col N (14)
        sheet.cell(r, 14).border = Border(left=None, right=thin_side, bottom=b_bottom)

# Step 4: Reorder sheets so 2025 and 2026 are paired neatly for each subdistrict
desired_sheet_order = []
for d in districts_data:
    desired_sheet_order.append(d['sheet_2025'])
    desired_sheet_order.append(d['sheet_2026'])

sheet_map = {s.title: s for s in wb.worksheets}
reordered_sheets = []
for name in desired_sheet_order:
    if name in sheet_map:
        reordered_sheets.append(sheet_map[name])

# Add any other sheet if existed
for s in wb.worksheets:
    if s not in reordered_sheets:
        reordered_sheets.append(s)

wb._sheets = reordered_sheets
print("\nFinal sheet order:")
print(wb.sheetnames)

# Step 5: Save the workbook
output_path = '7201_Evaluasi publikasi KcDA September 2025.xlsx'
candidates = [
    '7201_Evaluasi_Publikasi_KcDA_September_2026_MASTER_1PLUS1.xlsx',
    output_path,
    os.path.join('arsip_pengujian_dan_versi_lama', '7201_Evaluasi_Publikasi_KcDA_September_2026_Hasil_Revisi_SINKRON_WEB.xlsx')
]

saved_targets = []
for path in candidates:
    try:
        wb.save(path)
        print(f"Berhasil menyimpan workbook hasil revisi ke '{path}'!")
        saved_targets.append(path)
    except PermissionError:
        print(f"File '{path}' sedang dibuka/dikunci oleh aplikasi Excel.")
    except Exception as e:
        print(f"Gagal menyimpan ke '{path}': {e}")

if saved_targets:
    print(f"\nPROSES SELESAI SUKSES! File berhasil diperbarui pada: {', '.join(saved_targets)}")
else:
    print("\nPERINGATAN: Semua file tujuan sedang dikunci oleh Excel. Silakan tutup aplikasi Excel terlebih dahulu.")
