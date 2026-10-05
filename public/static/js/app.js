/**
 * Sistem Evaluasi Publikasi BPS (KcDA / KDA 2026)
 * Client-side Controller & Dynamic UI Interactions
 */

document.addEventListener('DOMContentLoaded', () => {
    // ── 0. THEME SWITCHER (DARK / LIGHT PUTIH-OREN) ──
    const btnThemeToggle = document.getElementById('btn-theme-toggle');
    const themeIcon = document.getElementById('theme-icon');
    const themeText = document.getElementById('theme-text');

    function applyTheme(theme) {
        document.documentElement.setAttribute('data-theme', theme);
        try {
            localStorage.setItem('bps_theme', theme);
        } catch (e) {}

        if (btnThemeToggle && themeIcon && themeText) {
            if (theme === 'light') {
                themeIcon.textContent = '🌙';
                themeText.textContent = 'Mode Gelap';
                btnThemeToggle.setAttribute('title', 'Beralih ke Mode Gelap');
            } else {
                themeIcon.textContent = '☀️';
                themeText.textContent = 'Mode Terang';
                btnThemeToggle.setAttribute('title', 'Beralih ke Mode Terang (Putih-Oren)');
            }
        }
    }

    const currentTheme = document.documentElement.getAttribute('data-theme') || 'dark';
    applyTheme(currentTheme);

    if (btnThemeToggle) {
        btnThemeToggle.addEventListener('click', () => {
            const activeTheme = document.documentElement.getAttribute('data-theme') || 'dark';
            const nextTheme = (activeTheme === 'light') ? 'dark' : 'light';
            applyTheme(nextTheme);
            showToast(nextTheme === 'light' ? 'Mode Terang (Putih-Oren BPS) Aktif ☀️' : 'Mode Gelap Aktif 🌙', 'info', 2000);
        });
    }

    // ── CEGAH BROWSER MEMBUKA PDF SAAT DRAG-DROP DI LUAR KOTAK ──
    ['dragenter', 'dragover', 'dragleave', 'drop'].forEach(name => {
        window.addEventListener(name, (e) => {
            e.preventDefault();
        }, false);
    });

    window.addEventListener('drop', (e) => {
        e.preventDefault();
        if (e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files.length > 0) {
            handlePdfsSelected(e.dataTransfer.files);
        }
    });

    // ── DOM ELEMENTS ──
    const btnOpenGuide = document.getElementById('btn-open-guide');
    const btnCloseGuide = document.getElementById('btn-close-guide');
    const guideModal = document.getElementById('guide-modal');

    const lanUrlCode = document.getElementById('lan-url');
    const lanPill = document.getElementById('lan-pill');

    const dropzone = document.getElementById('dropzone');
    const btnTriggerFile = document.getElementById('btn-trigger-file');
    const pdfInput = document.getElementById('pdf-input');
    const excelInput = document.getElementById('excel-input');
    const apiKeyInput = document.getElementById('api-key-input');
    const btnAnalyze = document.getElementById('btn-analyze-upload');
    const btnInstantAnalyze = document.getElementById('btn-instant-analyze');

    const fileChosen = document.getElementById('file-chosen');
    const chosenFileName = document.getElementById('chosen-file-name');
    const chosenFileSize = document.getElementById('chosen-file-size');
    const btnRemoveFile = document.getElementById('btn-remove-file');

    const btnToggleSettings = document.getElementById('btn-toggle-settings');
    const settingsContent = document.getElementById('settings-content');
    const settingsArrow = document.getElementById('settings-arrow');

    const progressCard = document.getElementById('progress-card');
    const resultsContainer = document.getElementById('results-container');

    const auditBadgeCard = document.getElementById('audit-badge-card');
    const auditBadgeIcon = document.getElementById('audit-badge-icon');
    const auditBadgeTitle = document.getElementById('audit-badge-title');
    const auditBadgeCaption = document.getElementById('audit-badge-caption');
    const auditBadgeCount = document.getElementById('audit-badge-count');

    const statTotalDefects = document.getElementById('stat-total-defects');
    const statCleanSections = document.getElementById('stat-clean-sections');
    const statDummyImages = document.getElementById('stat-dummy-images');
    const statISSNConsistency = document.getElementById('stat-issn-consistency');
    const statISSNSub = document.getElementById('stat-issn-sub');

    const metaTitle = document.getElementById('meta-title');
    const metaRegion = document.getElementById('meta-region');
    const metaYear = document.getElementById('meta-year');
    const metaCatalog = document.getElementById('meta-catalog');
    const metaIssn = document.getElementById('meta-issn');
    const metaPages = document.getElementById('meta-pages');

    const defectSearch = document.getElementById('defect-search');

    const btnToggleAll = document.getElementById('btn-toggle-all');
    const toggleAllText = document.getElementById('toggle-all-text');
    const btnCopyAll = document.getElementById('btn-copy-all');
    const sectionsWrapper = document.getElementById('sections-wrapper');

    const btnDownloadPdf = document.getElementById('btn-download-pdf');
    const btnDownloadExcel = document.getElementById('btn-download-excel');
    const btnResetAudit = document.getElementById('btn-reset-audit');
    const toast = document.getElementById('toast');

    // ── STATE ──
    let selectedPdfFiles = [];
    let selectedPdfFile = null;
    let currentAnalysisData = null;
    let currentBatchData = null;
    let isAllCollapsed = false;

    // ── TOAST NOTIFICATION ──
    let toastTimeout = null;
    function showToast(message, type = 'info', duration = 3000) {
        if (!toast) return;
        clearTimeout(toastTimeout);
        toast.textContent = message;
        toast.className = `toast-notification toast-${type}`;
        toast.style.display = 'block';

        toastTimeout = setTimeout(() => {
            toast.style.display = 'none';
        }, duration);
    }

    // ── 1. SYSTEM INFO & LAN IP ──
    fetch('/api/system-info')
        .then(r => r.json())
        .then(data => {
            if (data.lan_url && lanUrlCode) {
                lanUrlCode.textContent = data.lan_url;
            }
        })
        .catch(err => console.warn('Gagal membaca info jaringan:', err));

    if (lanPill) {
        lanPill.addEventListener('click', () => {
            const url = lanUrlCode ? lanUrlCode.textContent.trim() : window.location.host;
            const fullUrl = url.startsWith('http') ? url : `http://${url}`;
            navigator.clipboard.writeText(fullUrl).then(() => {
                showToast(`✓ Tautan LAN tersalin: ${fullUrl}`, 'success');
            }).catch(() => {
                showToast(`Salin manual: ${fullUrl}`, 'info');
            });
        });
    }

    // ── 2. STANDARDS GUIDE MODAL ──
    if (btnOpenGuide && guideModal) {
        btnOpenGuide.addEventListener('click', () => {
            guideModal.style.display = 'flex';
        });
    }

    if (btnCloseGuide && guideModal) {
        btnCloseGuide.addEventListener('click', () => {
            guideModal.style.display = 'none';
        });
    }

    if (guideModal) {
        guideModal.addEventListener('click', (e) => {
            if (e.target === guideModal) {
                guideModal.style.display = 'none';
            }
        });

        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape' && guideModal.style.display === 'flex') {
                guideModal.style.display = 'none';
            }
        });
    }

    // ── 3. ADVANCED SETTINGS ACCORDION ──
    if (btnToggleSettings && settingsContent) {
        btnToggleSettings.addEventListener('click', () => {
            const isHidden = settingsContent.style.display === 'none' || !settingsContent.style.display;
            settingsContent.style.display = isHidden ? 'block' : 'none';
            if (settingsArrow) {
                settingsArrow.textContent = isHidden ? '▲' : '▼';
            }
        });
    }

    // ── 4. FILE SELECTION & DROPZONE ──
    if (dropzone) {
        dropzone.addEventListener('click', (e) => {
            // Hindari double click jika target adalah label tombol
            if (e.target !== btnTriggerFile && !btnTriggerFile.contains(e.target)) {
                if (pdfInput) pdfInput.click();
            }
        });

        dropzone.addEventListener('dragover', (e) => {
            e.preventDefault();
            dropzone.classList.add('dragover');
        });

        dropzone.addEventListener('dragleave', () => {
            dropzone.classList.remove('dragover');
        });

        dropzone.addEventListener('drop', (e) => {
            e.preventDefault();
            dropzone.classList.remove('dragover');
            if (e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files.length > 0) {
                handlePdfsSelected(e.dataTransfer.files);
            }
        });
    }

    if (pdfInput) {
        pdfInput.addEventListener('change', (e) => {
            if (e.target.files && e.target.files.length > 0) {
                handlePdfsSelected(e.target.files);
            }
        });
    }

    function handlePdfsSelected(fileList) {
        if (!fileList || fileList.length === 0) return;
        const validFiles = Array.from(fileList).filter(f => f.name && f.name.toLowerCase().endsWith('.pdf'));
        if (validFiles.length === 0) {
            showToast('Format berkas harus PDF publikasi BPS (.pdf)!', 'warning', 4000);
            return;
        }

        selectedPdfFiles = validFiles;
        selectedPdfFile = validFiles[0];

        if (validFiles.length === 1) {
            const file = validFiles[0];
            const sizeMb = (file.size / (1024 * 1024)).toFixed(2);
            if (chosenFileName) chosenFileName.textContent = file.name;
            if (chosenFileSize) chosenFileSize.textContent = `${sizeMb} MB • Berkas Tunggal Siap Diperiksa`;
            if (btnAnalyze) {
                btnAnalyze.innerHTML = `<span>🔍 Mulai Audit Kepatuhan & Ekstraksi Kesalahan</span>`;
                btnAnalyze.disabled = false;
            }
            if (btnInstantAnalyze) {
                btnInstantAnalyze.innerHTML = `<span>🚀 Mulai Audit Sekarang</span>`;
            }
        } else {
            const totalMb = (validFiles.reduce((acc, f) => acc + f.size, 0) / (1024 * 1024)).toFixed(2);
            if (chosenFileName) chosenFileName.textContent = `${validFiles.length} Berkas PDF Terpilih`;
            if (chosenFileSize) chosenFileSize.textContent = `Total ${totalMb} MB • Mode Audit Kolektif Multi-Kecamatan`;
            if (btnAnalyze) {
                btnAnalyze.innerHTML = `<span>⚡ Mulai Audit Kolektif (${validFiles.length} Berkas PDF Sekaligus)</span>`;
                btnAnalyze.disabled = false;
            }
            if (btnInstantAnalyze) {
                btnInstantAnalyze.innerHTML = `<span>⚡ Mulai Audit Kolektif (${validFiles.length} PDF)</span>`;
            }
        }

        if (fileChosen) {
            fileChosen.style.display = 'flex';
            fileChosen.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
        }
        showToast(`✓ ${validFiles.length} berkas PDF dipilih. Klik "Mulai Audit" sekarang!`, 'success', 3500);
    }

    if (btnInstantAnalyze) {
        btnInstantAnalyze.addEventListener('click', (e) => {
            e.preventDefault();
            e.stopPropagation();
            if (btnAnalyze && !btnAnalyze.disabled) {
                btnAnalyze.click();
            }
        });
    }

    if (btnRemoveFile) {
        btnRemoveFile.addEventListener('click', (e) => {
            e.stopPropagation();
            selectedPdfFiles = [];
            selectedPdfFile = null;
            if (pdfInput) pdfInput.value = '';
            if (fileChosen) fileChosen.style.display = 'none';
            if (btnAnalyze) {
                btnAnalyze.disabled = true;
                btnAnalyze.innerHTML = `<span>🔍 Mulai Audit Kepatuhan & Ekstraksi Kesalahan</span>`;
            }
            showToast('Pilihan berkas PDF dibatalkan.', 'info', 1500);
        });
    }

    // ── 5. PROGRESS ANIMATION ──
    let progressInterval = null;
    function startProgress(title, desc) {
        if (resultsContainer) resultsContainer.style.display = 'none';
        const batchResultsContainer = document.getElementById('batch-results-container');
        if (batchResultsContainer) batchResultsContainer.style.display = 'none';

        const progressTitle = document.getElementById('progress-title');
        const progressDesc = document.getElementById('progress-desc');
        if (progressTitle && title) progressTitle.textContent = title;
        if (progressDesc && desc) progressDesc.textContent = desc;

        if (progressCard) progressCard.style.display = 'block';
        if (btnAnalyze) btnAnalyze.disabled = true;

        progressCard.scrollIntoView({ behavior: 'smooth', block: 'center' });

        const steps = [
            document.getElementById('step-1'),
            document.getElementById('step-2'),
            document.getElementById('step-3'),
            document.getElementById('step-4')
        ];

        steps.forEach(s => { if (s) s.className = 'step-pill'; });
        if (steps[0]) steps[0].classList.add('active');

        let stepIndex = 0;
        clearInterval(progressInterval);
        progressInterval = setInterval(() => {
            if (stepIndex < 3) {
                if (steps[stepIndex]) steps[stepIndex].classList.replace('active', 'done');
                stepIndex++;
                if (steps[stepIndex]) steps[stepIndex].classList.add('active');
            }
        }, 1200);
    }

    function stopProgress() {
        clearInterval(progressInterval);
        const steps = [
            document.getElementById('step-1'),
            document.getElementById('step-2'),
            document.getElementById('step-3'),
            document.getElementById('step-4')
        ];
        steps.forEach(s => { if (s) s.className = 'step-pill done'; });
        if (progressCard) progressCard.style.display = 'none';
        if (btnAnalyze) btnAnalyze.disabled = false;
    }

    // ── 6. SUBMIT ANALYSIS (SINGLE & MULTI BATCH) ──
    if (btnAnalyze) {
        btnAnalyze.addEventListener('click', () => {
            if (!selectedPdfFiles || selectedPdfFiles.length === 0) {
                showToast('Silakan pilih berkas PDF publikasi terlebih dahulu!', 'warning');
                return;
            }

            if (selectedPdfFiles.length > 1) {
                // Batch Upload Mode
                const formData = new FormData();
                selectedPdfFiles.forEach(file => {
                    formData.append('pdf_files', file);
                });
                if (apiKeyInput && apiKeyInput.value.trim()) {
                    formData.append('custom_api_key', apiKeyInput.value.trim());
                }

                startProgress(
                    `Sedang Melakukan Audit Kolektif ${selectedPdfFiles.length} Berkas PDF...`,
                    'Sistem memindai seluruh berkas secara paralel, mendeteksi ketidaksesuaian wilayah/kasus ganti kover, menyusun 1 Master File Excel Terpadu (.xlsx), dan mengemas seluruh Laporan PDF resmi (.zip).'
                );

                fetch('/api/analyze-batch-upload', {
                    method: 'POST',
                    body: formData
                })
                .then(res => {
                    if (!res.ok) {
                        return res.json().then(data => {
                            throw new Error(data.detail || 'Gagal memproses audit kolektif berkas PDF.');
                        }).catch(err => {
                            throw new Error(err.message || 'Gagal memproses audit kolektif.');
                        });
                    }
                    return res.json();
                })
                .then(batchData => {
                    stopProgress();
                    currentBatchData = batchData;
                    renderBatchResults(batchData);
                    showToast(`Audit kolektif selesai! ${batchData.total_districts} kecamatan berhasil dievaluasi.`, 'success', 4000);
                })
                .catch(err => {
                    stopProgress();
                    console.error(err);
                    alert(`Audit Kolektif Gagal: ${err.message}`);
                    showToast(`Terjadi kesalahan: ${err.message}`, 'warning', 5000);
                });

            } else {
                // Single File Mode
                const formData = new FormData();
                formData.append('pdf_file', selectedPdfFile);

                if (excelInput && excelInput.files && excelInput.files[0]) {
                    formData.append('excel_file', excelInput.files[0]);
                }
                if (apiKeyInput && apiKeyInput.value.trim()) {
                    formData.append('custom_api_key', apiKeyInput.value.trim());
                }

                startProgress(
                    'Sedang Menganalisis Dokumen Publikasi...',
                    'Sistem sedang memindai struktur teks, tipografi dwibahasa, visual gambar dummy template, tabel kosong, perataan angka, dan menyusun lembar evaluasi resmi.'
                );

                fetch('/api/analyze-upload', {
                    method: 'POST',
                    body: formData
                })
                .then(res => {
                    if (!res.ok) {
                        return res.json().then(data => {
                            throw new Error(data.detail || 'Gagal memproses audit berkas PDF.');
                        }).catch(err => {
                            throw new Error(err.message || 'Gagal memproses berkas PDF.');
                        });
                    }
                    return res.json();
                })
                .then(data => {
                    stopProgress();
                    currentAnalysisData = data;
                    renderResults(data);
                    showToast('Audit selesai! Hasil evaluasi siap ditelaah.', 'success', 4000);
                })
                .catch(err => {
                    stopProgress();
                    console.error(err);
                    alert(`Pemeriksaan Gagal: ${err.message}`);
                    showToast(`Terjadi kesalahan: ${err.message}`, 'warning', 5000);
                });
            }
        });
    }



    // ── 6C. RENDER BATCH RESULTS ──
    function renderBatchResults(batchData) {
        const batchContainer = document.getElementById('batch-results-container');
        if (!batchContainer) return;
        batchContainer.style.display = 'block';

        const statDistricts = document.getElementById('batch-stat-total-districts');
        const statDefects = document.getElementById('batch-stat-total-defects');
        const statClean = document.getElementById('batch-stat-clean-districts');
        const statMismatch = document.getElementById('batch-stat-mismatch-districts');
        const countBadge = document.getElementById('batch-table-count');

        if (statDistricts) statDistricts.textContent = batchData.total_districts || 0;
        if (statDefects) statDefects.textContent = batchData.total_defects || 0;
        if (statClean) statClean.textContent = batchData.clean_districts || 0;
        if (statMismatch) {
            statMismatch.textContent = batchData.mismatch_districts || 0;
            statMismatch.style.color = (batchData.mismatch_districts > 0) ? '#ef4444' : '#22c55e';
        }
        if (countBadge) countBadge.textContent = `${batchData.total_districts || 0} Kecamatan`;

        const btnExcel = document.getElementById('btn-batch-download-excel');
        const btnZip = document.getElementById('btn-batch-download-zip');
        if (btnExcel && batchData.master_excel_download_url) {
            btnExcel.href = batchData.master_excel_download_url;
            btnExcel.setAttribute('download', '');
        }
        if (btnZip && batchData.zip_download_url) {
            btnZip.href = batchData.zip_download_url;
            btnZip.setAttribute('download', '');
        }

        const tbody = document.getElementById('batch-table-body');
        if (!tbody) return;
        tbody.innerHTML = '';

        const districts = batchData.districts || [];
        districts.forEach((dist, idx) => {
            const tr = document.createElement('tr');
            const meta = dist.metadata || {};
            const isClean = dist.total_defects === 0;
            const isMismatch = dist.is_mismatch || (meta.district_mismatch_info && meta.district_mismatch_info.is_mismatch);
            const mismatchInfo = dist.mismatch_details || meta.district_mismatch_info || {};

            let statusPill = '';
            if (isMismatch) {
                statusPill = `<span class="badge-pill-status status-fatal">REVISI TOTAL</span>`;
            } else if (isClean) {
                statusPill = `<span class="badge-pill-status status-clean">SESUAI STANDAR</span>`;
            } else {
                statusPill = `<span class="badge-pill-status status-revision">PERLU REVISI</span>`;
            }

            let cloneCell = '';
            if (isMismatch) {
                const domInner = mismatchInfo.dominant_inner_district || 'Beda Wilayah';
                cloneCell = `<span class="badge-mismatch">🚨 Beda Wilayah (${domInner})</span>`;
            } else {
                cloneCell = `<span class="badge-normal">✓ Sesuai (Kover & Isi Sinkron)</span>`;
            }

            tr.innerHTML = `
                <td class="batch-cell-num">${idx + 1}</td>
                <td>
                    <strong class="dist-name">Kecamatan ${dist.district_name}</strong>
                    <div class="dist-meta">Publikasi: ${meta.year || '2026'} • ${meta.total_pages || '-'} Halaman</div>
                </td>
                <td>
                    <code class="dist-catalog">${meta.catalog || '-'}</code>
                    <div class="dist-issn">ISSN: ${meta.issn || '-'}</div>
                </td>
                <td style="text-align: center;">
                    <span class="badge-count ${isClean ? 'clean' : 'red'}">${dist.total_defects} Catatan</span>
                </td>
                <td style="text-align: center;">${statusPill}</td>
                <td>${cloneCell}</td>
                <td style="text-align: center;">
                    <button type="button" class="btn-table-detail" data-idx="${idx}">
                        <span>👁️ Rincian 11 Bagian</span>
                    </button>
                </td>
            `;

            const btnDetail = tr.querySelector('.btn-table-detail');
            if (btnDetail) {
                btnDetail.addEventListener('click', () => {
                    currentAnalysisData = dist;
                    renderResults(dist);
                    showToast(`Membuka rincian evaluasi Kecamatan ${dist.district_name}`, 'info', 2000);
                });
            }

            tbody.appendChild(tr);
        });

        batchContainer.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }


    // ── 7. RENDER RESULTS ──
    function renderResults(data) {
        if (!resultsContainer) return;
        resultsContainer.style.display = 'block';

        const meta = data.metadata || {};
        const defects = data.defects || {};
        const totalDefects = data.total_defects || 0;
        const totalSections = Object.keys(defects).length || 11;
        const cleanSections = data.clean_sections || 0;
        const defectSections = totalSections - cleanSections;

        // 1. Metadata Banner
        if (metaTitle) metaTitle.textContent = meta.title || 'Publikasi Kecamatan Dalam Angka';
        if (metaRegion) metaRegion.textContent = `📍 Wilayah: ${meta.region || '-'}`;
        if (metaYear) metaYear.textContent = `📅 Tahun: ${meta.year || '2026'}`;
        if (metaCatalog) metaCatalog.textContent = `🏷️ Katalog: ${meta.catalog || '-'}`;
        if (metaIssn) metaIssn.textContent = `🔢 ISSN: ${meta.issn || '-'}`;
        if (metaPages) metaPages.textContent = `📄 Fisik: ${meta.total_pages || '-'} Hlm`;

        // 2. Status Kelayakan Publikasi (Baku & Obyektif - Tanpa Persentase Arbitrer)
        const dMismatch = meta.district_mismatch_info || {};
        const fatalBanner = document.getElementById('fatal-mismatch-banner');
        const fatalDesc = document.getElementById('fatal-mismatch-desc');
        const fatalReasons = document.getElementById('fatal-mismatch-reasons');

        const isCleanAll = totalDefects === 0;
        if (dMismatch.is_mismatch) {
            if (fatalBanner) fatalBanner.style.display = 'flex';
            const covD = dMismatch.cover_district || meta.region || 'Wilayah A';
            const inD = dMismatch.dominant_inner_district || dMismatch.catalog_district || 'Wilayah B';
            if (fatalDesc) {
                fatalDesc.innerHTML = `Dokumen ini terdeteksi menggunakan kover <strong>"${covD}"</strong>, namun batang tubuh, narasi ulasan, dan data di dalamnya merupakan milik <strong>"${inD}"</strong>. Terindikasi kuat ketidaksesuaian identitas wilayah (halaman kover tidak sesuai dengan isi). <strong>PUBLIKASI TIDAK LAYAK TERBIT</strong> sebelum diganti dengan naskah dan data wilayah yang benar.`;
            }
            if (fatalReasons) {
                fatalReasons.innerHTML = (dMismatch.reasons || []).map(r => `<div>• ${r}</div>`).join('');
            }
            if (auditBadgeCard) auditBadgeCard.className = 'audit-badge-card status-fatal';
            if (auditBadgeIcon) auditBadgeIcon.textContent = '🚨';
            if (auditBadgeTitle) auditBadgeTitle.textContent = 'REVISI TOTAL (FATAL)';
            if (auditBadgeCount) auditBadgeCount.textContent = totalDefects;
            if (auditBadgeCaption) {
                auditBadgeCaption.innerHTML = `<span style="color:#ef4444;font-weight:700;">SALAH WILAYAH</span>: Terindikasi Hanya Ubah Kover (${totalDefects} Temuan)`;
            }
        } else {
            if (fatalBanner) fatalBanner.style.display = 'none';
            if (auditBadgeCard) {
                auditBadgeCard.className = `audit-badge-card ${isCleanAll ? 'status-clean' : 'status-revision'}`;
            }
            if (auditBadgeIcon) {
                auditBadgeIcon.textContent = isCleanAll ? '🛡️' : '⚠️';
            }
            if (auditBadgeTitle) {
                auditBadgeTitle.textContent = isCleanAll ? 'SESUAI STANDAR (SIAP RILIS)' : 'PERLU REVISI';
            }
            if (auditBadgeCount) {
                auditBadgeCount.textContent = totalDefects;
            }
            if (auditBadgeCaption) {
                auditBadgeCaption.innerHTML = isCleanAll
                    ? `✓ Seluruh 11 Bagian Bebas Kesalahan & Memenuhi Standar Baku BPS 2026`
                    : `<span id="audit-badge-count">${totalDefects}</span> Catatan Temuan Wajib Diperbaiki Sebelum Rilis`;
            }
        }

        // 3. Stat Cards
        if (statTotalDefects) statTotalDefects.textContent = totalDefects;
        if (statCleanSections) statCleanSections.textContent = `${cleanSections} / ${totalSections}`;

        const dummyCount = (meta.dummy_figures && meta.dummy_figures.length) ||
                           (meta.placeholder_pages && meta.placeholder_pages.length) ||
                           (meta.dummy_camera_detected ? 14 : 0);
        if (statDummyImages) {
            statDummyImages.textContent = dummyCount > 0 ? `${dummyCount} Gambar` : '0 Gambar';
            statDummyImages.style.color = dummyCount > 0 ? 'var(--accent-amber)' : 'var(--accent-green)';
        }

        if (statISSNConsistency) {
            const issnInconsistent = meta.issn_cross_page_inconsistent || false;
            const issnRegistryMismatch = meta.issn_registry_mismatch || null;
            
            if (issnInconsistent) {
                statISSNConsistency.textContent = 'Inkonsisten!';
                statISSNConsistency.style.color = 'var(--accent-red, #ef4444)';
                if (statISSNSub) {
                    const details = meta.issn_cross_page_details || [];
                    if (details.length >= 2) {
                        statISSNSub.textContent = `${details[0].issn} vs ${details[1].issn}`;
                    } else {
                        statISSNSub.textContent = 'Beda nomor antar-halaman';
                    }
                }
            } else if (issnRegistryMismatch) {
                statISSNConsistency.textContent = 'Salah Registri';
                statISSNConsistency.style.color = 'var(--accent-amber, #f59e0b)';
                if (statISSNSub) {
                    statISSNSub.textContent = `Tertulis ${issnRegistryMismatch.found} (Resmi: ${issnRegistryMismatch.correct})`;
                }
            } else {
                statISSNConsistency.textContent = 'Konsisten';
                statISSNConsistency.style.color = 'var(--accent-green, #22c55e)';
                if (statISSNSub) {
                    statISSNSub.textContent = 'Seluruh halaman sinkron';
                }
            }
        }

        // 3B. Computer Vision Advanced Telemetry Panel
        const cvCard = document.getElementById('cv-telemetry-card');
        const cvValCover = document.getElementById('cv-val-cover');
        const cvValHJU = document.getElementById('cv-val-hju');
        const cvValPreface = document.getElementById('cv-val-preface');
        const cvValBody = document.getElementById('cv-val-body');

        const cvAudit = meta.cv_audit || {};
        if (cvCard && (cvAudit.cover_visual || cvAudit.hju_visual || cvAudit.preface_visual)) {
            cvCard.style.display = 'block';

            // Cover
            const covVis = cvAudit.cover_visual || {};
            let covIssues = [];
            if (covVis.has_colon_on_issn) covIssues.push('ISSN : (Titik Dua)');
            if (covVis.has_space_before_colon_catalog) covIssues.push('Katalog : (Spasi)');
            if (covVis.has_template_letter_a) covIssues.push('Residu Huruf A');
            if (cvValCover) {
                cvValCover.textContent = covIssues.length > 0 ? `⚠️ ${covIssues.join(' • ')}` : '✓ Sesuai Kaidah Baku';
                cvValCover.style.color = covIssues.length > 0 ? '#f87171' : '#4ade80';
            }

            // HJU
            const hjuVis = cvAudit.hju_visual || {};
            let hjuIssues = [];
            if (hjuVis.has_illustration_background) hjuIssues.push('Foto Alam (Duplikasi Kover)');
            if (hjuVis.logo_is_monochrome) hjuIssues.push('Logo Monokrom');
            if (hjuVis.has_colon_on_issn) hjuIssues.push('ISSN : (Titik Dua)');
            if (cvValHJU) {
                cvValHJU.textContent = hjuIssues.length > 0 ? `⚠️ ${hjuIssues.join(' • ')}` : '✓ Latar Putih Bersih';
                cvValHJU.style.color = hjuIssues.length > 0 ? '#f87171' : '#4ade80';
            }

            // Preface
            const prefVis = cvAudit.preface_visual || {};
            let prefTxt = [];
            if (prefVis.has_face) {
                prefTxt.push(`Wajah BPS (${prefVis.photo_aspect_ratio || '3:4'})`);
            }
            if (prefVis.signature_vertical_gap_cm) {
                const isCramped = prefVis.signature_space_is_cramped;
                prefTxt.push(`Ruang TTD: ${prefVis.signature_vertical_gap_cm} cm ${isCramped ? '(Cramped < 2.5cm)' : '(Cukup)'}`);
            }
            if (cvValPreface) {
                cvValPreface.textContent = prefTxt.length > 0 ? prefTxt.join(' • ') : 'Tidak Terdeteksi Foto/TTD';
                cvValPreface.style.color = prefVis.signature_space_is_cramped ? '#fbbf24' : '#38bdf8';
            }

            // Body
            const bodyVis = cvAudit.tables_figures_visual || {};
            const dummies = bodyVis.dummy_camera_placeholders || [];
            if (cvValBody) {
                if (dummies.length > 0) {
                    cvValBody.textContent = `⚠️ ${dummies.length} Titik Placeholder Kamera (Hal ${dummies.slice(0, 4).join(', ')}...)`;
                    cvValBody.style.color = '#f87171';
                } else {
                    cvValBody.textContent = '✓ Tidak Ada Dummy Kamera';
                    cvValBody.style.color = '#4ade80';
                }
            }
        } else if (cvCard) {
            cvCard.style.display = 'none';
        }

        // 4. Download Excel & PDF Buttons
        if (btnDownloadPdf && data.pdf_download_url) {
            btnDownloadPdf.href = data.pdf_download_url;
            btnDownloadPdf.setAttribute('download', '');
        }
        if (btnDownloadExcel) {
            btnDownloadExcel.href = data.excel_download_url || data.download_url;
            btnDownloadExcel.setAttribute('download', '');
        }

        // Reset search
        if (defectSearch) defectSearch.value = '';

        // 5. Aesthetic Tips Banner Logic
        let aestheticCount = 0;
        for (const items of Object.values(defects)) {
            if (Array.isArray(items)) {
                items.forEach(d => {
                    if (d.includes('[SARAN ESTETIKA')) aestheticCount++;
                });
            }
        }
        const aestheticBanner = document.getElementById('aesthetic-tips-banner');
        const aestheticCountPill = document.getElementById('aesthetic-count-pill');
        if (aestheticBanner) {
            if (aestheticCount > 0) {
                aestheticBanner.style.display = 'flex';
                if (aestheticCountPill) aestheticCountPill.textContent = `${aestheticCount} Rekomendasi Desain`;
            } else {
                aestheticBanner.style.display = 'none';
            }
        }

        // 6. Render Section Cards & Apply Filters
        renderSectionCards(defects);
        applyFilters();

        // Smooth scroll to results
        resultsContainer.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }

    function renderSectionCards(defects) {
        if (!sectionsWrapper) {
            console.error('sectionsWrapper tidak ditemukan pada DOM!');
            return;
        }
        sectionsWrapper.innerHTML = '';

        for (const [sectionName, items] of Object.entries(defects)) {
            const isClean = !items || items.length === 0;
            const cleanTitle = sectionName.replace(':', '').replace('-', '').trim();

            const card = document.createElement('div');
            card.className = `section-card ${isClean ? 'section-clean' : 'section-defect'}`;
            card.dataset.clean = isClean ? 'true' : 'false';
            card.dataset.title = cleanTitle.toLowerCase();
            card.style.display = 'block';

            // Header
            const header = document.createElement('div');
            header.className = 'section-header';
            header.innerHTML = `
                <div class="section-title">
                    <span class="status-icon">${isClean ? '✅' : '⚠️'}</span>
                    <span class="title-text">${cleanTitle}</span>
                </div>
                <div class="header-badges">
                    <span class="badge-count ${isClean ? 'clean' : 'red'}">
                        ${isClean ? 'Bebas Kesalahan' : items.length + ' Temuan'}
                    </span>
                    <span class="card-chevron">▼</span>
                </div>
            `;

            // List
            const list = document.createElement('div');
            list.className = 'defect-list';

            if (isClean) {
                const cleanItem = document.createElement('div');
                cleanItem.className = 'clean-item';
                cleanItem.innerHTML = `
                    <span class="check-icon">✓</span>
                    <div>Bagian ini telah sesuai dengan ketentuan baku BPS (tanpa temuan kesalahan). Sesuai aturan evaluasi resmi, kolom catatan dikosongkan.</div>
                `;
                list.appendChild(cleanItem);
            } else {
                items.forEach((defect, idx) => {
                    const isFatal = defect.includes('[FATAL');
                    const isAesthetic = defect.includes('[SARAN ESTETIKA');
                    const defectItem = document.createElement('div');
                    defectItem.className = `defect-item ${isFatal ? 'defect-item-fatal' : (isAesthetic ? 'defect-item-aesthetic' : '')}`;

                    const itemContent = document.createElement('div');
                    itemContent.className = 'defect-content';
                    itemContent.innerHTML = `<span class="defect-num">[${idx + 1}]</span> <span class="defect-text">${defect}</span>`;

                    const btnCopySingle = document.createElement('button');
                    btnCopySingle.type = 'button';
                    btnCopySingle.className = 'btn-copy-defect';
                    btnCopySingle.title = 'Salin catatan ini';
                    btnCopySingle.innerHTML = '📋 Salin';
                    btnCopySingle.addEventListener('click', (e) => {
                        e.stopPropagation();
                        navigator.clipboard.writeText(`[${cleanTitle}] ${defect}`).then(() => {
                            showToast(`Catatan [${idx + 1}] tersalin ke clipboard! ✓`, 'success', 2000);
                        });
                    });

                    defectItem.appendChild(itemContent);
                    defectItem.appendChild(btnCopySingle);
                    list.appendChild(defectItem);
                });
            }

            // Accordion Toggle on Header Click
            header.addEventListener('click', () => {
                const isCollapsed = list.classList.toggle('collapsed');
                const chevron = header.querySelector('.card-chevron');
                if (chevron) chevron.textContent = isCollapsed ? '▶' : '▼';
            });

            card.appendChild(header);
            card.appendChild(list);
            sectionsWrapper.appendChild(card);
        }
    }

    // ── 8. REAL-TIME KEYWORD SEARCH ──
    if (defectSearch) {
        defectSearch.addEventListener('input', () => {
            applyFilters();
        });
    }

    function applyFilters() {
        const query = defectSearch ? defectSearch.value.trim().toLowerCase() : '';
        const cards = document.querySelectorAll('.section-card');

        cards.forEach(card => {
            const title = card.dataset.title || '';
            const textContent = card.textContent.toLowerCase();
            const matchesQuery = !query || title.includes(query) || textContent.includes(query);
            card.style.display = matchesQuery ? 'block' : 'none';
        });
    }

    // ── 10. EXPAND / COLLAPSE ALL ──
    if (btnToggleAll && toggleAllText) {
        btnToggleAll.addEventListener('click', () => {
            isAllCollapsed = !isAllCollapsed;
            const lists = document.querySelectorAll('.defect-list');
            const chevrons = document.querySelectorAll('.card-chevron');

            lists.forEach(list => {
                if (isAllCollapsed) {
                    list.classList.add('collapsed');
                } else {
                    list.classList.remove('collapsed');
                }
            });

            chevrons.forEach(ch => {
                ch.textContent = isAllCollapsed ? '▶' : '▼';
            });

            toggleAllText.textContent = isAllCollapsed ? '📂 Buka Semua' : '📁 Ciutkan Semua';
            showToast(isAllCollapsed ? 'Semua seksi diciutkan' : 'Semua seksi dibuka', 'info', 1500);
        });
    }

    // ── 11. BULK COPY ALL DEFECTS ──
    if (btnCopyAll) {
        btnCopyAll.addEventListener('click', () => {
            if (!currentAnalysisData || !currentAnalysisData.defects) {
                showToast('Belum ada data evaluasi untuk disalin.', 'warning');
                return;
            }

            const meta = currentAnalysisData.metadata || {};
            const defects = currentAnalysisData.defects;
            let report = `LAPORAN EVALUASI PUBLIKASI BPS 2026\n`;
            report += `Judul: ${meta.title || '-'}\n`;
            report += `Wilayah: ${meta.region || '-'} | Tahun: ${meta.year || '2026'}\n`;
            report += `Katalog: ${meta.catalog || '-'} | ISSN: ${meta.issn || '-'}\n`;
            report += `Total Temuan: ${currentAnalysisData.total_defects} catatan\n`;
            report += `==================================================\n\n`;

            for (const [sec, items] of Object.entries(defects)) {
                const secClean = sec.replace(':', '').replace('-', '').trim();
                report += `[ ${secClean} ]\n`;
                if (items.length === 0) {
                    report += `  ✓ Sesuai standar baku (Bebas kesalahan)\n\n`;
                } else {
                    items.forEach((item, idx) => {
                        report += `  (${idx + 1}) ${item}\n`;
                    });
                    report += `\n`;
                }
            }

            navigator.clipboard.writeText(report).then(() => {
                showToast(`✓ Seluruh catatan evaluasi (${currentAnalysisData.total_defects} temuan) tersalin ke clipboard!`, 'success', 3500);
            }).catch(() => {
                showToast('Gagal menyalin otomatis, silakan periksa izin peramban.', 'warning');
            });
        });
    }

    // ── 12. RESET AUDIT ──
    if (btnResetAudit) {
        btnResetAudit.addEventListener('click', () => {
            selectedPdfFile = null;
            currentAnalysisData = null;
            if (pdfInput) pdfInput.value = '';
            if (fileChosen) fileChosen.style.display = 'none';
            if (btnAnalyze) btnAnalyze.disabled = true;
            if (resultsContainer) resultsContainer.style.display = 'none';

            const panelUpload = document.getElementById('panel-upload');
            if (panelUpload) {
                panelUpload.scrollIntoView({ behavior: 'smooth', block: 'start' });
            }
            showToast('Siap melakukan evaluasi dokumen baru.', 'info', 2000);
        });
    }
});
