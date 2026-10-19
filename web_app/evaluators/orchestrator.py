"""
Orkestrator Evaluasi Publikasi BPS (Phase 2)
Mengintegrasikan seluruh evaluator 11 anatomi publikasi, audit lintas halaman,
dan penyusunan kamus temuan terstruktur.
"""
from .common import load_variation_cache, deduplicate_all_defects
from .kover_depan import evaluate_kover_depan
from .halaman_judul import evaluate_halaman_judul
from .katalog import evaluate_katalog
from .tim_penyusun import evaluate_tim_penyusun
from .kata_pengantar import evaluate_kata_pengantar
from .daftar_isi import evaluate_daftar_isi, evaluate_daftar_tabel_gambar
from .penjelasan_umum import evaluate_penjelasan_umum
from .batang_tubuh import evaluate_layout_isi
from .daftar_pustaka import evaluate_daftar_pustaka
from .kover_belakang import evaluate_kover_belakang
from .cross_page import apply_cross_page_checks
from .dwibahasa import audit_bilingual_compliance

def analyze_defects(meta, custom_api_key=None):
    """
    Evaluasi Kepatuhan Publikasi BPS Berdasarkan 11 Bagian Anatomi Resmi
    Sesuai Pedoman Pembuatan Publikasi BPS 2023 & Instrumen Pemeriksaan Publikasi.
    """
    load_variation_cache()
    region = meta["region"]
    year = meta["year"]
    
    kabupaten_str = meta.get("kabupaten") or f"Kabupaten {region}"
    kab_upper = kabupaten_str.upper()
    kab_raw = kabupaten_str.replace("Kabupaten ", "").replace("Kota ", "").strip().upper()

    pub_level = meta.get("pub_level", "kecamatan")
    if pub_level == "kota":
        level_id = "Kota"
        level_en = "Municipality"
        level_en_upper = "MUNICIPALITY"
    elif pub_level == "kabupaten":
        level_id = "Kabupaten"
        level_en = "Regency"
        level_en_upper = "REGENCY"
    else:
        level_id = "Kecamatan"
        level_en = "District"
        level_en_upper = "DISTRICT"

    kover_depan = evaluate_kover_depan(meta, kabupaten_str, kab_upper, kab_raw, level_id, level_en, level_en_upper)
    halaman_judul = evaluate_halaman_judul(meta, kabupaten_str, kab_upper, kab_raw, level_id, level_en, level_en_upper)
    halaman_katalog = evaluate_katalog(meta, kabupaten_str, kab_upper, kab_raw, level_id, level_en, level_en_upper)
    tim_penyusun = evaluate_tim_penyusun(meta, kabupaten_str, kab_upper, kab_raw, level_id, level_en, level_en_upper)
    kata_pengantar = evaluate_kata_pengantar(meta, kabupaten_str, kab_upper, kab_raw, level_id, level_en, level_en_upper)
    daftar_isi = evaluate_daftar_isi(meta)
    penjelasan_umum = evaluate_penjelasan_umum(meta)
    daftar_tabel_gambar = evaluate_daftar_tabel_gambar(meta)
    layout_isi = evaluate_layout_isi(meta, kabupaten_str, kab_upper, kab_raw, level_id, level_en, level_en_upper)
    daftar_pustaka = evaluate_daftar_pustaka(meta)
    kover_belakang = evaluate_kover_belakang(meta)

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

    audit_bilingual_compliance(meta, raw_res)
    apply_cross_page_checks(meta, raw_res)
    return deduplicate_all_defects(raw_res)
