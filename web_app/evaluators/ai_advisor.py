"""
Modul Penghalus Bahasa & Variasi Temuan AI Gemini (Phase 3)
Menggunakan model Google Gemini untuk menghaluskan redaksi temuan tanpa mengubah makna substantif.
"""
import os
import json
import requests
from .common import DEFAULT_API_KEY, GEMINI_API_URL, VARIATION_CACHE, get_cache_file

def call_gemini_defect_variation(region, year, original_defects, api_key, pub_level="kecamatan"):
    prompt = f"""Peran: Auditor Dokumentasi dan Tata Kelola Publikasi BPS (Badan Pusat Statistik Indonesia).
Tugas: Perbaiki dan pertajam redaksi butir-butir evaluasi publikasi "{'Kota' if pub_level == 'kota' else 'Kabupaten' if pub_level == 'kabupaten' else 'Kecamatan'} {region} Dalam Angka {year}".

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

