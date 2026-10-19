import os
import sys
import uuid
import time
import socket
import shutil
import re
import zipfile
try:
    import rarfile
    if not shutil.which("unrar"):
        for cand in [
            r"C:\Program Files\WinRAR\UnRAR.exe",
            r"C:\Program Files (x86)\WinRAR\UnRAR.exe",
            r"C:\Program Files\WinRAR\WinRAR.exe",
        ]:
            if os.path.exists(cand):
                rarfile.UNRAR_TOOL = cand
                break
except ImportError:
    rarfile = None

try:
    import py7zr
except ImportError:
    py7zr = None
from typing import Optional, List
from fastapi import FastAPI, File, UploadFile, Form, HTTPException
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

# Tambahkan path aplikasi
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.append(current_dir)

from collections import Counter
from evaluator import (
    extract_pdf_metadata,
    analyze_defects,
    generate_excel_report,
    DEFAULT_API_KEY,
    WILAYAH_METADATA,
    ALL_REGENCIES_MAP,
)
from pdf_generator import generate_pdf_report
from batch_processor import generate_master_batch_excel, create_batch_zip

def get_kabupaten_code(kab_name: str) -> str:
    if not kab_name:
        return ""
    clean_k = kab_name.lower().replace("kabupaten", "").replace("kota", "").strip()
    for code, name in ALL_REGENCIES_MAP.items():
        name_clean = name.lower().replace("kabupaten", "").replace("kota", "").strip()
        if clean_k and (clean_k == name_clean or clean_k in name_clean or name_clean in clean_k):
            return str(code)
    return ""

def sanitize_clean_name(name: str) -> str:
    if not name:
        return ""
    clean = re.sub(r'[\\/*?:"<>|]', '_', str(name).strip())
    clean = re.sub(r'\s+', '_', clean)
    clean = re.sub(r'_+', '_', clean)
    return clean.strip('_')

app = FastAPI(title="Sistem Otomatisasi Evaluasi Publikasi BPS", version="2.0.0")

# Setup CORS (aman untuk LAN dan tunnel publik)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.middleware("http")
async def add_no_cache_header(request, call_next):
    response = await call_next(request)
    # Jangan cache API dinamis
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response

# Folder direktori
BASE_DIR = os.path.dirname(current_dir)
IS_CLOUD = bool(os.environ.get("VERCEL") or os.environ.get("AWS_LAMBDA_FUNCTION_NAME") or os.environ.get("SPACE_ID") or os.environ.get("HF_SPACE_ID"))
IS_VERCEL = bool(os.environ.get("VERCEL"))

if IS_CLOUD:
    UPLOAD_DIR = "/tmp/uploads"
    OUTPUT_DIR = "/tmp/outputs"
else:
    UPLOAD_DIR = os.path.join(current_dir, "uploads")
    OUTPUT_DIR = os.path.join(current_dir, "outputs")

STATIC_DIR = os.path.join(current_dir, "static")
TEMPLATES_DIR = os.path.join(current_dir, "templates")
SAMPLE_DIR = os.path.join(BASE_DIR, "PUBLIKASI BANGKEP")

os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)

# Mount static files
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

def cleanup_old_files(max_age_hours: int = 3):
    """Menghapus berkas sementara di uploads/ dan outputs/ yang berusia lebih dari max_age_hours."""
    now = time.time()
    cutoff = now - (max_age_hours * 3600)
    cleaned_count = 0
    cleaned_bytes = 0
    for folder in [UPLOAD_DIR, OUTPUT_DIR]:
        if not os.path.exists(folder):
            continue
        for fname in os.listdir(folder):
            if fname.startswith("."):
                continue
            fpath = os.path.join(folder, fname)
            try:
                if os.path.isfile(fpath) and os.path.getmtime(fpath) < cutoff:
                    sz = os.path.getsize(fpath)
                    os.remove(fpath)
                    cleaned_count += 1
                    cleaned_bytes += sz
            except Exception:
                pass
    if cleaned_count > 0:
        print(f"[Auto-Cleanup] Berhasil membersihkan {cleaned_count} berkas lawas ({round(cleaned_bytes / (1024*1024), 1)} MB)")

@app.on_event("startup")
def on_startup():
    cleanup_old_files(max_age_hours=3)

def get_lan_ip():
    """Mendapatkan alamat IP lokal LAN agar rekan sekantor bisa akses"""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
    except Exception:
        ip = "127.0.0.1"
    finally:
        s.close()
    return ip

@app.get("/", response_class=HTMLResponse)
async def serve_index():
    index_path = os.path.join(TEMPLATES_DIR, "index.html")
    if os.path.exists(index_path):
        with open(index_path, "r", encoding="utf-8") as f:
            content = f.read()
        return HTMLResponse(content=content)
    return HTMLResponse("<h1>Index file not found</h1>", status_code=404)

@app.get("/api/system-info")
def get_system_info():
    lan_ip = get_lan_ip()
    return {
        "status": "online",
        "lan_ip": lan_ip,
        "lan_url": f"http://{lan_ip}:8000",
        "has_default_api_key": bool(DEFAULT_API_KEY),
        "is_vercel": IS_VERCEL,
        "dataset_info": WILAYAH_METADATA or {
            "source": "Kemendagri (Kepmendagri No. 050-145-2022) & BPS RI Master Wilayah 2024",
            "version": "v2024.1-Kemendagri-BPS",
            "release_date": "Semester I 2024 / Edisi Publikasi 2026",
            "total_provinces": 38,
            "total_regencies": 514,
            "total_districts": 7288
        }
    }

@app.get("/api/sample-files")
def list_sample_files():
    samples = []
    for d in [SAMPLE_DIR, BASE_DIR]:
        if os.path.exists(d):
            for f in sorted(os.listdir(d)):
                if f.lower().endswith(".pdf") and not f.startswith("[") and not f.startswith("Pedoman") and not f.startswith("Template"):
                    display_name = f.replace(".pdf", "").replace("-", " ").title()
                    if not any(s["filename"] == f for s in samples):
                        samples.append({
                            "filename": f,
                            "display_name": display_name,
                            "size_mb": round(os.path.getsize(os.path.join(d, f)) / (1024 * 1024), 2)
                        })
    return {"samples": samples}

@app.post("/api/analyze-sample")
def analyze_sample(
    filename: str = Form(...),
    custom_api_key: Optional[str] = Form(None)
):
    safe_filename = os.path.basename(filename)
    pdf_path = os.path.join(SAMPLE_DIR, safe_filename)
    if not os.path.exists(pdf_path):
        pdf_path = os.path.join(BASE_DIR, safe_filename)
    if not os.path.exists(pdf_path):
        raise HTTPException(status_code=404, detail="File sampel tidak ditemukan.")
    
    # Proses analisis
    meta = extract_pdf_metadata(pdf_path)
    defects = analyze_defects(meta, custom_api_key=custom_api_key)
    
    # Hitung metrik
    total_defects = sum(len(items) for items in defects.values())
    clean_sections = sum(1 for items in defects.values() if len(items) == 0)
    
    # Generate Excel Report
    task_id = str(uuid.uuid4())[:8]
    excel_filename = f"Evaluasi_{meta['region'].replace(' ', '_')}_{meta['year']}_{task_id}.xlsx"
    excel_path = os.path.join(OUTPUT_DIR, excel_filename)
    
    # Buat file Excel laporan resmi BPS
    generate_excel_report(meta, defects, excel_path, base_template_path=None)
    
    # Generate Executive PDF Report
    pdf_filename = f"Laporan_Evaluasi_{meta['region'].replace(' ', '_')}_{meta['year']}_{task_id}.pdf"
    pdf_path = os.path.join(OUTPUT_DIR, pdf_filename)
    generate_pdf_report(meta, defects, pdf_path)
    
    return {
        "success": True,
        "task_id": task_id,
        "metadata": meta,
        "total_defects": total_defects,
        "clean_sections": clean_sections,
        "defects": defects,
        "download_url": f"/api/download/{excel_filename}",
        "excel_download_url": f"/api/download/{excel_filename}",
        "pdf_download_url": f"/api/download/{pdf_filename}",
        "source_pdf_filename": safe_filename,
        "source_pdf_url": f"/api/view-pdf/{safe_filename}"
    }

@app.post("/api/analyze-upload")
def analyze_upload(
    pdf_file: UploadFile = File(...),
    excel_file: Optional[UploadFile] = File(None),
    custom_api_key: Optional[str] = Form(None)
):
    if not pdf_file.filename or not pdf_file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="File harus berformat PDF.")
    
    task_id = str(uuid.uuid4())[:8]
    safe_pdf_orig = os.path.basename(pdf_file.filename)
    saved_pdf_name = f"upload_{task_id}_{safe_pdf_orig}"
    saved_pdf_path = os.path.join(UPLOAD_DIR, saved_pdf_name)
    
    MAX_UPLOAD_SIZE = 150 * 1024 * 1024  # 150 MB
    file_bytes_written = 0
    with open(saved_pdf_path, "wb") as f:
        while chunk := pdf_file.file.read(1024 * 1024):  # 1MB buffer
            file_bytes_written += len(chunk)
            if file_bytes_written > MAX_UPLOAD_SIZE:
                f.close()
                if os.path.exists(saved_pdf_path):
                    os.remove(saved_pdf_path)
                raise HTTPException(status_code=400, detail="Ukuran file PDF melebihi batas maksimal yang diizinkan (150 MB).")
            f.write(chunk)
        
    base_template_path = None
    if excel_file and excel_file.filename:
        safe_excel_orig = os.path.basename(excel_file.filename)
        saved_excel_name = f"upload_tpl_{task_id}_{safe_excel_orig}"
        base_template_path = os.path.join(UPLOAD_DIR, saved_excel_name)
        with open(base_template_path, "wb") as f:
            shutil.copyfileobj(excel_file.file, f)
    else:
        base_template_path = None
            
    # Ekstraksi dan Analisis dengan perlindungan crash
    try:
        meta = extract_pdf_metadata(saved_pdf_path)
        defects = analyze_defects(meta, custom_api_key=custom_api_key)
        
        total_defects = sum(len(items) for items in defects.values())
        clean_sections = sum(1 for items in defects.values() if len(items) == 0)
        
        # Penamaan Hasil Ekspor Resmi & Informatif sesuai Standar BPS
        kab = meta.get("kabupaten") or ""
        kab_code = get_kabupaten_code(kab)
        prefix = f"{kab_code}_" if kab_code else ""
        region_clean = sanitize_clean_name(meta.get("region", "Wilayah"))
        year_clean = str(meta.get("year", 2026))
        
        # Generate Excel Report
        excel_filename = f"{prefix}Evaluasi_Publikasi_KcDA_Kecamatan_{region_clean}_{year_clean}.xlsx"
        excel_path = os.path.join(OUTPUT_DIR, excel_filename)
        generate_excel_report(meta, defects, excel_path, base_template_path=base_template_path)
        
        # Generate Executive PDF Report
        pdf_filename = f"{prefix}Laporan_Evaluasi_KcDA_Kecamatan_{region_clean}_{year_clean}.pdf"
        pdf_path = os.path.join(OUTPUT_DIR, pdf_filename)
        generate_pdf_report(meta, defects, pdf_path)
    except Exception as e:
        if os.path.exists(saved_pdf_path):
            try:
                os.remove(saved_pdf_path)
            except Exception:
                pass
        err_str = str(e)
        if any(term in err_str.lower() for term in ["fitz", "filedataerror", "cannot open", "password", "corrupt", "damaged"]):
            raise HTTPException(status_code=400, detail="File PDF rusak, terenkripsi kata sandi, atau format tidak dapat dibaca oleh engine analisis.")
        raise HTTPException(status_code=500, detail=f"Gagal memproses evaluasi publikasi: {err_str}")
    
    return {
        "success": True,
        "task_id": task_id,
        "metadata": meta,
        "total_defects": total_defects,
        "clean_sections": clean_sections,
        "defects": defects,
        "excel_filename": excel_filename,
        "pdf_filename": pdf_filename,
        "download_url": f"/api/download/{excel_filename}",
        "excel_download_url": f"/api/download/{excel_filename}",
        "pdf_download_url": f"/api/download/{pdf_filename}",
        "source_pdf_filename": saved_pdf_name,
        "source_pdf_url": f"/api/view-pdf/{saved_pdf_name}"
    }

@app.post("/api/analyze-batch-bangkep")
def analyze_batch_bangkep(custom_api_key: Optional[str] = Form(None)):
    sample_files = []
    if os.path.exists(SAMPLE_DIR):
        for f in sorted(os.listdir(SAMPLE_DIR)):
            if f.lower().endswith(".pdf") and f.lower().startswith("kecamatan"):
                sample_files.append(os.path.join(SAMPLE_DIR, f))
                
    if not sample_files:
        raise HTTPException(status_code=404, detail="Berkas publikasi Bangkep tidak ditemukan di folder sampel.")

    task_id = str(uuid.uuid4())[:8]
    eval_results = []
    zip_items = []
    
    total_aggregate_defects = 0
    total_clean_districts = 0
    total_mismatch_districts = 0

    for item_idx, pdf_path in enumerate(sample_files):
        meta = extract_pdf_metadata(pdf_path)
        defects = analyze_defects(meta, custom_api_key=custom_api_key)
        tot_d = sum(len(items) for items in defects.values())
        clean_sec = sum(1 for items in defects.values() if len(items) == 0)
        
        is_mismatch = meta.get("district_mismatch_info", {}).get("is_mismatch", False)
        if is_mismatch:
            total_mismatch_districts += 1
        if tot_d == 0:
            total_clean_districts += 1
        total_aggregate_defects += tot_d

        item_kab = meta.get("kabupaten") or "Kabupaten Banggai Kepulauan"
        item_code = get_kabupaten_code(item_kab) or "7201"
        item_prefix = f"{item_code}_" if item_code else ""
        item_reg = sanitize_clean_name(meta.get("region", f"Kecamatan_{item_idx+1}"))
        item_year = str(meta.get("year", 2026))

        pdf_fn = f"{item_prefix}Laporan_Evaluasi_KcDA_Kecamatan_{item_reg}_{item_year}.pdf"
        pdf_out_path = os.path.join(OUTPUT_DIR, pdf_fn)
        generate_pdf_report(meta, defects, pdf_out_path)
        zip_items.append((pdf_out_path, pdf_fn))

        excel_fn = f"{item_prefix}Evaluasi_Publikasi_KcDA_Kecamatan_{item_reg}_{item_year}.xlsx"
        excel_out_path = os.path.join(OUTPUT_DIR, excel_fn)
        generate_excel_report(meta, defects, excel_out_path, base_template_path=None)

        eval_results.append({
            "district_name": meta["region"],
            "region": meta["region"],
            "year": meta["year"],
            "title": meta["title"],
            "catalog": meta["catalog"],
            "issn": meta["issn"],
            "total_defects": tot_d,
            "clean_sections": clean_sec,
            "is_mismatch": is_mismatch,
            "mismatch_details": meta.get("district_mismatch_info", {}),
            "raw_template_info": meta.get("raw_template_info", {}),
            "meta": meta,
            "metadata": meta,
            "defects": defects,
            "pdf_filename": pdf_fn,
            "pdf_download_url": f"/api/download/{pdf_fn}",
            "excel_filename": excel_fn,
            "excel_download_url": f"/api/download/{excel_fn}",
            "download_url": f"/api/download/{excel_fn}",
            "source_pdf_filename": os.path.basename(pdf_path),
            "source_pdf_url": f"/api/view-pdf/{os.path.basename(pdf_path)}"
        })

    master_excel_fn = "7201_Evaluasi_Publikasi_KcDA_Banggai_Kepulauan_2026_MASTER.xlsx"
    master_excel_path = os.path.join(OUTPUT_DIR, master_excel_fn)
    generate_master_batch_excel(eval_results, master_excel_path, regency_title="Kabupaten Banggai Kepulauan")

    zip_fn = "7201_Laporan_Evaluasi_PDF_KcDA_Banggai_Kepulauan_2026.zip"
    zip_out_path = os.path.join(OUTPUT_DIR, zip_fn)
    create_batch_zip(zip_items, zip_out_path)

    return {
        "success": True,
        "task_id": task_id,
        "regency": "Kabupaten Banggai Kepulauan",
        "total_districts": len(eval_results),
        "total_defects": total_aggregate_defects,
        "total_aggregate_defects": total_aggregate_defects,
        "clean_districts": total_clean_districts,
        "total_clean_districts": total_clean_districts,
        "mismatch_districts": total_mismatch_districts,
        "total_mismatch_districts": total_mismatch_districts,
        "master_excel_filename": master_excel_fn,
        "zip_filename": zip_fn,
        "master_excel_download_url": f"/api/download/{master_excel_fn}",
        "zip_download_url": f"/api/download/{zip_fn}",
        "zip_pdf_download_url": f"/api/download/{zip_fn}",
        "districts": eval_results
    }

@app.post("/api/analyze-batch-upload")
def analyze_batch_upload(
    pdf_files: List[UploadFile] = File(...),
    custom_api_key: Optional[str] = Form(None)
):
    if not pdf_files:
        raise HTTPException(status_code=400, detail="Tidak ada berkas PDF yang diunggah.")

    task_id = str(uuid.uuid4())[:8]
    eval_results = []
    zip_items = []
    
    total_aggregate_defects = 0
    total_clean_districts = 0
    total_mismatch_districts = 0

    pdf_items_to_process = []
    temp_zip_paths = []
    
    for file_obj in pdf_files:
        safe_orig_name = os.path.basename(file_obj.filename)
        fname_lower = safe_orig_name.lower()
        if fname_lower.endswith(".zip"):
            zip_saved_path = os.path.join(UPLOAD_DIR, f"zip_{task_id}_{safe_orig_name}")
            temp_zip_paths.append(zip_saved_path)
            with open(zip_saved_path, "wb") as f:
                shutil.copyfileobj(file_obj.file, f)
            try:
                with zipfile.ZipFile(zip_saved_path, 'r') as zf:
                    for member in zf.namelist():
                        member_base = os.path.basename(member)
                        if member_base.lower().endswith(".pdf") and not member.startswith("__MACOSX") and not member_base.startswith("."):
                            safe_member_base = re.sub(r'[\\/*?:"<>|]', '_', member_base)
                            item_num = len(pdf_items_to_process) + 1
                            extracted_name = f"batch_{task_id}_{item_num}_{safe_member_base}"
                            extracted_path = os.path.join(UPLOAD_DIR, extracted_name)
                            with open(extracted_path, "wb") as out_f, zf.open(member) as in_f:
                                shutil.copyfileobj(in_f, out_f)
                            if os.path.exists(extracted_path) and os.path.getsize(extracted_path) > 500:
                                pdf_items_to_process.append({
                                    "path": extracted_path,
                                    "saved_name": extracted_name,
                                    "display_name": member_base
                                })
            except Exception as e:
                print(f"[ZIP Upload] Error extracting zip {safe_orig_name}: {e}")
        elif fname_lower.endswith(".rar"):
            rar_saved_path = os.path.join(UPLOAD_DIR, f"rar_{task_id}_{safe_orig_name}")
            temp_zip_paths.append(rar_saved_path)
            with open(rar_saved_path, "wb") as f:
                shutil.copyfileobj(file_obj.file, f)
            try:
                if rarfile is not None:
                    with rarfile.RarFile(rar_saved_path, 'r') as rf:
                        for member in rf.infolist():
                            member_base = os.path.basename(member.filename)
                            if member_base.lower().endswith(".pdf") and not member.filename.startswith("__MACOSX") and not member_base.startswith("."):
                                safe_member_base = re.sub(r'[\\/*?:"<>|]', '_', member_base)
                                item_num = len(pdf_items_to_process) + 1
                                extracted_name = f"batch_{task_id}_{item_num}_{safe_member_base}"
                                extracted_path = os.path.join(UPLOAD_DIR, extracted_name)
                                with open(extracted_path, "wb") as out_f, rf.open(member) as in_f:
                                    shutil.copyfileobj(in_f, out_f)
                                if os.path.exists(extracted_path) and os.path.getsize(extracted_path) > 500:
                                    pdf_items_to_process.append({
                                        "path": extracted_path,
                                        "saved_name": extracted_name,
                                        "display_name": member_base
                                    })
                else:
                    # Fallback menggunakan Windows bsdtar jika rarfile tidak terpasang
                    import subprocess
                    tar_bin = shutil.which("tar") or "tar.exe"
                    tar_extract_dir = os.path.join(UPLOAD_DIR, f"rar_ext_{task_id}")
                    os.makedirs(tar_extract_dir, exist_ok=True)
                    subprocess.run([tar_bin, "-xf", rar_saved_path, "-C", tar_extract_dir], capture_output=True)
                    for root_dir, _, files_in_dir in os.walk(tar_extract_dir):
                        for f_in in files_in_dir:
                            if f_in.lower().endswith(".pdf") and not f_in.startswith("."):
                                safe_member_base = re.sub(r'[\\/*?:"<>|]', '_', f_in)
                                item_num = len(pdf_items_to_process) + 1
                                extracted_name = f"batch_{task_id}_{item_num}_{safe_member_base}"
                                extracted_path = os.path.join(UPLOAD_DIR, extracted_name)
                                shutil.copy2(os.path.join(root_dir, f_in), extracted_path)
                                if os.path.exists(extracted_path) and os.path.getsize(extracted_path) > 500:
                                    pdf_items_to_process.append({
                                        "path": extracted_path,
                                        "saved_name": extracted_name,
                                        "display_name": f_in
                                    })
            except Exception as e:
                print(f"[RAR Upload] Error extracting rar {safe_orig_name}: {e}")
        elif fname_lower.endswith(".7z"):
            sz_saved_path = os.path.join(UPLOAD_DIR, f"7z_{task_id}_{safe_orig_name}")
            temp_zip_paths.append(sz_saved_path)
            with open(sz_saved_path, "wb") as f:
                shutil.copyfileobj(file_obj.file, f)
            try:
                if py7zr is not None:
                    sz_ext_dir = os.path.join(UPLOAD_DIR, f"7z_ext_{task_id}")
                    os.makedirs(sz_ext_dir, exist_ok=True)
                    with py7zr.SevenZipFile(sz_saved_path, 'r') as szf:
                        szf.extractall(path=sz_ext_dir)
                    for root_dir, _, files_in_dir in os.walk(sz_ext_dir):
                        for f_in in files_in_dir:
                            if f_in.lower().endswith(".pdf") and not f_in.startswith("."):
                                safe_member_base = re.sub(r'[\\/*?:"<>|]', '_', f_in)
                                item_num = len(pdf_items_to_process) + 1
                                extracted_name = f"batch_{task_id}_{item_num}_{safe_member_base}"
                                extracted_path = os.path.join(UPLOAD_DIR, extracted_name)
                                shutil.copy2(os.path.join(root_dir, f_in), extracted_path)
                                if os.path.exists(extracted_path) and os.path.getsize(extracted_path) > 500:
                                    pdf_items_to_process.append({
                                        "path": extracted_path,
                                        "saved_name": extracted_name,
                                        "display_name": f_in
                                    })
            except Exception as e:
                print(f"[7Z Upload] Error extracting 7z {safe_orig_name}: {e}")
        elif fname_lower.endswith(".pdf"):
            item_num = len(pdf_items_to_process) + 1
            saved_name = f"batch_{task_id}_{item_num}_{safe_orig_name}"
            saved_path = os.path.join(UPLOAD_DIR, saved_name)
            with open(saved_path, "wb") as f:
                shutil.copyfileobj(file_obj.file, f)
            if os.path.exists(saved_path) and os.path.getsize(saved_path) > 500:
                pdf_items_to_process.append({
                    "path": saved_path,
                    "saved_name": saved_name,
                    "display_name": safe_orig_name
                })

    if not pdf_items_to_process:
        raise HTTPException(
            status_code=400, 
            detail="Tidak ditemukan berkas PDF yang valid di dalam unggahan atau arsip ZIP. Pastikan berkas berformat .pdf dan tidak kosong."
        )

    for item_idx, item in enumerate(pdf_items_to_process):
        saved_path = item["path"]
        saved_name = item["saved_name"]
        display_name = item["display_name"]

        try:
            meta = extract_pdf_metadata(saved_path)
            defects = analyze_defects(meta, custom_api_key=custom_api_key)
            tot_d = sum(len(items) for items in defects.values())
            clean_sec = sum(1 for items in defects.values() if len(items) == 0)
            
            is_mismatch = meta.get("district_mismatch_info", {}).get("is_mismatch", False)
            if is_mismatch:
                total_mismatch_districts += 1
            if tot_d == 0:
                total_clean_districts += 1
            total_aggregate_defects += tot_d

            item_kab = meta.get("kabupaten") or ""
            item_code = get_kabupaten_code(item_kab)
            item_prefix = f"{item_code}_" if item_code else ""
            item_reg = sanitize_clean_name(meta.get("region", display_name))
            item_year = str(meta.get("year", 2026))

            pdf_fn = f"{item_prefix}Laporan_Evaluasi_KcDA_Kecamatan_{item_reg}_{item_year}.pdf"
            pdf_out_path = os.path.join(OUTPUT_DIR, pdf_fn)
            generate_pdf_report(meta, defects, pdf_out_path)
            zip_items.append((pdf_out_path, pdf_fn))

            excel_fn = f"{item_prefix}Evaluasi_Publikasi_KcDA_Kecamatan_{item_reg}_{item_year}.xlsx"
            excel_out_path = os.path.join(OUTPUT_DIR, excel_fn)
            generate_excel_report(meta, defects, excel_out_path, base_template_path=None)

            eval_results.append({
                "district_name": meta.get("region", display_name),
                "region": meta.get("region", display_name),
                "year": meta.get("year", 2026),
                "title": meta.get("title", display_name),
                "catalog": meta.get("catalog", "-"),
                "issn": meta.get("issn", "-"),
                "total_defects": tot_d,
                "clean_sections": clean_sec,
                "is_mismatch": is_mismatch,
                "mismatch_details": meta.get("district_mismatch_info", {}),
                "raw_template_info": meta.get("raw_template_info", {}),
                "meta": meta,
                "metadata": meta,
                "defects": defects,
                "pdf_filename": pdf_fn,
                "pdf_download_url": f"/api/download/{pdf_fn}",
                "excel_filename": excel_fn,
                "excel_download_url": f"/api/download/{excel_fn}",
                "download_url": f"/api/download/{excel_fn}",
                "source_pdf_filename": saved_name,
                "source_pdf_url": f"/api/view-pdf/{saved_name}"
            })
        except Exception as item_err:
            print(f"[Batch Processing] Error on {display_name}: {item_err}")

    if not eval_results:
        raise HTTPException(status_code=400, detail="Tidak ada berkas PDF yang valid untuk diproses.")

    unique_kabs = [r["meta"].get("kabupaten") for r in eval_results if r["meta"].get("kabupaten")]
    unique_kabs = list(dict.fromkeys(unique_kabs))
    
    years = [str(r["meta"].get("year", 2026)) for r in eval_results if r["meta"].get("year")]
    dominant_year = Counter(years).most_common(1)[0][0] if years else "2026"

    if len(unique_kabs) == 1 and unique_kabs[0]:
        kab_full = unique_kabs[0]
        kab_code = get_kabupaten_code(kab_full)
        kab_clean = sanitize_clean_name(kab_full.replace("Kabupaten ", "").replace("Kota ", ""))
        prefix = f"{kab_code}_" if kab_code else ""
        reg_title = kab_full
        master_excel_fn = f"{prefix}Evaluasi_Publikasi_KcDA_{kab_clean}_{dominant_year}_MASTER.xlsx"
        zip_fn = f"{prefix}Laporan_Evaluasi_PDF_KcDA_{kab_clean}_{dominant_year}.zip"
    else:
        reg_title = f"Kolektif ({len(eval_results)} Kecamatan)"
        master_excel_fn = f"Master_Evaluasi_Publikasi_KcDA_{dominant_year}_Kolektif_{len(eval_results)}_Kecamatan.xlsx"
        zip_fn = f"Kumpulan_Laporan_Evaluasi_PDF_KcDA_{dominant_year}_{len(eval_results)}_Kecamatan.zip"

    master_excel_path = os.path.join(OUTPUT_DIR, master_excel_fn)
    generate_master_batch_excel(eval_results, master_excel_path, regency_title=reg_title)

    zip_out_path = os.path.join(OUTPUT_DIR, zip_fn)
    create_batch_zip(zip_items, zip_out_path)

    for zp in temp_zip_paths:
        try:
            if os.path.exists(zp):
                os.remove(zp)
        except Exception:
            pass

    return {
        "success": True,
        "task_id": task_id,
        "total_districts": len(eval_results),
        "total_defects": total_aggregate_defects,
        "total_aggregate_defects": total_aggregate_defects,
        "clean_districts": total_clean_districts,
        "total_clean_districts": total_clean_districts,
        "mismatch_districts": total_mismatch_districts,
        "total_mismatch_districts": total_mismatch_districts,
        "master_excel_filename": master_excel_fn,
        "zip_filename": zip_fn,
        "master_excel_download_url": f"/api/download/{master_excel_fn}",
        "zip_download_url": f"/api/download/{zip_fn}",
        "zip_pdf_download_url": f"/api/download/{zip_fn}",
        "districts": eval_results
    }

@app.get("/api/download/{filename}")
def download_file(filename: str):
    safe_fn = os.path.basename(filename)
    file_path = os.path.realpath(os.path.join(OUTPUT_DIR, safe_fn))
    output_dir_real = os.path.realpath(OUTPUT_DIR)
    
    if not file_path.startswith(output_dir_real) or not os.path.exists(file_path) or not os.path.isfile(file_path):
        raise HTTPException(status_code=404, detail="File unduhan tidak ditemukan.")
    
    if safe_fn.lower().endswith(".zip"):
        media_type = "application/zip"
    elif safe_fn.lower().endswith(".pdf"):
        media_type = "application/pdf"
    else:
        media_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

    return FileResponse(
        path=file_path,
        filename=safe_fn,
        media_type=media_type,
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0"
        }
    )

@app.get("/api/view-pdf/{filename}")
def view_pdf(filename: str):
    clean_fn = os.path.basename(filename)
    allowed_dirs = [os.path.realpath(d) for d in [UPLOAD_DIR, SAMPLE_DIR, OUTPUT_DIR, BASE_DIR] if os.path.exists(d)]
    target_path = None
    for ad in allowed_dirs:
        cand = os.path.realpath(os.path.join(ad, clean_fn))
        if cand.startswith(ad) and os.path.exists(cand) and os.path.isfile(cand):
            target_path = cand
            break
            
    if not target_path or not target_path.lower().endswith(".pdf"):
        raise HTTPException(status_code=404, detail="Berkas PDF tidak ditemukan.")
        
    return FileResponse(
        path=target_path,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f"inline; filename=\"{clean_fn}\"",
            "Cache-Control": "public, max-age=3600"
        }
    )

if __name__ == "__main__":
    import uvicorn
    print(f"Starting BPS KcDA Review Web App on http://0.0.0.0:8000...")
    uvicorn.run(app, host="0.0.0.0", port=8000)

