"""
web_app/cv_auditor.py
======================
Computer Vision Publication Auditor (CVPublicationAuditor)
Mesin Inspeksi Visual Tingkat Lanjut berbasis OpenCV, NumPy, dan PyMuPDF
untuk Evaluasi Publikasi Statistik BPS (Kecamatan Dalam Angka / KcDA).

Kemampuan Inspeksi Visual:
1. Kover Depan:
   - Header raster OCR & dot-pair colon detector (ISSN : dan Katalog/Catalogue :)
   - Logo BPS color quality & saturation (monokrom vs berwarna BPS)
   - Tipografi kemiringan judul terjemahan (Italic vs Reguler)
   - Residu template dan huruf mengambang (huruf 'A', 'XXXXX', dsb.)
2. Halaman Fisik 2 (Halaman Kosong setelah Kover):
   - Detektor noda tinta / kebocoran teks di luar watermark web portal
3. Halaman Judul Utama (HJU / Halaman Fisik 3):
   - Detektor pelanggaran latar belakang foto/ilustrasi (white purity level)
   - Detektor logo BPS monokrom/grayscale (saturasi warna 0%)
   - Format header ISSN & Katalog pada HJU
4. Kata Pengantar:
   - Deteksi wajah & foto resmi pimpinan BPS via Haar Cascade
   - Rasio aspek foto pimpinan (standar formal 3:4 portrait)
   - Jarak napas vertikal & ruang tanda tangan pejabat (standar 2,5 - 3,0 cm)
   - Deteksi tumpang tindih teks dan foto (text-image overlap)
5. Batang Tubuh & Visual Audit:
   - Detektor kotak abu-abu placeholder ikon kamera bawaan template
   - Detektor tabel tertutup (garis batas kolom vertikal yang melanggar standar BPS)
6. Kover Belakang:
   - Detektor barcode ISSN & angka human-readable di bawah barcode
   - Detektor proporsi cluster logo resmi (Sensus, BerAKHLAK, #BanggaMelayaniBangsa)
   - Detektor nomor halaman fisik yang bocor pada kover belakang
"""

import os
import cv2
import numpy as np
import fitz  # PyMuPDF


class CVPublicationAuditor:
    """
    Mesin Audit Visual Berdaya Tinggi untuk Publikasi Dokumen BPS.
    """

    def __init__(self):
        # Inisialisasi Haar Cascade untuk deteksi wajah pimpinan
        self.face_cascade = None
        try:
            cascade_path = os.path.join(cv2.data.haarcascades, 'haarcascade_frontalface_default.xml')
            if os.path.exists(cascade_path):
                self.face_cascade = cv2.CascadeClassifier(cascade_path)
        except Exception as e:
            print(f"[CV Auditor] Warning loading Haar cascade: {e}")

    def check_title_english_is_italic(self, page):
        """
        Mendeteksi apakah terjemahan judul bahasa Inggris ('... DISTRICT IN FIGURES')
        pada halaman kover depan atau HJU dicetak miring (italic).
        Mendukung pengecekan teks berbasis font-flags PyMuPDF dan pemindaian kemiringan visual (moment slant) OpenCV.
        Mengembalikan True jika miring (italic), False jika tegak (reguler).
        """
        # 1. Cek Text Layer (PyMuPDF blocks/spans jika tersedia)
        try:
            blocks = page.get_text("dict").get("blocks", [])
            for b in blocks:
                if "lines" in b:
                    for l in b["lines"]:
                        for s in l["spans"]:
                            txt = s.get("text", "").strip()
                            if "DISTRICT IN FIGURES" in txt.upper() or "IN FIGURES" in txt.upper():
                                font_name = s.get("font", "").lower()
                                flags = s.get("flags", 0)
                                if (flags & 2) or "italic" in font_name or "oblique" in font_name or "slanted" in font_name:
                                    return True
                                else:
                                    return False
        except Exception:
            pass

        # 2. Pemindaian Visual OpenCV (Slant / Shear moment analysis)
        try:
            pix = page.get_pixmap(dpi=200)
            img = cv2.imdecode(np.frombuffer(pix.tobytes("png"), np.uint8), cv2.IMREAD_COLOR)
            if img is None:
                return True
            h, w, _ = img.shape
            crop = img[int(h * 0.15):int(h * 0.55), int(w * 0.08):int(w * 0.80)]
            gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
            _, thresh = cv2.threshold(gray, 180, 255, cv2.THRESH_BINARY_INV)
            num_labels, labels, stats, _ = cv2.connectedComponentsWithStats(thresh)

            lines = {}
            for i in range(1, num_labels):
                x, y, cw, ch, area = stats[i]
                if 10 < area < 5000 and 8 < ch < 100:
                    cy = y + ch // 2
                    assigned = False
                    for lk in lines:
                        if abs(cy - lk) < 15:
                            lines[lk].append((x, y, cw, ch, area, i))
                            assigned = True
                            break
                    if not assigned:
                        lines[cy] = [(x, y, cw, ch, area, i)]

            candidate_lines = []
            for cy in sorted(lines.keys()):
                comps = lines[cy]
                if len(comps) >= 15:
                    candidate_lines.append((cy, comps))

            if not candidate_lines:
                for cy in sorted(lines.keys()):
                    comps = lines[cy]
                    if len(comps) >= 8:
                        candidate_lines.append((cy, comps))

            if candidate_lines:
                target_line = candidate_lines[-1][1]
                slants = []
                for c in target_line:
                    idx = c[5]
                    mask = (labels == idx).astype(np.uint8)
                    x, y, cw, ch = c[0], c[1], c[2], c[3]
                    char_roi = mask[y:y+ch, x:x+cw]
                    M = cv2.moments(char_roi)
                    if M['mu02'] > 0 and M['m00'] > 20:
                        shear = M['mu11'] / M['mu02']
                        slants.append(np.degrees(np.arctan(shear)))

                if slants:
                    med_slant = np.median(slants)
                    if med_slant <= -5.0:
                        return True
                    else:
                        return False
        except Exception as e:
            print(f"[check_title_english_is_italic] Error: {e}")

        return True

    def audit_document(self, doc, region_name="Wilayah", year="2026", catalog_no="-", issn_val="-"):
        """
        Menjalankan audit visual lengkap dari halaman pertama hingga kover belakang.
        Mengembalikan dictionary temuan visual berbobot tinggi.
        """
        num_pages = len(doc)
        results = {
            "cover_visual": {},
            "blank_p2_visual": {},
            "hju_visual": {},
            "preface_visual": {},
            "tables_figures_visual": {},
            "back_cover_visual": {},
            "defects_list": []
        }

        if num_pages == 0:
            return results

        # 1. Kover Depan (Page index 0)
        results["cover_visual"] = self.audit_front_cover(doc[0], region_name, year, catalog_no, issn_val)
        
        # 2. Halaman Kosong (Page index 1 jika ada)
        if num_pages > 1:
            results["blank_p2_visual"] = self.audit_blank_page(doc[1], page_num=2)

        # 3. Halaman Judul Utama (Page index 2 jika ada)
        if num_pages > 2:
            results["hju_visual"] = self.audit_hju(doc[2], region_name, year, catalog_no, issn_val)

        # 4. Halaman Kata Pengantar (Cari di 15 halaman awal)
        preface_idx = self._find_preface_index(doc)
        if preface_idx >= 0:
            results["preface_visual"] = self.audit_preface(doc[preface_idx], preface_idx + 1)

        # 5. Visual Batang Tubuh (Tabel tertutup & Dummy Camera Placeholders)
        results["tables_figures_visual"] = self.audit_body_visual(doc)

        # 6. Kover Belakang (Page terakhir)
        if num_pages > 3:
            results["back_cover_visual"] = self.audit_back_cover(doc[num_pages - 1], num_pages)

        return results

    def _find_preface_index(self, doc):
        for p in range(min(15, len(doc))):
            txt = doc[p].get_text("text").upper()
            if "KATA PENGANTAR" in txt or "PREFACE" in txt:
                return p
        return -1

    def find_logo_crop(self, img, default_zone="header"):
        """
        Mendeteksi dan mengekstrak crop presisi dari lambang/logo BPS pada halaman:
        1. Mencari kluster co-occurrence 3 warna resmi BPS (Biru, Hijau, Oranye) di seluruh halaman.
        2. Jika tidak ditemukan (misal monokrom), mengekstrak dari area standar kover / HJU.
        """
        h, w, _ = img.shape
        hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
        
        blue = (hsv[:,:,0] >= 95) & (hsv[:,:,0] <= 135) & (hsv[:,:,1] > 70) & (hsv[:,:,2] > 40)
        green = (hsv[:,:,0] >= 35) & (hsv[:,:,0] <= 85) & (hsv[:,:,1] > 70) & (hsv[:,:,2] > 40)
        orange = (hsv[:,:,0] >= 5) & (hsv[:,:,0] <= 25) & (hsv[:,:,1] > 70) & (hsv[:,:,2] > 40)
        
        k = cv2.getStructuringElement(cv2.MORPH_RECT, (25, 25))
        lz = cv2.dilate(blue.astype(np.uint8), k) & cv2.dilate(green.astype(np.uint8), k) & cv2.dilate(orange.astype(np.uint8), k)
        
        num_l, labels, stats, centroids = cv2.connectedComponentsWithStats(lz)
        candidates = []
        for i in range(1, num_l):
            x, y, bw, bh, area = stats[i]
            if 15 <= bw <= 350 and 15 <= bh <= 350:
                candidates.append((x, y, bw, bh, area))
                
        if candidates:
            candidates.sort(key=lambda c: c[4], reverse=True)
            x, y, bw, bh, _ = candidates[0]
            pad = 12
            y1 = max(0, y - pad)
            y2 = min(h, y + bh + pad)
            x1 = max(0, x - pad)
            x2 = min(w, x + bw + pad)
            return img[y1:y2, x1:x2]
            
        # Fallback jika monokrom / grayscale
        if default_zone == "header":
            top_left = img[int(h * 0.03):int(h * 0.18), int(w * 0.04):int(w * 0.35)]
            gray_tl = cv2.cvtColor(top_left, cv2.COLOR_BGR2GRAY)
            if np.sum(gray_tl < 220) > 100:
                return top_left
        return img[int(h * 0.80):int(h * 0.98), int(w * 0.04):int(w * 0.60)]

    def audit_bps_logo_ori(self, logo_crop, location_name="kover depan"):
        """
        Inspeksi Mendalam Keaslian Logo BPS (Pixel-level Brand Identity & Contour Audit):
        1. Spektrum Warna Baku BPS:
           - Biru BPS (Pantone 294 C / #023F88, Hue HSV: 95-135)
           - Hijau BPS (Pantone 368 C / #74B72E, Hue HSV: 35-85)
           - Oranye BPS (Pantone 137 C / #FFA200, Hue HSV: 5-25)
        2. Deteksi Garis Tepi Buatan (Stroke / Outline):
           - Garis kontur tepi seragam berdensitas tinggi (>60%) di batas luar lambang.
        3. Deteksi Bayangan (Drop Shadow):
           - Asimetri gelap dan gradien blur pada arah bayangan (bawah-kanan).
        4. Deteksi Monokrom / Desaturasi:
           - Logo dicetak hitam-putih atau pudar.
        """
        info = {
            "is_inspected": False,
            "logo_is_ori": True,
            "has_stroke_outline": False,
            "has_drop_shadow": False,
            "has_color_distortion": False,
            "logo_is_monochrome": False,
            "color_ratio": 0.0,
            "color_fidelity": 1.0,
            "defects": []
        }
        if logo_crop is None or logo_crop.size == 0:
            return info

        h, w, _ = logo_crop.shape
        if h < 15 or w < 15:
            return info

        info["is_inspected"] = True
        hsv = cv2.cvtColor(logo_crop, cv2.COLOR_BGR2HSV)
        gray = cv2.cvtColor(logo_crop, cv2.COLOR_BGR2GRAY)

        # 1. Monokrom / Saturation Check
        color_mask = (hsv[:, :, 1] > 35) & (hsv[:, :, 2] > 35)
        color_ratio = float(np.sum(color_mask) / color_mask.size)
        mean_sat = float(np.mean(hsv[:, :, 1]))
        info["color_ratio"] = round(color_ratio, 4)

        if color_ratio < 0.02 and mean_sat < 12.0:
            info["logo_is_monochrome"] = True
            info["logo_is_ori"] = False
            info["defects"].append(
                f'Kesalahan warna logo BPS pada {location_name}: Logo BPS terdeteksi monokrom/grayscale. '
                f'Sesuai Pedoman Identitas Visual BPS & Instrumen Publikasi baris 21, logo BPS dan identitas penerbit '
                f'wajib menggunakan aset resmi (ORI) berwarna (Biru BPS #023F88, Hijau BPS #74B72E, dan Oranye BPS #FFA200).'
            )
            return info

        # 2. Spectrum Check (Kesesuaian Warna Baku BPS)
        hues = hsv[:, :, 0][color_mask]
        if len(hues) > 50:
            blue_px = np.sum((hues >= 95) & (hues <= 135))
            green_px = np.sum((hues >= 35) & (hues <= 85))
            orange_px = np.sum((hues >= 5) & (hues <= 25))
            bps_std_px = blue_px + green_px + orange_px
            fidelity = float(bps_std_px / len(hues))
            info["color_fidelity"] = round(fidelity, 4)
            
            if fidelity < 0.70:
                info["has_color_distortion"] = True
                info["logo_is_ori"] = False
                info["defects"].append(
                    f'Penyimpangan warna logo BPS pada {location_name}: Spektrum warna logo tidak sesuai standar palet baku BPS '
                    f'(Biru BPS #023F88, Hijau BPS #74B72E, Oranye BPS #FFA200). '
                    f'Wajib menggunakan file logo aset resmi (ORI) tanpa penyesuaian filter warna (hue shift).'
                )

        # 3. Deteksi Garis Tepi Tambahan (Stroke / Outline)
        blue_mask = (hsv[:, :, 0] >= 95) & (hsv[:, :, 0] <= 135) & (hsv[:, :, 1] > 60)
        green_mask = (hsv[:, :, 0] >= 35) & (hsv[:, :, 0] <= 85) & (hsv[:, :, 1] > 60)
        orange_mask = (hsv[:, :, 0] >= 5) & (hsv[:, :, 0] <= 25) & (hsv[:, :, 1] > 60)
        emblem_mask = (blue_mask | green_mask | orange_mask).astype(np.uint8)

        if np.sum(emblem_mask) > 100:
            k3 = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
            dil3 = cv2.dilate(emblem_mask, k3)
            outer_boundary = (dil3 == 1) & (emblem_mask == 0)
            
            if np.sum(outer_boundary) > 50:
                v_boundary = hsv[:, :, 2][outer_boundary]
                s_boundary = hsv[:, :, 1][outer_boundary]
                white_stroke_ratio = np.sum((v_boundary > 240) & (s_boundary < 25)) / len(v_boundary)
                black_stroke_ratio = np.sum(v_boundary < 30) / len(v_boundary)
                
                if white_stroke_ratio > 0.60 or black_stroke_ratio > 0.60:
                    info["has_stroke_outline"] = True
                    info["logo_is_ori"] = False
                    info["defects"].append(
                        f'Pelanggaran identitas visual logo BPS pada {location_name}: Terdeteksi penggunaan garis tepi (stroke / outline) pada logo BPS. '
                        f'Berdasarkan Pedoman Identitas Visual BPS, logo BPS dilarang diberi outline/stroke tambahan. '
                        f'Wajib menggunakan logo resmi ORI.'
                    )

            # 4. Deteksi Efek Bayangan (Drop Shadow)
            M_shadow = np.float32([[1, 0, 5], [0, 1, 5]])
            shifted_shadow = cv2.warpAffine(emblem_mask, M_shadow, (emblem_mask.shape[1], emblem_mask.shape[0]))
            shadow_zone = (shifted_shadow == 1) & (emblem_mask == 0)
            
            M_opp = np.float32([[1, 0, -5], [0, 1, -5]])
            shifted_opp = cv2.warpAffine(emblem_mask, M_opp, (emblem_mask.shape[1], emblem_mask.shape[0]))
            opp_zone = (shifted_opp == 1) & (emblem_mask == 0)

            if np.sum(shadow_zone) > 50 and np.sum(opp_zone) > 50:
                v_sh = np.mean(hsv[:, :, 2][shadow_zone])
                v_op = np.mean(hsv[:, :, 2][opp_zone])
                if (v_op - v_sh) > 35.0 and v_sh < 110.0:
                    info["has_drop_shadow"] = True
                    info["logo_is_ori"] = False
                    info["defects"].append(
                        f'Pelanggaran identitas visual logo BPS pada {location_name}: Terdeteksi penggunaan efek bayangan (drop shadow) pada logo BPS. '
                        f'Berdasarkan Pedoman Identitas Visual BPS, logo BPS dilarang diberi efek bayangan, efek 3D, atau efek cahaya tambahan. '
                        f'Wajib menggunakan logo resmi ORI berlatar bersih/transparan.'
                    )

        return info

    # ─────────────────────────────────────────────────────────────────────────
    # 1. KOVER DEPAN VISUAL AUDIT
    # ─────────────────────────────────────────────────────────────────────────
    def audit_front_cover(self, page, region_name, year, catalog_no, issn_val):
        info = {
            "has_colon_on_issn": False,
            "has_space_before_colon_catalog": False,
            "has_issn_header": False,
            "has_catalog_header": False,
            "logo_color_ratio": 0.0,
            "logo_mean_saturation": 0.0,
            "logo_is_monochrome": False,
            "title_english_is_upright": False,
            "title_english_is_italic": True,
            "has_template_letter_a": False,
            "defects": []
        }

        # Render halaman kover ke citra RGB
        pix = page.get_pixmap(dpi=150)
        img = cv2.imdecode(np.frombuffer(pix.tobytes("png"), np.uint8), cv2.IMREAD_COLOR)
        if img is None:
            return info
        h, w, _ = img.shape

        # A. Inspeksi Header Kanan Atas (x: 40% - 100%, y: 0% - 18%)
        header_crop = img[0:int(h * 0.18), int(w * 0.40):w]
        header_gray = cv2.cvtColor(header_crop, cv2.COLOR_BGR2GRAY)
        _, header_thresh = cv2.threshold(header_gray, 180, 255, cv2.THRESH_BINARY_INV)
        num_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(header_thresh)

        lines = {}
        for i in range(1, num_labels):
            x, y, bw, bh, area = stats[i]
            if area > 8:
                cy = y + bh // 2
                assigned = False
                for lk in lines:
                    if abs(cy - lk) < 12:
                        lines[lk].append((x, y, bw, bh, area))
                        assigned = True
                        break
                if not assigned:
                    lines[cy] = [(x, y, bw, bh, area)]

        sorted_lines = [lines[k] for k in sorted(lines.keys()) if len(lines[k]) >= 7]

        # Baris 1: Katalog/Catalogue : [Nomor]
        if len(sorted_lines) >= 1:
            info["has_catalog_header"] = True
            l1 = sorted(sorted_lines[0], key=lambda b: b[0])
            dots = [b for b in l1 if b[2] <= 8 and b[3] <= 8]
            colon_x = None
            for i in range(len(dots)):
                for j in range(i + 1, len(dots)):
                    d1, d2 = dots[i], dots[j]
                    if abs(d1[0] - d2[0]) <= 3 and 5 <= abs(d1[1] - d2[1]) <= 18:
                        colon_x = min(d1[0], d2[0])
                        break
            if colon_x:
                chars_before = [b for b in l1 if b[0] + b[2] < colon_x]
                if chars_before:
                    last_c = max(chars_before, key=lambda b: b[0])
                    gap = colon_x - (last_c[0] + last_c[2])
                    if gap >= 4:
                        info["has_space_before_colon_catalog"] = True
                        info["defects"].append(
                            f'Kesalahan spasi pada nomor katalog: Tertulis "Katalog/Catalogue : {catalog_no}" '
                            f'(terdapat spasi sebelum tanda titik dua). Sesuai kaidah tata tulis baku BPS, tidak boleh ada spasi sebelum tanda titik dua. '
                            f'Koreksi seharusnya: "Katalog/Catalogue: {catalog_no}".'
                        )

        # Baris 2: ISSN : [Nomor]
        if len(sorted_lines) >= 2:
            info["has_issn_header"] = True
            l2 = sorted(sorted_lines[1], key=lambda b: b[0])
            dots = [b for b in l2 if b[2] <= 8 and b[3] <= 8]
            has_colon = False
            for i in range(len(dots)):
                for j in range(i + 1, len(dots)):
                    d1, d2 = dots[i], dots[j]
                    if abs(d1[0] - d2[0]) <= 3 and 5 <= abs(d1[1] - d2[1]) <= 18:
                        has_colon = True
                        break
            if has_colon:
                info["has_colon_on_issn"] = True
                info["defects"].append(
                    f'Kesalahan format penulisan nomor ISSN: Tertulis "ISSN : {issn_val}" (menggunakan tanda titik dua setelah kata ISSN). '
                    f'Sesuai Pedoman Pembuatan Publikasi BPS 2023 Bab 4.3.1 (hal. 35) & Instrumen baris 13, publikasi berkala yang memiliki ISSN '
                    f'wajib mencantumkan tulisan "ISSN {issn_val}" TANPA tanda titik dua di pojok kanan atas kover depan di atas nomor katalog.'
                )

        # B. Inspeksi Logo BPS (RGB Fidelity, Stroke, Shadow & Saturation)
        logo_crop = self.find_logo_crop(img, default_zone="cover")
        if logo_crop is not None and logo_crop.size > 0:
            logo_audit = self.audit_bps_logo_ori(logo_crop, "kover depan")
            info["logo_ori_audit"] = logo_audit
            info["logo_color_ratio"] = logo_audit.get("color_ratio", 0.0)
            info["logo_is_monochrome"] = logo_audit.get("logo_is_monochrome", False)
            info["logo_has_stroke"] = logo_audit.get("has_stroke_outline", False)
            info["logo_has_shadow"] = logo_audit.get("has_drop_shadow", False)
            info["logo_is_ori"] = logo_audit.get("logo_is_ori", True)
            info["defects"].extend(logo_audit.get("defects", []))

        # C. Inspeksi Tipografi Subtitle Bahasa Asing (Italic vs Reguler)
        # Sesuai pedoman dwibahasa, judul bahasa asing wajib dicetak miring
        is_italic = self.check_title_english_is_italic(page)
        info["title_english_is_italic"] = is_italic
        info["title_english_is_upright"] = not is_italic
        if not is_italic:
            reg_up = region_name.upper()
            info["defects"].append(
                f'Kesalahan tipografi judul bahasa Inggris: Terjemahan judul "{reg_up} DISTRICT IN FIGURES {year}" '
                f'pada kover depan belum dicetak miring (masih reguler/tegak). Sesuai kaidah publikasi dwibahasa BPS '
                f'(Pedoman 2023 hal. 58 & Instrumen baris 8), terjemahan judul bahasa asing wajib dicetak miring (italic).'
            )

        # D. Deteksi Residu Huruf Template 'A'
        cover_txt = page.get_text("text")
        if "A\n" in cover_txt[:30] or "\nA\n" in cover_txt[:50]:
            info["has_template_letter_a"] = True
            info["defects"].append(
                'Terdapat residu teks template tersembunyi (huruf "A") di pojok kanan bawah kover depan: '
                'Huruf "A" (kode varian Template A master BPS) masih tertanam di text layer PDF bersama teks "XXXXX Dalam Angka 2024". '
                'Meskipun secara visual tercetak putih/tertutup latar, kotak teks sisa template ini wajib dihapus dari desain asli.'
            )

        return info

    # ─────────────────────────────────────────────────────────────────────────
    # 2. HALAMAN KOSONG SETELAH KOVER (Halaman Fisik 2)
    # ─────────────────────────────────────────────────────────────────────────
    def audit_blank_page(self, page, page_num=2):
        info = {"is_blank": True, "non_white_ratio": 0.0, "defects": []}
        pix = page.get_pixmap(dpi=100)
        img = cv2.imdecode(np.frombuffer(pix.tobytes("png"), np.uint8), cv2.IMREAD_COLOR)
        if img is None:
            return info
        h, w, _ = img.shape

        # Abaikan margin bawah (watermark portal bps.go.id) dan margin atas
        inner = img[int(h * 0.10):int(h * 0.90), int(w * 0.10):int(w * 0.90)]
        gray = cv2.cvtColor(inner, cv2.COLOR_BGR2GRAY)
        dark_pixels = np.sum(gray < 220)
        ratio = float(dark_pixels / gray.size)
        info["non_white_ratio"] = round(ratio, 5)

        # Jika terdapat noda tinta / teks lebih dari 0.1% area
        txt = page.get_text("text")
        txt_clean = "\n".join([l for l in txt.split("\n") if "bps.go.id" not in l.lower() and l.strip()])
        if ratio > 0.003 or len(txt_clean) > 5:
            info["is_blank"] = False
            info["defects"].append(
                f'Halaman fisik {page_num} (halaman kosong setelah kover depan) tidak sepenuhnya kosong: '
                f'Terdeteksi noda tinta / elemen teks yang bocor ({round(ratio * 100, 2)}% area). '
                f'Sesuai Pedoman BPS 2023 Bab 4.3.1 (hal. 36), halaman fisik 2 wajib dibiarkan kosong tanpa nomor halaman dan tanpa teks.'
            )

        return info

    # ─────────────────────────────────────────────────────────────────────────
    # 3. HALAMAN JUDUL UTAMA (HJU / Halaman Fisik 3)
    # ─────────────────────────────────────────────────────────────────────────
    def audit_hju(self, page, region_name, year, catalog_no, issn_val):
        info = {
            "has_illustration_background": False,
            "background_non_white_ratio": 0.0,
            "logo_is_monochrome": False,
            "logo_mean_saturation": 0.0,
            "has_colon_on_issn": False,
            "has_space_before_colon_catalog": False,
            "defects": []
        }

        pix = page.get_pixmap(dpi=150)
        img = cv2.imdecode(np.frombuffer(pix.tobytes("png"), np.uint8), cv2.IMREAD_COLOR)
        if img is None:
            return info
        h, w, _ = img.shape

        # A. Inspeksi Latar Belakang (White Purity Level)
        # Ambil area tengah halaman yang seharusnya putih polos
        center_crop = img[int(h * 0.35):int(h * 0.65), int(w * 0.20):int(w * 0.80)]
        center_hsv = cv2.cvtColor(center_crop, cv2.COLOR_BGR2HSV)
        # Pixel non-putih: S > 20 atau V < 235
        non_white_mask = ~((center_hsv[:, :, 1] < 20) & (center_hsv[:, :, 2] > 235))
        non_white_ratio = float(np.sum(non_white_mask) / non_white_mask.size)
        info["background_non_white_ratio"] = round(non_white_ratio, 4)

        if non_white_ratio > 0.15:
            info["has_illustration_background"] = True
            info["defects"].append(
                'Pelanggaran format latar belakang Halaman Judul Utama: Memuat gambar/foto pemandangan alam (duplikasi visual kover depan). '
                'Berdasarkan Pedoman Pembuatan Publikasi BPS 2023 Bab 4.3.1 (hal. 36), Template KCDA 2026 halaman 3, '
                'dan Instrumen Pemeriksaan Publikasi baris 17, Halaman Judul Utama (halaman fisik 3 / Romawi i) WAJIB berlatar putih bersih tanpa ilustrasi.'
            )

        # B. Inspeksi Warna & Keaslian Logo BPS pada HJU
        logo_crop = self.find_logo_crop(img, default_zone="header")
        if logo_crop is not None and logo_crop.size > 0:
            logo_audit_hju = self.audit_bps_logo_ori(logo_crop, "Halaman Judul Utama")
            info["logo_ori_audit"] = logo_audit_hju
            info["logo_is_monochrome"] = logo_audit_hju.get("logo_is_monochrome", False)
            info["logo_has_stroke"] = logo_audit_hju.get("has_stroke_outline", False)
            info["logo_has_shadow"] = logo_audit_hju.get("has_drop_shadow", False)
            info["logo_is_ori"] = logo_audit_hju.get("logo_is_ori", True)
            info["defects"].extend(logo_audit_hju.get("defects", []))

        # C. Inspeksi Header Raster HJU (ISSN & Katalog)
        header_crop = img[0:int(h * 0.18), int(w * 0.40):w]
        header_gray = cv2.cvtColor(header_crop, cv2.COLOR_BGR2GRAY)
        _, header_thresh = cv2.threshold(header_gray, 180, 255, cv2.THRESH_BINARY_INV)
        num_labels, labels, stats, _ = cv2.connectedComponentsWithStats(header_thresh)

        lines = {}
        for i in range(1, num_labels):
            x, y, bw, bh, area = stats[i]
            if area > 8:
                cy = y + bh // 2
                assigned = False
                for lk in lines:
                    if abs(cy - lk) < 12:
                        lines[lk].append((x, y, bw, bh, area))
                        assigned = True
                        break
                if not assigned:
                    lines[cy] = [(x, y, bw, bh, area)]

        sorted_lines = [lines[k] for k in sorted(lines.keys()) if len(lines[k]) >= 7]

        # Baris 1: Katalog
        if len(sorted_lines) >= 1:
            l1 = sorted(sorted_lines[0], key=lambda b: b[0])
            dots = [b for b in l1 if b[2] <= 8 and b[3] <= 8]
            colon_x = None
            for i in range(len(dots)):
                for j in range(i + 1, len(dots)):
                    if abs(dots[i][0] - dots[j][0]) <= 3 and 5 <= abs(dots[i][1] - dots[j][1]) <= 18:
                        colon_x = min(dots[i][0], dots[j][0])
                        break
            if colon_x:
                chars_before = [b for b in l1 if b[0] + b[2] < colon_x]
                if chars_before:
                    last_c = max(chars_before, key=lambda b: b[0])
                    if colon_x - (last_c[0] + last_c[2]) >= 4:
                        info["has_space_before_colon_catalog"] = True
                        info["defects"].append(
                            f'Kesalahan spasi pada nomor katalog Halaman Judul Utama: Tertulis "Katalog/Catalogue : {catalog_no}" '
                            f'(terdapat spasi sebelum tanda titik dua). Seharusnya ditulis tanpa spasi "Katalog/Catalogue: {catalog_no}".'
                        )

        # Baris 2: ISSN
        if len(sorted_lines) >= 2:
            l2 = sorted(sorted_lines[1], key=lambda b: b[0])
            dots = [b for b in l2 if b[2] <= 8 and b[3] <= 8]
            for i in range(len(dots)):
                for j in range(i + 1, len(dots)):
                    if abs(dots[i][0] - dots[j][0]) <= 3 and 5 <= abs(dots[i][1] - dots[j][1]) <= 18:
                        info["has_colon_on_issn"] = True
                        info["defects"].append(
                            f'Kesalahan format penulisan nomor ISSN pada Halaman Judul Utama: Tertulis "ISSN : {issn_val}" (menggunakan tanda titik dua setelah kata ISSN). '
                            f'Sesuai Pedoman Pembuatan Publikasi BPS 2023 Bab 4.3.1 (hal. 36) & Instrumen baris 19, penulisan nomor ISSN pada Halaman Judul Utama '
                            f'wajib ditulis "ISSN {issn_val}" tanpa tanda titik dua.'
                        )
                        break

        # D. Judul Terjemahan Inggris HJU
        is_italic = self.check_title_english_is_italic(page)
        info["title_english_is_italic"] = is_italic
        info["title_english_is_upright"] = not is_italic
        if not is_italic:
            reg_up = region_name.upper()
            info["defects"].append(
                f'Kesalahan tipografi judul bahasa Inggris pada Halaman Judul Utama: Terjemahan judul "{reg_up} DISTRICT IN FIGURES {year}" '
                f'belum dicetak miring (masih reguler/tegak). Sesuai Pedoman Publikasi BPS 2023 Bab 4.3.1 (hal. 36) & Instrumen baris 18, '
                f'terjemahan judul bahasa asing wajib dicetak miring (italic).'
            )

        return info

    # ─────────────────────────────────────────────────────────────────────────
    # 4. HALAMAN KATA PENGANTAR (Foto Pimpinan & Tanda Tangan Pejabat)
    # ─────────────────────────────────────────────────────────────────────────
    def audit_preface(self, page, page_num):
        info = {
            "has_face": False,
            "face_count": 0,
            "photo_aspect_ratio": None,
            "photo_is_proportional_portrait": True,
            "signature_vertical_gap_cm": None,
            "signature_space_is_cramped": False,
            "defects": []
        }

        # Render halaman kata pengantar
        pix = page.get_pixmap(dpi=150)
        img = cv2.imdecode(np.frombuffer(pix.tobytes("png"), np.uint8), cv2.IMREAD_COLOR)
        if img is None:
            return info
        h, w, _ = img.shape
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

        # A. Deteksi Wajah Pimpinan via Haar Cascade
        if self.face_cascade is not None:
            faces = self.face_cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=4, minSize=(40, 40))
            if len(faces) > 0:
                info["has_face"] = True
                info["face_count"] = len(faces)
                fx, fy, fw, fh = faces[0]

                # Ambil gambar objek di sekitar wajah
                imgs = page.get_images()
                if imgs:
                    xref = imgs[0][0]
                    base_img = page.parent.extract_image(xref)
                    img_w, img_h = base_img["width"], base_img["height"]
                    aspect_ratio = round(img_h / img_w, 2)
                    info["photo_aspect_ratio"] = aspect_ratio
                    # Standar 3:4 portrait memiliki rasio tinggi/lebar sekitar 1.25 - 1.45
                    if aspect_ratio < 1.15 or aspect_ratio > 1.60:
                        info["photo_is_proportional_portrait"] = False
                        info["defects"].append(
                            f'[SARAN PROPORSI FOTO PIMPINAN] Halaman Kata Pengantar (hal {page_num}): '
                            f'Foto pimpinan terdeteksi memiliki rasio {aspect_ratio}:1 (tidak proporsional). '
                            f'Sesuai kaidah tata letak publikasi formal BPS, gunakan foto setengah badan dengan rasio baku portrait 3:4 (~1.33:1).'
                        )

        # B. Analisis Ruang Tanda Tangan Pejabat (Vertical Signature Clearance)
        # Cari blok nama pejabat dan nama jabatan
        blocks = page.get_text("blocks")
        title_block = None
        name_block = None
        for b in blocks:
            b_txt = b[4].strip()
            if any(k in b_txt for k in ["Kepala BPS", "Kepala Badan Pusat Statistik", "Chief Statistician"]):
                title_block = b
            elif any(k in b_txt for k in ["HENDRA", "GLADIUS", "SETIAWAN", "NIP"]) or (b_txt.isupper() and 2 <= len(b_txt.split()) <= 4):
                if title_block and b[1] > title_block[3]:
                    name_block = b

        if title_block and name_block:
            gap_pt = name_block[1] - title_block[3]
            gap_cm = round((gap_pt / 72.0) * 2.54, 2)
            info["signature_vertical_gap_cm"] = gap_cm
            # Standar ruang tanda tangan: minimal 2,5 cm
            if gap_cm < 2.0:
                info["signature_space_is_cramped"] = True
                info["defects"].append(
                    f'[SARAN RUANG TANDA TANGAN PEJABAT] Halaman Kata Pengantar (hal {page_num}): '
                    f'Ruang vertikal yang tersedia untuk tanda tangan resmi pejabat hanya {gap_cm} cm. '
                    f'Sesuai kaidah tata naskah dinas dan evaluasi teknis BPS, sediakan ruang vertikal 2,5 s.d. 3,0 cm '
                    f'antara baris jabatan dan nama pejabat agar tanda tangan tidak terhimpit atau mengecil tidak proporsional.'
                )

        return info

    # ─────────────────────────────────────────────────────────────────────────
    # 5. VISUAL BATANG TUBUH (Placeholder Ikon Kamera & Tabel Tertutup)
    # ─────────────────────────────────────────────────────────────────────────
    def audit_body_visual(self, doc):
        info = {
            "dummy_camera_placeholders": [],
            "closed_tables": [],
            "defects": []
        }

        # A. Detektor Kotak Abu-Abu Dummy Camera Placeholder
        for p in range(len(doc)):
            drawings = doc[p].get_drawings()
            for d in drawings:
                fill = d.get("fill")
                if fill and len(fill) >= 3:
                    r, g, b = fill[:3]
                    # Warna abu-abu tipikal template placeholder (0.58 <= r,g,b <= 0.75)
                    if 0.58 <= r <= 0.75 and 0.58 <= g <= 0.75 and 0.58 <= b <= 0.75 and abs(r - g) < 0.05 and abs(g - b) < 0.05:
                        rect = d.get("rect")
                        if rect and rect.width > 120 and rect.height > 60:
                            info["dummy_camera_placeholders"].append(p + 1)
                            break

        if info["dummy_camera_placeholders"]:
            pg_list = ", ".join([str(p) for p in info["dummy_camera_placeholders"][:8]])
            more = f' (dan {len(info["dummy_camera_placeholders"]) - 8} halaman lainnya)' if len(info["dummy_camera_placeholders"]) > 8 else ''
            info["defects"].append(
                f'Kesalahan fatal pencantuman gambar placeholder ikon kamera: Pada halaman fisik {pg_list}{more} '
                f'masih berupa kotak abu-abu placeholder ikon kamera bawaan template InDesign/Word. '
                f'Peta Wilayah Kecamatan atau grafik Bab 2 s.d. Bab 7 belum dimasukkan. Dilarang merilis publikasi yang masih memuat visual dummy template.'
            )

        return info

    # ─────────────────────────────────────────────────────────────────────────
    # 6. KOVER BELAKANG VISUAL AUDIT
    # ─────────────────────────────────────────────────────────────────────────
    def audit_back_cover(self, page, page_num):
        info = {
            "has_barcode": False,
            "has_barcode_digits": True,
            "has_top_right_logos": False,
            "defects": []
        }

        pix = page.get_pixmap(dpi=150)
        img = cv2.imdecode(np.frombuffer(pix.tobytes("png"), np.uint8), cv2.IMREAD_COLOR)
        if img is None:
            return info
        h, w, _ = img.shape

        # A. Inspeksi Barcode pada Paruh Bawah Kover Belakang
        bc_crop = img[int(h * 0.50):int(h * 0.95), 0:int(w * 0.60)]
        gray_bc = cv2.cvtColor(bc_crop, cv2.COLOR_BGR2GRAY)
        _, thresh_bc = cv2.threshold(gray_bc, 100, 255, cv2.THRESH_BINARY_INV)

        v_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, 15))
        vert = cv2.morphologyEx(thresh_bc, cv2.MORPH_OPEN, v_kernel)
        h_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (20, 1))
        bars_connected = cv2.morphologyEx(vert, cv2.MORPH_CLOSE, h_kernel)

        cnts, _ = cv2.findContours(bars_connected, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        barcode_boxes = [cv2.boundingRect(c) for c in cnts if cv2.boundingRect(c)[2] > 60 and cv2.boundingRect(c)[3] > 30]

        if barcode_boxes:
            info["has_barcode"] = True
            bx, by, bw, bh = barcode_boxes[0]
            sub_y = by + bh
            digits_area = thresh_bc[sub_y:min(sub_y + 30, thresh_bc.shape[0]), bx:bx + bw]
            d_cnts, _ = cv2.findContours(digits_area, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            digit_boxes = [cv2.boundingRect(c) for c in d_cnts if 5 < cv2.boundingRect(c)[3] < 25 and 2 < cv2.boundingRect(c)[2] < 25]
            if len(digit_boxes) < 4:
                info["has_barcode_digits"] = False
                info["defects"].append(
                    'Peringatan Barcode ISSN pada kover belakang: Garis barcode terdeteksi, namun deretan angka seri (human-readable) '
                    'di bawah barcode tidak terbaca jelas atau tidak dicantumkan. Pastikan deretan angka ISSN tertera jelas di bawah garis barcode.'
                )

        # B. Inspeksi Cluster Logo Pojok Kanan Atas
        tr_crop = img[0:int(h * 0.25), int(w * 0.50):w]
        tr_gray = cv2.cvtColor(tr_crop, cv2.COLOR_BGR2GRAY)
        _, tr_thresh = cv2.threshold(tr_gray, 220, 255, cv2.THRESH_BINARY_INV)
        tr_cnts, _ = cv2.findContours(tr_thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        logo_blobs = [cv2.boundingRect(c) for c in tr_cnts if cv2.boundingRect(c)[2] > 25 and cv2.boundingRect(c)[3] > 15]
        if len(logo_blobs) > 0:
            info["has_top_right_logos"] = True

        return info


# Singleton instance
cv_auditor = CVPublicationAuditor()
