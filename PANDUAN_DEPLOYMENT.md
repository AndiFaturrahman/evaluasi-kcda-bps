# 🚀 Panduan Deployment Sistem Evaluasi Publikasi BPS (KCDA)

Repositori ini berisi aplikasi web evaluasi publikasi BPS berbasis **FastAPI** dan **PyMuPDF / OpenCV**.

* **Repository GitHub:** `https://github.com/AndiFaturrahman/evaluasi-kcda-bps`
* **Branch Utama:** `main`
* **Port Standar:** `8000`
* **Entry Point Aplikasi:** `web_app.main:app`

---

## 📋 Spesifikasi Sistem & Dependencies
* **Python:** Versi 3.10 atau 3.11 (disarankan 3.11)
* **Paket Sistem Linux (Ubuntu/Debian):**
  ```bash
  sudo apt-get update && sudo apt-get install -y \
      curl \
      libgl1 \
      libglib2.0-0 \
      libgomp1
  ```
  *(Dibutuhkan untuk library headless OpenCV dan rendering PyMuPDF)*

---

## 🛠️ Pilihan Metode Deployment

### Opsi 1: Menggunakan Docker / Docker Compose (Paling Mudah di VPS)

Jika server VPS IndoGlobal sudah terpasang Docker & Docker Compose:

1. **Clone repositori:**
   ```bash
   git clone https://github.com/AndiFaturrahman/evaluasi-kcda-bps.git
   cd evaluasi-kcda-bps
   ```

2. **Jalankan aplikasi di background:**
   ```bash
   docker compose up -d --build
   ```

3. **Cek status:**
   ```bash
   docker compose ps
   docker compose logs -f
   ```
   Aplikasi langsung aktif di port `8000`.

---

### Opsi 2: Manual di VPS Linux (Ubuntu/Debian) via Systemd & Uvicorn

1. **Clone repositori:**
   ```bash
   git clone https://github.com/AndiFaturrahman/evaluasi-kcda-bps.git /var/www/evaluasi-kcda-bps
   cd /var/www/evaluasi-kcda-bps
   ```

2. **Install paket sistem & Python virtual environment:**
   ```bash
   sudo apt update
   sudo apt install -y python3-pip python3-venv libgl1 libglib2.0-0 libgomp1
   python3 -m venv venv
   source venv/bin/activate
   pip install --upgrade pip
   pip install -r requirements.txt
   ```

3. **Buat service Systemd agar otomatis hidup saat server reboot:**
   ```bash
   sudo nano /etc/systemd/system/evaluasi-bps.service
   ```
   Isi file tersebut dengan:
   ```ini
   [Unit]
   Description=Evaluasi Publikasi BPS Web App
   After=network.target

   [Service]
   User=www-data
   Group=www-data
   WorkingDirectory=/var/www/evaluasi-kcda-bps
   ExecStart=/var/www/evaluasi-kcda-bps/venv/bin/uvicorn web_app.main:app --host 0.0.0.0 --port 8000 --workers 2
   Restart=always
   RestartSec=5
   Environment=PYTHONUNBUFFERED=1

   [Install]
   WantedBy=multi-user.target
   ```

4. **Aktifkan dan jalankan service:**
   ```bash
   sudo chown -R www-data:www-data /var/www/evaluasi-kcda-bps
   sudo systemctl daemon-reload
   sudo systemctl enable evaluasi-bps
   sudo systemctl start evaluasi-bps
   sudo systemctl status evaluasi-bps
   ```

5. **Konfigurasi Reverse Proxy Nginx (Opsional / dengan Domain):**
   ```nginx
   server {
       listen 80;
       server_name evaluasi.bps-wilayah.go.id; # Ganti dengan domain Anda

       location / {
           proxy_pass http://127.0.0.1:8000;
           proxy_set_header Host $host;
           proxy_set_header X-Real-IP $remote_addr;
           proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
           proxy_set_header X-Forwarded-Proto $scheme;
           client_max_body_size 100M;
       }
   }
   ```

---

### Opsi 3: Hosting cPanel IndoGlobal ("Setup Python App")

Jika server IndoGlobal berupa Shared/Cloud Hosting cPanel:
1. Masuk ke cPanel $\rightarrow$ menu **Setup Python App**.
2. Klik **Create Application**:
   * Python Version: Pilih `3.10` atau `3.11`
   * Application root: `evaluasi-kcda-bps`
   * Application URL: pilih domain/subdomain
3. Upload source code atau `git clone` ke direktori tersebut.
4. Buka terminal cPanel, aktifkan environment:
   ```bash
   pip install -r requirements.txt
   ```
5. Buat file `passenger_wsgi.py` (jika menggunakan WSGI adapter) atau jalankan via Uvicorn runner port.

---

## 🔒 Catatan Keamanan & File Permissions
Pastikan direktori berikut memiliki izin tulis (*write permission*):
* `web_app/uploads/`
* `web_app/outputs/`
* `web_app/static/downloads/`
```bash
chmod -R 775 web_app/uploads web_app/outputs web_app/static/downloads
```
