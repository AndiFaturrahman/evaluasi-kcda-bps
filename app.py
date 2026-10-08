import os
import sys
import uvicorn
import gradio as gr

# Setup import paths
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)
WEB_APP_DIR = os.path.join(BASE_DIR, "web_app")
if WEB_APP_DIR not in sys.path:
    sys.path.insert(0, WEB_APP_DIR)

from web_app.main import app

# Create a clean Gradio interface mounted at /gradio to satisfy the Gradio Space runtime
with gr.Blocks(title="Sistem Evaluasi Publikasi KCDA BPS") as demo:
    gr.Markdown("# 📊 Sistem Evaluasi Publikasi KCDA BPS")
    gr.HTML('''
        <div style="padding: 24px; text-align: center; font-family: sans-serif; background: #f8fafc; border-radius: 12px; border: 1px solid #e2e8f0; margin-top: 16px;">
            <h2 style="color: #1e3a8a; margin-bottom: 8px;">Aplikasi Evaluasi Publikasi KCDA BPS Berhasil Berjalan!</h2>
            <p style="color: #475569; font-size: 15px; margin-bottom: 20px;">
                Gunakan Dashboard Utama untuk mengunggah PDF, evaluasi batch (ZIP), dan ekspor laporan otomatis ke Excel & PDF.
            </p>
            <a href="/" target="_self" style="display: inline-block; padding: 12px 28px; background: #2563eb; color: #ffffff; border-radius: 8px; text-decoration: none; font-weight: 600; font-size: 15px; box-shadow: 0 4px 6px -1px rgba(37, 99, 235, 0.2);">
                🚀 Buka Dashboard Utama (Layar Penuh)
            </a>
        </div>
    ''')

# Mount Gradio onto the existing FastAPI application
app = gr.mount_gradio_app(app, demo, path="/gradio")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 7860))
    uvicorn.run("app:app", host="0.0.0.0", port=port, reload=False)
