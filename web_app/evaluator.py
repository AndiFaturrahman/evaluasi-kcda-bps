"""
Sistem Evaluasi Kepatuhan Format Publikasi BPS (Master Facade Module)
Refaktorisasi Modular: Logika evaluasi telah dipecah rapi per bagian anatomi publikasi
di dalam paket `web_app.evaluators`. Modul ini bertindak sebagai Facade untuk menjamin
100% kompatibilitas terhadap seluruh file pemanggil (main.py, batch_processor.py, dll.)

Struktur Modul per Anatomi di `web_app/evaluators/`:
- evaluators.kover_depan: Anatomi 1 (Kover Depan)
- evaluators.halaman_judul: Anatomi 2 (Halaman Judul Utama)
- evaluators.katalog: Anatomi 3 (Halaman Katalog BPS)
- evaluators.tim_penyusun: Anatomi 4 (Halaman Tim Penyusun)
- evaluators.kata_pengantar: Anatomi 5 (Halaman Kata Pengantar)
- evaluators.daftar_isi: Anatomi 6 & 8 (Daftar Isi & Daftar Tabel/Gambar/Lampiran)
- evaluators.penjelasan_umum: Anatomi 7 (Penjelasan Umum)
- evaluators.batang_tubuh: Anatomi 9 (Layout Isi & Batang Tubuh)
- evaluators.daftar_pustaka: Anatomi 10 (Daftar Pustaka)
- evaluators.kover_belakang: Anatomi 11 (Kover Belakang)
- evaluators.cross_page: Pemeriksaan Konsistensi Lintas Halaman & Integritas Dokumen
- evaluators.extractor: Ekstraksi Data PDF & Computer Vision (Phase 1)
- evaluators.orchestrator: Orkestrasi Temuan (Phase 2)
- evaluators.ai_advisor: Penghalusan Narasi Gemini AI (Phase 3)
- evaluators.excel_reporter: Lembar Kerja Excel Resmi BPS (Phase 4)
"""

try:
    from .evaluators.common import (
        validate_issn_checksum,
        detect_kabupaten_name,
        find_page_with_text,
        scan_cover_raster_header,
        load_variation_cache,
        DEFAULT_API_KEY,
        GEMINI_API_URL,
        WILAYAH_METADATA,
        WILAYAH_DATA_PATH,
        KECAMATAN_TO_KABUPATEN,
        URL_SUBDOMAIN_TO_KABUPATEN,
        ALL_REGENCIES_MAP,
        DUPLICATE_KECAMATAN_MAP,
        KNOWN_BANGKEP_ISSN,
        JABATAN_SALAH_JAMAK,
        get_cache_file,
        get_aesthetic_and_standard_suggestions,
        classify_cover_finding,
        classify_hju_finding,
        deduplicate_section_items,
        deduplicate_all_defects,
    )
    from .evaluators.extractor import extract_pdf_metadata
    from .evaluators.orchestrator import analyze_defects
    from .evaluators.excel_reporter import generate_excel_report
    from .evaluators.ai_advisor import call_gemini_defect_variation
    from .evaluators.pdf_reader_engine import VisualPDFReader, VisualPage, TableStructure
except (ImportError, ValueError):
    from evaluators.common import (
        validate_issn_checksum,
        detect_kabupaten_name,
        find_page_with_text,
        scan_cover_raster_header,
        load_variation_cache,
        DEFAULT_API_KEY,
        GEMINI_API_URL,
        WILAYAH_METADATA,
        WILAYAH_DATA_PATH,
        KECAMATAN_TO_KABUPATEN,
        URL_SUBDOMAIN_TO_KABUPATEN,
        ALL_REGENCIES_MAP,
        DUPLICATE_KECAMATAN_MAP,
        KNOWN_BANGKEP_ISSN,
        JABATAN_SALAH_JAMAK,
        get_cache_file,
        get_aesthetic_and_standard_suggestions,
        classify_cover_finding,
        classify_hju_finding,
        deduplicate_section_items,
        deduplicate_all_defects,
    )
    from evaluators.extractor import extract_pdf_metadata
    from evaluators.orchestrator import analyze_defects
    from evaluators.excel_reporter import generate_excel_report
    from evaluators.ai_advisor import call_gemini_defect_variation
    from evaluators.pdf_reader_engine import VisualPDFReader, VisualPage, TableStructure

__all__ = [
    "extract_pdf_metadata",
    "analyze_defects",
    "generate_excel_report",
    "validate_issn_checksum",
    "detect_kabupaten_name",
    "find_page_with_text",
    "scan_cover_raster_header",
    "load_variation_cache",
    "call_gemini_defect_variation",
    "VisualPDFReader",
    "VisualPage",
    "TableStructure",
    "DEFAULT_API_KEY",
    "GEMINI_API_URL",
    "WILAYAH_METADATA",
    "WILAYAH_DATA_PATH",
    "KECAMATAN_TO_KABUPATEN",
    "URL_SUBDOMAIN_TO_KABUPATEN",
    "ALL_REGENCIES_MAP",
    "DUPLICATE_KECAMATAN_MAP",
    "KNOWN_BANGKEP_ISSN",
    "JABATAN_SALAH_JAMAK",
    "get_cache_file",
    "get_aesthetic_and_standard_suggestions",
    "classify_cover_finding",
    "classify_hju_finding",
    "deduplicate_section_items",
    "deduplicate_all_defects",
]
