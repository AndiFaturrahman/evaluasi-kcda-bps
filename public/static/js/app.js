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
    const btnAddMorePdf = document.getElementById('btn-add-more-pdf');
    const pdfAddInput = document.getElementById('pdf-add-input');
    const chosenFilesList = document.getElementById('chosen-files-list');
    const fileChosenMainIcon = document.getElementById('file-chosen-main-icon');

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
                handlePdfsSelected(e.target.files, false);
            }
        });
    }

    if (btnAddMorePdf && pdfAddInput) {
        btnAddMorePdf.addEventListener('click', (e) => {
            e.preventDefault();
            e.stopPropagation();
            pdfAddInput.click();
        });
        pdfAddInput.addEventListener('change', (e) => {
            if (e.target.files && e.target.files.length > 0) {
                handlePdfsSelected(e.target.files, true);
                e.target.value = '';
            }
        });
    }

    function handlePdfsSelected(fileList, isAppend = false) {
        if (!fileList || fileList.length === 0) return;
        const validFiles = Array.from(fileList).filter(f => f.name && f.name.toLowerCase().endsWith('.pdf'));
        if (validFiles.length === 0) {
            showToast('Format berkas harus PDF publikasi BPS (.pdf)!', 'warning', 4000);
            return;
        }

        if (isAppend && selectedPdfFiles && selectedPdfFiles.length > 0) {
            let addedCount = 0;
            validFiles.forEach(newF => {
                const exists = selectedPdfFiles.some(cur => cur.name === newF.name && cur.size === newF.size);
                if (!exists) {
                    selectedPdfFiles.push(newF);
                    addedCount++;
                }
            });
            if (addedCount === 0) {
                showToast('Berkas PDF tersebut sudah ada di antrean.', 'info', 2500);
                return;
            }
            showToast(`✓ Ditambahkan ${addedCount} berkas PDF baru ke antrean!`, 'success', 3000);
        } else {
            selectedPdfFiles = validFiles;
            showToast(`✓ ${validFiles.length} berkas PDF dipilih. Klik "Mulai Audit" sekarang!`, 'success', 3500);
        }

        selectedPdfFile = selectedPdfFiles[0] || null;
        renderChosenFilesUI();
    }

    function renderChosenFilesUI() {
        if (!selectedPdfFiles || selectedPdfFiles.length === 0) {
            if (fileChosen) fileChosen.style.display = 'none';
            if (btnAnalyze) {
                btnAnalyze.disabled = true;
                btnAnalyze.innerHTML = `<span>🔍 Mulai Audit Kepatuhan & Ekstraksi Kesalahan</span>`;
            }
            if (chosenFilesList) {
                chosenFilesList.innerHTML = '';
                chosenFilesList.style.display = 'none';
            }
            return;
        }

        const count = selectedPdfFiles.length;
        const totalBytes = selectedPdfFiles.reduce((acc, f) => acc + f.size, 0);
        const totalMb = (totalBytes / (1024 * 1024)).toFixed(2);

        if (count === 1) {
            const single = selectedPdfFiles[0];
            if (fileChosenMainIcon) fileChosenMainIcon.textContent = '📄';
            if (chosenFileName) chosenFileName.textContent = single.name;
            if (chosenFileSize) chosenFileSize.textContent = `${totalMb} MB • Berkas Tunggal Siap Diperiksa`;
            if (btnAnalyze) {
                btnAnalyze.innerHTML = `<span>🔍 Mulai Audit Kepatuhan & Ekstraksi Kesalahan</span>`;
                btnAnalyze.disabled = false;
            }
            if (btnInstantAnalyze) {
                btnInstantAnalyze.innerHTML = `<span>🚀 Mulai Audit Sekarang</span>`;
            }
            if (chosenFilesList) {
                chosenFilesList.style.display = 'none';
                chosenFilesList.innerHTML = '';
            }
        } else {
            if (fileChosenMainIcon) fileChosenMainIcon.textContent = '📚';
            if (chosenFileName) chosenFileName.textContent = `${count} Berkas PDF Terpilih (Kolektif)`;
            if (chosenFileSize) chosenFileSize.textContent = `Total ${totalMb} MB • Mode Audit Kolektif Multi-Kecamatan`;
            if (btnAnalyze) {
                btnAnalyze.innerHTML = `<span>⚡ Mulai Audit Kolektif (${count} Berkas PDF Sekaligus)</span>`;
                btnAnalyze.disabled = false;
            }
            if (btnInstantAnalyze) {
                btnInstantAnalyze.innerHTML = `<span>⚡ Mulai Audit Kolektif (${count} PDF)</span>`;
            }

            if (chosenFilesList) {
                chosenFilesList.innerHTML = '';
                chosenFilesList.style.display = 'flex';

                selectedPdfFiles.forEach((f, idx) => {
                    const chip = document.createElement('div');
                    chip.className = 'chosen-file-chip';
                    const fMb = (f.size / (1024 * 1024)).toFixed(2);
                    chip.innerHTML = `
                        <div class="chosen-chip-info" title="${f.name}">
                            <span>📄</span>
                            <span class="chosen-chip-name">${idx + 1}. ${f.name}</span>
                            <span class="chosen-chip-size">${fMb} MB</span>
                        </div>
                        <button type="button" class="btn-chip-del" title="Hapus berkas ini dari antrean">✕</button>
                    `;
                    const delBtn = chip.querySelector('.btn-chip-del');
                    delBtn.addEventListener('click', (e) => {
                        e.stopPropagation();
                        selectedPdfFiles.splice(idx, 1);
                        selectedPdfFile = selectedPdfFiles[0] || null;
                        renderChosenFilesUI();
                        showToast(`Berkas "${f.name}" dihapus dari antrean.`, 'info', 2000);
                    });
                    chosenFilesList.appendChild(chip);
                });
            }
        }

        if (fileChosen) {
            fileChosen.style.display = 'flex';
            fileChosen.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
        }
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
            if (pdfAddInput) pdfAddInput.value = '';
            if (fileChosen) fileChosen.style.display = 'none';
            if (chosenFilesList) {
                chosenFilesList.innerHTML = '';
                chosenFilesList.style.display = 'none';
            }
            if (btnAnalyze) {
                btnAnalyze.disabled = true;
                btnAnalyze.innerHTML = `<span>🔍 Mulai Audit Kepatuhan & Ekstraksi Kesalahan</span>`;
            }
            showToast('Seluruh pilihan berkas PDF dibersihkan.', 'info', 1500);
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
                const totalBytes = selectedPdfFiles.reduce((sum, f) => sum + f.size, 0);
                const totalMB = (totalBytes / (1024 * 1024)).toFixed(1);

                if (window.location.hostname.includes('vercel.app') && totalBytes > 4.5 * 1024 * 1024) {
                    alert(`Batas Vercel Serverless Terlampaui:\n\nTotal ukuran ${selectedPdfFiles.length} berkas yang Anda pilih adalah ${totalMB} MB.\nVercel Serverless memiliki batas maksimal payload 4.5 MB per permintaan.\n\nUntuk melakukan Audit Kolektif berkas publikasi BPS secara utuh dan tanpa batasan ukuran, silakan gunakan tautan Cloudflare Tunnel atau server lokal.`);
                    showToast(`Batas Vercel (4.5 MB) terlampaui (${totalMB} MB). Gunakan Cloudflare Tunnel / Server Lokal.`, 'warning', 7000);
                    return;
                }

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
                .then(async res => {
                    if (!res.ok) {
                        let errMsg = `Gagal memproses audit kolektif (${res.status} ${res.statusText})`;
                        if (res.status === 413) {
                            errMsg = `Batas Payload Serverless Terlampaui (HTTP 413 Request Entity Too Large): Total berkas (${totalMB} MB) melebihi batas 4.5 MB Vercel Serverless. Silakan gunakan Cloudflare Tunnel atau server lokal untuk audit kolektif.`;
                        } else if (res.status === 504) {
                            errMsg = 'Batas Waktu Eksekusi Terlampaui (HTTP 504 Gateway Timeout): Analisis dokumen melebihi batas waktu Vercel Serverless. Silakan gunakan Cloudflare Tunnel atau server lokal.';
                        } else {
                            try {
                                const text = await res.text();
                                const errData = JSON.parse(text);
                                errMsg = errData.detail || errData.message || errMsg;
                            } catch (e) {
                                // Not JSON
                            }
                        }
                        throw new Error(errMsg);
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
                    showToast(`Terjadi kesalahan: ${err.message}`, 'warning', 6000);
                });

            } else {
                // Single File Mode
                const singleBytes = selectedPdfFile.size;
                const singleMB = (singleBytes / (1024 * 1024)).toFixed(1);

                if (window.location.hostname.includes('vercel.app') && singleBytes > 4.5 * 1024 * 1024) {
                    alert(`Batas Vercel Serverless Terlampaui:\n\nBerkas "${selectedPdfFile.name}" berukuran ${singleMB} MB, melebihi batas maksimal Vercel Serverless (4.5 MB).\n\nSilakan gunakan tautan Cloudflare Tunnel atau server lokal untuk memproses berkas publikasi besar ini.`);
                    showToast(`Berkas terlalu besar (${singleMB} MB) untuk Vercel. Gunakan Cloudflare Tunnel / Server Lokal.`, 'warning', 7000);
                    return;
                }

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
                .then(async res => {
                    if (!res.ok) {
                        let errMsg = `Gagal memproses berkas (${res.status} ${res.statusText})`;
                        if (res.status === 413) {
                            errMsg = `Batas Payload Serverless Terlampaui (HTTP 413 Request Entity Too Large): Berkas "${selectedPdfFile.name}" (${singleMB} MB) melebihi batas 4.5 MB Vercel Serverless. Silakan gunakan Cloudflare Tunnel atau server lokal.`;
                        } else if (res.status === 504) {
                            errMsg = 'Batas Waktu Eksekusi Terlampaui (HTTP 504 Gateway Timeout): Analisis dokumen melebihi batas waktu Vercel Serverless. Silakan gunakan Cloudflare Tunnel atau server lokal.';
                        } else {
                            try {
                                const text = await res.text();
                                const errData = JSON.parse(text);
                                errMsg = errData.detail || errData.message || errMsg;
                            } catch (e) {
                                // Not JSON
                            }
                        }
                        throw new Error(errMsg);
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
                    showToast(`Terjadi kesalahan: ${err.message}`, 'warning', 6000);
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

        // 4. Download Excel & PDF Buttons (Anti undefined.json Fallback)
        const distName = (meta && meta.region) ? meta.region.replace(/\s+/g, '_') : 'Evaluasi';
        const docYear = (meta && meta.year) || '2026';

        if (btnDownloadPdf) {
            if (data.pdf_download_url) {
                btnDownloadPdf.href = data.pdf_download_url;
                btnDownloadPdf.setAttribute('download', `Laporan_Evaluasi_${distName}_${docYear}.pdf`);
                btnDownloadPdf.style.display = 'inline-flex';
            } else {
                btnDownloadPdf.style.display = 'none';
            }
        }

        const excelUrl = data.excel_download_url || data.download_url || (currentBatchData && currentBatchData.master_excel_download_url);
        if (btnDownloadExcel) {
            if (excelUrl) {
                btnDownloadExcel.href = excelUrl;
                btnDownloadExcel.setAttribute('download', `Evaluasi_${distName}_${docYear}.xlsx`);
                btnDownloadExcel.style.display = 'inline-flex';
            } else {
                btnDownloadExcel.style.display = 'none';
            }
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
        renderSectionCards(defects, meta);
        applyFilters();

        // Smooth scroll to results
        resultsContainer.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }

    function renderSectionCards(defects, meta) {
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

                    const actionsWrap = document.createElement('div');
                    actionsWrap.className = 'defect-actions-wrap';

                    // Direct Page Jump Button
                    const targetPage = getPageForDefect(cleanTitle, defect, meta);
                    const btnViewPdf = document.createElement('button');
                    btnViewPdf.type = 'button';
                    btnViewPdf.className = 'btn-view-pdf';
                    btnViewPdf.title = `Buka PDF langsung ke Halaman ${targetPage}`;
                    btnViewPdf.innerHTML = `👁️ Hal. ${targetPage}`;
                    btnViewPdf.addEventListener('click', (e) => {
                        e.stopPropagation();
                        openPdfViewer(currentAnalysisData || data, targetPage, cleanTitle, defect, idx + 1);
                    });

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

                    actionsWrap.appendChild(btnViewPdf);
                    actionsWrap.appendChild(btnCopySingle);

                    defectItem.appendChild(itemContent);
                    defectItem.appendChild(actionsWrap);
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

    // ── 13. DIRECT PDF VIEWER MODAL CONTROLLER ──
    const pdfViewerModal = document.getElementById('pdf-viewer-modal');
    const pdfModalDocTitle = document.getElementById('pdf-modal-doc-title');
    const pdfModalSubTitle = document.getElementById('pdf-modal-sub-title');
    const pdfModalCurPage = document.getElementById('pdf-modal-cur-page');
    const pdfModalTotalPage = document.getElementById('pdf-modal-total-page');
    const btnPdfPrevPage = document.getElementById('btn-pdf-prev-page');
    const btnPdfNextPage = document.getElementById('btn-pdf-next-page');
    const btnPdfOpenTab = document.getElementById('btn-pdf-open-tab');
    const btnClosePdfModal = document.getElementById('btn-close-pdf-modal');
    const pdfModalDefectBanner = document.getElementById('pdf-modal-defect-banner');
    const pdfModalDefectIcon = document.getElementById('pdf-modal-defect-icon');
    const pdfModalDefectMsg = document.getElementById('pdf-modal-defect-msg');
    const pdfModalIframe = document.getElementById('pdf-modal-iframe');

    let pdfViewerState = {
        pdfUrl: '',
        currentPage: 1,
        totalPages: 1
    };

    function romanToInt(s) {
        if (!s) return 0;
        const roman = { i: 1, v: 5, x: 10, l: 50, c: 100, d: 500, m: 1000 };
        let num = 0;
        const str = s.toLowerCase();
        for (let i = 0; i < str.length; i++) {
            const curr = roman[str[i]] || 0;
            const next = roman[str[i + 1]] || 0;
            if (curr < next) {
                num -= curr;
            } else {
                num += curr;
            }
        }
        return num;
    }

    function getPageForDefect(sectionName, defectText, meta) {
        if (!defectText) return 1;
        const text = defectText;
        const sec = (sectionName || '').toLowerCase();
        const sectionPages = (meta && meta.section_pages) || {};

        // 1. Direct explicit physical page regex in defect text
        // E.g.: "halaman fisik 29", "hal fisik 4", "Halaman 18", "Hal. 12", "hal 5", "Halaman: 8"
        const mPhys = text.match(/(?:halaman\s+fisik|hal\s+fisik|halaman|hal\.?)\s*[:#]?\s*(\d+)/i);
        if (mPhys && mPhys[1]) {
            const p = parseInt(mPhys[1], 10);
            if (p > 0) return p;
        }

        // 2. Table label with page, e.g. "Tabel 3.1.2 (halaman 29)" or "(hal. 14)"
        const mTbl = text.match(/\(hal(?:aman)?\.?\s*(\d+)\)/i);
        if (mTbl && mTbl[1]) {
            const p = parseInt(mTbl[1], 10);
            if (p > 0) return p;
        }

        // 3. Multi-page dummy list: "Hal 24, 30, 42" -> take the first one
        const mDummies = text.match(/Hal(?:aman)?\s+(\d+)(?:\s*,\s*\d+)/i);
        if (mDummies && mDummies[1]) {
            const p = parseInt(mDummies[1], 10);
            if (p > 0) return p;
        }

        // 4. Roman numerals in defect text: e.g. "halaman v", "hal iii", "halaman xii"
        const mRoman = text.match(/(?:halaman|hal)\s+([ivxlcdm]+)\b/i);
        if (mRoman && mRoman[1]) {
            const rVal = romanToInt(mRoman[1]);
            if (rVal > 0) {
                if (sectionPages.kata_pengantar) {
                    return sectionPages.kata_pengantar;
                }
                return rVal + 2;
            }
        }

        // 5. Section-based mapping if no explicit page is found in text
        if (sec.includes('kover depan') || sec.includes('cover depan')) return 1;
        if (sec.includes('halaman kosong') && sec.includes('kover')) return 2;
        if (sec.includes('judul utama') || sec.includes('hju')) return sectionPages.hju || 3;
        if (sec.includes('katalog') || sec.includes('catalog')) return sectionPages.katalog || 4;
        if (sec.includes('tim penyusun') || sec.includes('team')) return sectionPages.tim_penyusun || 5;
        if (sec.includes('kata pengantar') || sec.includes('preface')) return sectionPages.kata_pengantar || 6;
        if (sec.includes('daftar isi') || sec.includes('contents')) return sectionPages.daftar_isi || 8;
        if (sec.includes('daftar tabel') || sec.includes('list of tables')) return sectionPages.daftar_tabel || 10;
        if (sec.includes('daftar gambar') || sec.includes('list of figures')) return sectionPages.daftar_gambar || 12;
        if (sec.includes('penjelasan umum') || sec.includes('penjelasan teknis') || sec.includes('singkatan')) return sectionPages.penjelasan_umum || 14;
        if (sec.includes('batang tubuh') || sec.includes('tabel')) return 16;
        if (sec.includes('daftar pustaka') || sec.includes('bibliography')) return sectionPages.daftar_pustaka || Math.max(1, (meta && meta.total_pages ? meta.total_pages - 1 : 100));
        if (sec.includes('kover belakang') || sec.includes('cover belakang')) return (meta && meta.total_pages) ? meta.total_pages : 1;

        return 1;
    }

    function openPdfViewer(data, targetPage, sectionTitle, defectText, defectIndex) {
        const modal = pdfViewerModal || document.getElementById('pdf-viewer-modal');
        if (!modal) {
            console.error('Modal element #pdf-viewer-modal not found in DOM');
            showToast('Komponen penampil PDF tidak ditemukan di halaman.', 'warning');
            return;
        }

        const meta = (data && data.metadata) || {};
        const totalPages = parseInt(meta.total_pages || (data && data.total_pages) || 100, 10);
        const region = meta.region || (data && data.district_name) || 'Kecamatan';
        const year = meta.year || (data && data.year) || '2026';
        const title = meta.title || (data && data.title) || `Publikasi Kecamatan ${region} Dalam Angka ${year}`;

        // Cari file lokal jika pengguna mengunggah berkas di sesi ini
        let localFile = null;
        if (selectedPdfFile) {
            localFile = selectedPdfFile;
        } else if (selectedPdfFiles && selectedPdfFiles.length > 0) {
            const regClean = region.toLowerCase().replace(/\s+/g, '');
            for (const f of selectedPdfFiles) {
                const fname = f.name.toLowerCase().replace(/[^a-z0-9]/g, '');
                if (fname.includes(regClean)) {
                    localFile = f;
                    break;
                }
            }
            if (!localFile) localFile = selectedPdfFiles[0];
        }

        let pdfSourceUrl = '';
        if (localFile) {
            if (!localFile._blobUrl) {
                localFile._blobUrl = URL.createObjectURL(localFile);
            }
            pdfSourceUrl = localFile._blobUrl;
        } else if (data && data.source_pdf_url) {
            pdfSourceUrl = data.source_pdf_url;
        } else if (data && data.source_pdf_filename) {
            pdfSourceUrl = `/api/view-pdf/${encodeURIComponent(data.source_pdf_filename)}`;
        } else if (data && data.pdf_download_url) {
            pdfSourceUrl = data.pdf_download_url;
        }

        if (!pdfSourceUrl) {
            showToast('Berkas PDF belum tersedia untuk pratinjau langsung.', 'warning');
            return;
        }

        pdfViewerState = {
            pdfUrl: pdfSourceUrl,
            currentPage: Math.max(1, Math.min(totalPages, targetPage || 1)),
            totalPages: totalPages,
            title: title
        };

        if (pdfModalDocTitle) pdfModalDocTitle.textContent = title;
        if (pdfModalSubTitle) pdfModalSubTitle.textContent = `Wilayah: ${region} • ${totalPages} Halaman Dokumen`;

        const isAesthetic = defectText && defectText.includes('[SARAN ESTETIKA');
        if (pdfModalDefectBanner) {
            pdfModalDefectBanner.className = `pdf-modal-defect-banner ${isAesthetic ? 'is-aesthetic' : ''}`;
        }
        if (pdfModalDefectIcon) {
            pdfModalDefectIcon.textContent = isAesthetic ? '💡' : '⚠️';
        }
        if (pdfModalDefectMsg) {
            pdfModalDefectMsg.innerHTML = `<strong>[${sectionTitle}] Catatan #${defectIndex}:</strong> ${defectText}`;
        }

        updatePdfModalPage(pdfViewerState.currentPage);

        modal.style.display = 'flex';
        document.body.style.overflow = 'hidden';
    }

    function updatePdfModalPage(page) {
        if (!pdfViewerState || !pdfViewerState.pdfUrl) return;

        pdfViewerState.currentPage = Math.max(1, Math.min(pdfViewerState.totalPages, page));
        const curPage = pdfViewerState.currentPage;

        if (pdfModalCurPage) pdfModalCurPage.textContent = curPage;
        if (pdfModalTotalPage) pdfModalTotalPage.textContent = pdfViewerState.totalPages;

        if (btnPdfPrevPage) btnPdfPrevPage.disabled = (curPage <= 1);
        if (btnPdfNextPage) btnPdfNextPage.disabled = (curPage >= pdfViewerState.totalPages);

        const targetUrlWithHash = `${pdfViewerState.pdfUrl}#page=${curPage}&zoom=100`;

        if (btnPdfOpenTab) {
            btnPdfOpenTab.href = targetUrlWithHash;
        }

        if (pdfModalIframe) {
            pdfModalIframe.src = targetUrlWithHash;
        }
    }

    function closePdfViewer() {
        if (!pdfViewerModal) return;
        pdfViewerModal.style.display = 'none';
        document.body.style.overflow = '';
        if (pdfModalIframe) {
            pdfModalIframe.src = '';
        }
    }

    if (btnPdfPrevPage) {
        btnPdfPrevPage.addEventListener('click', () => {
            updatePdfModalPage(pdfViewerState.currentPage - 1);
        });
    }

    if (btnPdfNextPage) {
        btnPdfNextPage.addEventListener('click', () => {
            updatePdfModalPage(pdfViewerState.currentPage + 1);
        });
    }

    if (btnClosePdfModal) {
        btnClosePdfModal.addEventListener('click', closePdfViewer);
    }

    if (pdfViewerModal) {
        pdfViewerModal.addEventListener('click', (e) => {
            if (e.target === pdfViewerModal) {
                closePdfViewer();
            }
        });
    }

    window.addEventListener('keydown', (e) => {
        if (pdfViewerModal && pdfViewerModal.style.display === 'flex') {
            if (e.key === 'Escape') {
                closePdfViewer();
            } else if (e.key === 'ArrowLeft') {
                updatePdfModalPage(pdfViewerState.currentPage - 1);
            } else if (e.key === 'ArrowRight') {
                updatePdfModalPage(pdfViewerState.currentPage + 1);
            }
        }
    });
});
