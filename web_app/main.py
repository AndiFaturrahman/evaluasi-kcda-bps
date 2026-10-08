import os
import sys
import uuid
import socket
import shutil
from typing import Optional, List
from fastapi import FastAPI, File, UploadFile, Form, HTTPException
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

# Tambahkan path aplikasi
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.append(current_dir)

from evaluator import extract_pdf_metadata, analyze_defects, generate_excel_report, DEFAULT_API_KEY
from pdf_generator import generate_pdf_report
from batch_processor import generate_master_batch_excel, create_batch_zip

app = FastAPI(title="Sistem Otomatisasi Evaluasi Publikasi BPS", version="2.0.0")

# Setup CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.middleware("http")
async def add_no_cache_header(request, call_next):
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response

# Folder direktori
BASE_DIR = os.path.dirname(current_dir)
IS_CLOUD = bool(os.environ.get("VERCEL") or os.environ.get("AWS_LAMBDA_FUNCTION_NAME") or os.environ.get("SPACE_ID") or os.environ.get("HF_SPACE_ID"))
IS_VERCEL = IS_CLOUD

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
async def get_system_info():
    lan_ip = get_lan_ip()
    return {
        "status": "online",
        "lan_ip": lan_ip,
        "lan_url": f"http://{lan_ip}:8000",
        "has_default_api_key": bool(DEFAULT_API_KEY),
        "is_vercel": IS_VERCEL
    }

@app.get("/api/sample-files")
async def list_sample_files():
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
async def analyze_sample(
    filename: str = Form(...),
    custom_api_key: Optional[str] = Form(None)
):
    pdf_path = os.path.join(SAMPLE_DIR, filename)
    if not os.path.exists(pdf_path):
        pdf_path = os.path.join(BASE_DIR, filename)
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
        "source_pdf_filename": filename,
        "source_pdf_url": f"/api/view-pdf/{filename}"
    }

@app.post("/api/analyze-upload")
async def analyze_upload(
    pdf_file: UploadFile = File(...),
    excel_file: Optional[UploadFile] = File(None),
    custom_api_key: Optional[str] = Form(None)
):
    if not pdf_file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="File harus berformat PDF.")
    
    task_id = str(uuid.uuid4())[:8]
    saved_pdf_name = f"upload_{task_id}_{pdf_file.filename}"
    saved_pdf_path = os.path.join(UPLOAD_DIR, saved_pdf_name)
    
    with open(saved_pdf_path, "wb") as f:
        shutil.copyfileobj(pdf_file.file, f)
        
    base_template_path = None
    if excel_file and excel_file.filename:
        saved_excel_name = f"upload_tpl_{task_id}_{excel_file.filename}"
        base_template_path = os.path.join(UPLOAD_DIR, saved_excel_name)
        with open(base_template_path, "wb") as f:
            shutil.copyfileobj(excel_file.file, f)
    else:
        base_template_path = None
            
    # Ekstraksi dan Analisis
    meta = extract_pdf_metadata(saved_pdf_path)
    defects = analyze_defects(meta, custom_api_key=custom_api_key)
    
    total_defects = sum(len(items) for items in defects.values())
    clean_sections = sum(1 for items in defects.values() if len(items) == 0)
    
    # Generate Excel Report
    excel_filename = f"Evaluasi_{meta['region'].replace(' ', '_')}_{meta['year']}_{task_id}.xlsx"
    excel_path = os.path.join(OUTPUT_DIR, excel_filename)
    generate_excel_report(meta, defects, excel_path, base_template_path=base_template_path)
    
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
        "source_pdf_filename": saved_pdf_name,
        "source_pdf_url": f"/api/view-pdf/{saved_pdf_name}"
    }

@app.post("/api/analyze-batch-bangkep")
async def analyze_batch_bangkep(custom_api_key: Optional[str] = Form(None)):
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

    for pdf_path in sample_files:
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

        pdf_fn = f"Laporan_Evaluasi_{meta['region'].replace(' ', '_')}_{meta['year']}_{task_id}.pdf"
        pdf_out_path = os.path.join(OUTPUT_DIR, pdf_fn)
        generate_pdf_report(meta, defects, pdf_out_path)
        zip_items.append((pdf_out_path, pdf_fn))

        excel_fn = f"Evaluasi_{meta['region'].replace(' ', '_')}_{meta['year']}_{task_id}.xlsx"
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

    unique_kabs = [r["meta"].get("kabupaten") for r in eval_results if r["meta"].get("kabupaten")]
    unique_kabs = list(dict.fromkeys(unique_kabs))
    reg_title = unique_kabs[0] if len(unique_kabs) == 1 else "Kolektif Publikasi Kecamatan"

    master_excel_fn = f"Evaluasi_Publikasi_KcDA_MASTER_{task_id}.xlsx"
    master_excel_path = os.path.join(OUTPUT_DIR, master_excel_fn)
    generate_master_batch_excel(eval_results, master_excel_path, regency_title=reg_title)

    zip_fn = f"Laporan_Evaluasi_PDF_Kolektif_{task_id}.zip"
    zip_out_path = os.path.join(OUTPUT_DIR, zip_fn)
    create_batch_zip(zip_items, zip_out_path)

    return {
        "success": True,
        "task_id": task_id,
        "regency": "Kolektif Publikasi Kecamatan",
        "total_districts": len(eval_results),
        "total_defects": total_aggregate_defects,
        "total_aggregate_defects": total_aggregate_defects,
        "clean_districts": total_clean_districts,
        "total_clean_districts": total_clean_districts,
        "mismatch_districts": total_mismatch_districts,
        "total_mismatch_districts": total_mismatch_districts,
        "master_excel_download_url": f"/api/download/{master_excel_fn}",
        "zip_download_url": f"/api/download/{zip_fn}",
        "zip_pdf_download_url": f"/api/download/{zip_fn}",
        "districts": eval_results
    }

@app.post("/api/analyze-batch-upload")
async def analyze_batch_upload(
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

    import zipfile
    pdf_paths_to_process = []
    for file_obj in pdf_files:
        fname = file_obj.filename.lower()
        if fname.endswith(".zip"):
            zip_saved_path = os.path.join(UPLOAD_DIR, f"zip_{task_id}_{file_obj.filename}")
            with open(zip_saved_path, "wb") as f:
                shutil.copyfileobj(file_obj.file, f)
            try:
                with zipfile.ZipFile(zip_saved_path, 'r') as zf:
                    for member in zf.namelist():
                        if member.lower().endswith(".pdf") and not member.startswith("__MACOSX") and not os.path.basename(member).startswith("."):
                            extracted_name = f"batch_{task_id}_{os.path.basename(member)}"
                            extracted_path = os.path.join(UPLOAD_DIR, extracted_name)
                            with open(extracted_path, "wb") as out_f, zf.open(member) as in_f:
                                shutil.copyfileobj(in_f, out_f)
                            pdf_paths_to_process.append(extracted_path)
            except Exception as e:
                print(f"[ZIP Upload] Error extracting zip {file_obj.filename}: {e}")
        elif fname.endswith(".pdf"):
            saved_name = f"batch_{task_id}_{file_obj.filename}"
            saved_path = os.path.join(UPLOAD_DIR, saved_name)
            with open(saved_path, "wb") as f:
                shutil.copyfileobj(file_obj.file, f)
            pdf_paths_to_process.append(saved_path)

    for saved_path in pdf_paths_to_process:

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

        pdf_fn = f"Laporan_Evaluasi_{meta['region'].replace(' ', '_')}_{meta['year']}_{task_id}.pdf"
        pdf_out_path = os.path.join(OUTPUT_DIR, pdf_fn)
        generate_pdf_report(meta, defects, pdf_out_path)
        zip_items.append((pdf_out_path, pdf_fn))

        excel_fn = f"Evaluasi_{meta['region'].replace(' ', '_')}_{meta['year']}_{task_id}.xlsx"
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

    if not eval_results:
        raise HTTPException(status_code=400, detail="Tidak ada berkas PDF yang valid untuk diproses.")

    unique_kabs = [r["meta"].get("kabupaten") for r in eval_results if r["meta"].get("kabupaten")]
    unique_kabs = list(dict.fromkeys(unique_kabs))
    reg_title = unique_kabs[0] if len(unique_kabs) == 1 else f"Kolektif ({len(eval_results)} Kecamatan)"

    master_excel_fn = f"Evaluasi_Publikasi_Kolektif_{task_id}.xlsx"
    master_excel_path = os.path.join(OUTPUT_DIR, master_excel_fn)
    generate_master_batch_excel(eval_results, master_excel_path, regency_title=reg_title)

    zip_fn = f"Laporan_Evaluasi_PDF_Kolektif_{task_id}.zip"
    zip_out_path = os.path.join(OUTPUT_DIR, zip_fn)
    create_batch_zip(zip_items, zip_out_path)

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
        "master_excel_download_url": f"/api/download/{master_excel_fn}",
        "zip_download_url": f"/api/download/{zip_fn}",
        "zip_pdf_download_url": f"/api/download/{zip_fn}",
        "districts": eval_results
    }

@app.get("/api/download/{filename}")
async def download_file(filename: str):
    file_path = os.path.join(OUTPUT_DIR, filename)
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="File unduhan tidak ditemukan.")
    
    if filename.lower().endswith(".zip"):
        media_type = "application/zip"
    elif filename.lower().endswith(".pdf"):
        media_type = "application/pdf"
    else:
        media_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

    return FileResponse(
        path=file_path,
        filename=filename,
        media_type=media_type
    )

@app.get("/api/view-pdf/{filename}")
async def view_pdf(filename: str):
    clean_fn = os.path.basename(filename)
    candidate_paths = [
        os.path.join(UPLOAD_DIR, clean_fn),
        os.path.join(SAMPLE_DIR, clean_fn),
        os.path.join(OUTPUT_DIR, clean_fn),
        os.path.join(BASE_DIR, clean_fn)
    ]
    target_path = None
    for cp in candidate_paths:
        if os.path.exists(cp):
            target_path = cp
            break
            
    if not target_path:
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
