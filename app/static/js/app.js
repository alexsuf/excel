let currentSessionId = null;
let currentStep = 1;
let extractedData = null;
let extractStarted = false;
let extractPollInterval = null;
let validationResult = null;

const steps = ['template', 'dictionary', 'documents', 'extract', 'validate', 'generate'];

async function apiCall(endpoint, options = {}, timeoutMs = 150000) {
    const controller = new AbortController();
    const signal = controller.signal;
    const timer = setTimeout(() => controller.abort(), timeoutMs);
    try {
        const response = await fetch(`/api${endpoint}`, {
            headers: {'Content-Type': 'application/json', ...options.headers},
            signal,
            ...options
        });
        clearTimeout(timer);
        const data = await response.json();
        if (!response.ok) {
            const errMsg = data.error || `Request failed with status ${response.status}`;
            throw new Error(errMsg);
        }
        return data;
    } catch (e) {
        clearTimeout(timer);
        if (e.name === 'AbortError') {
            throw new Error('Request timed out');
        }
        throw e;
    }
}

function showStep(stepNumber) {
    steps.forEach((step, index) => {
        const panel = document.getElementById(`step-${step}`);
        const stepEl = document.querySelector(`.step[data-step="${index + 1}"]`);
        if (index + 1 === stepNumber) {
            panel.classList.add('active');
            stepEl.classList.add('active');
            stepEl.classList.remove('completed');
        } else if (index + 1 < stepNumber) {
            panel.classList.remove('active');
            stepEl.classList.add('completed');
            stepEl.classList.remove('active');
        } else {
            panel.classList.remove('active');
            stepEl.classList.remove('active', 'completed');
        }
    });
    currentStep = stepNumber;
}

function showToast(message, type = 'info') {
    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;
    toast.textContent = message;
    document.body.appendChild(toast);
    setTimeout(() => toast.remove(), 3000);
}

function formatJson(obj) {
    return JSON.stringify(obj, null, 2);
}

function jsonForAttr(value) {
    return JSON.stringify(value)
        .replace(/&/g, '&amp;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;');
}

async function initSession() {
    const result = await apiCall('/session', {method: 'POST'});
    if (result.session_id) {
        currentSessionId = result.session_id;
        document.getElementById('session-id').textContent = currentSessionId;
        document.getElementById('session-badge').classList.remove('hidden');
        showStep(1);
    }
}

function setupUploadZone(zoneId, fileId, onFilesSelected) {
    const zone = document.getElementById(zoneId);
    const fileInput = document.getElementById(fileId);
    zone.addEventListener('click', () => fileInput.click());
    zone.addEventListener('dragover', (e) => { e.preventDefault(); zone.classList.add('drag-over'); });
    zone.addEventListener('dragleave', () => zone.classList.remove('drag-over'));
    zone.addEventListener('drop', (e) => {
        e.preventDefault();
        zone.classList.remove('drag-over');
        fileInput.files = e.dataTransfer.files;
        onFilesSelected(fileInput.files);
    });
    fileInput.addEventListener('change', () => onFilesSelected(fileInput.files));
}

function renderNamedRanges(namedRanges) {
    const container = document.getElementById('named-ranges-list');
    container.innerHTML = '';
    Object.entries(namedRanges).forEach(([name, nr]) => {
        const item = document.createElement('div');
        const tag = nr.is_bookmark ? 'bookmark' : (nr.is_table ? 'table' : 'field');
        item.className = `named-range-item ${tag}`;
        const iconMap = {table: 'fa-table', bookmark: 'fa-bookmark', field: 'fa-regular fa-square'};
        item.innerHTML = `
            <div class="nr-icon"><i class="fas ${iconMap[tag]}"></i></div>
            <div class="nr-info">
                <div class="nr-name">${name}</div>
                <div class="nr-details">Sheet: ${nr.sheet_name} | Range: ${nr.cell_range}${nr.is_bookmark ? ' (bookmark)' : ''}</div>
            </div>
            <span class="nr-type ${tag}">${tag.charAt(0).toUpperCase() + tag.slice(1)}</span>
        `;
        container.appendChild(item);
    });
}

function renderMappings(mappings) {
    const tbody = document.querySelector('#mappings-table tbody');
    tbody.innerHTML = '';
    Object.entries(mappings).forEach(([name, mapping]) => {
        const tr = document.createElement('tr');
        tr.innerHTML = `
            <td>${name}</td>
            <td>${mapping.description}</td>
            <td>${mapping.entity_type || '-'}</td>
            <td>${mapping.data_type}</td>
            <td>${mapping.required ? '<i class="fas fa-check text-success"></i>' : '-'}</td>
        `;
        tbody.appendChild(tr);
    });
}

function renderDocumentsList(files) {
    const list = document.getElementById('documents-files');
    list.innerHTML = '';
    Array.from(files).forEach(file => {
        const li = document.createElement('li');
        const icon = file.type.includes('pdf') ? 'fa-file-pdf' :
                     file.type.includes('word') ? 'fa-file-word' :
                     file.type.includes('image') ? 'fa-file-image' : 'fa-file-alt';
        li.innerHTML = `<i class="fas ${icon}"></i> ${file.name} (${(file.size / 1024).toFixed(1)} KB)`;
        list.appendChild(li);
    });
    document.getElementById('documents-list').classList.remove('hidden');
}

function renderExtractedJson(data) {
    document.getElementById('extracted-json').textContent = formatJson(data);
}

function renderValidationSummary(result) {
    const summary = document.getElementById('validation-summary');
    const fieldsValid = Object.values(result.fields).filter(f => f.is_valid).length;
    const fieldsTotal = Object.keys(result.fields).length;
    const tablesValid = Object.values(result.tables).filter(t => t.is_valid).length;
    const tablesTotal = Object.keys(result.tables).length;
    const allValid = result.is_valid;
    summary.innerHTML = `
        <div class="summary-card ${allValid ? 'valid' : 'invalid'}">
            <div class="summary-value" style="color: ${allValid ? 'var(--success)' : 'var(--danger)'}">${allValid ? '✓' : '✗'}</div>
            <div class="summary-label">Overall</div>
        </div>
        <div class="summary-card ${fieldsValid === fieldsTotal ? 'valid' : 'invalid'}">
            <div class="summary-value">${fieldsValid}/${fieldsTotal}</div>
            <div class="summary-label">Fields Valid</div>
        </div>
        <div class="summary-card ${tablesValid === tablesTotal ? 'valid' : 'invalid'}">
            <div class="summary-value">${tablesValid}/${tablesTotal}</div>
            <div class="summary-label">Tables Valid</div>
        </div>
        <div class="summary-card warning">
            <div class="summary-value">${result.errors.length}</div>
            <div class="summary-label">Errors</div>
        </div>
    `;
}

function renderFields(fields) {
    const grid = document.getElementById('fields-grid');
    grid.innerHTML = '';
    Object.entries(fields).forEach(([name, field]) => {
        const card = document.createElement('div');
        card.className = `field-card ${field.is_valid ? 'valid' : 'invalid'}`;
        const valueStr = field.value === null || field.value === undefined ? '(empty)' : String(field.value);
        card.innerHTML = `
            <div class="field-header">
                <span class="field-name">${name}</span>
                <span class="field-type">${field.data_type}</span>
            </div>
            <div class="field-value ${!field.value ? 'empty' : ''}"></div>
            ${field.errors.length ? `<div class="field-errors"><ul>${field.errors.map(e => `<li>${escapeHtml(e)}</li>`).join('')}</ul></div>` : ''}
            <div class="field-actions">
                <button class="btn btn-secondary btn-sm edit-field-btn"
                    data-type="field" data-name="${name}" data-value='${jsonForAttr(field.value)}'>
                    <i class="fas fa-edit"></i> Edit
                </button>
            </div>
        `;
        card.querySelector('.field-value').textContent = valueStr;
        grid.appendChild(card);
    });
}

function renderTables(tables) {
    const container = document.getElementById('tables-container');
    container.innerHTML = '';
    Object.entries(tables).forEach(([name, table]) => {
        const card = document.createElement('div');
        card.className = 'table-card';
        let rowsHtml = '';
        table.rows.forEach((row, rowIdx) => {
            let cellsHtml = '';
            table.headers.forEach(header => {
                const cellValue = row.cells[header] === null || row.cells[header] === undefined ? '' : String(row.cells[header]);
                cellsHtml += `<td class="editable edit-table-cell-btn"
                    data-table="${name}" data-row="${rowIdx}" data-header="${header}"
                    data-value='${jsonForAttr(row.cells[header])}'>${escapeHtml(cellValue)}</td>`;
            });
            rowsHtml += `<tr class="${row.is_valid ? '' : 'invalid'}">${cellsHtml}</tr>`;
        });
        card.innerHTML = `
            <div class="table-header">
                <span class="table-title">${name}</span>
                <span class="table-row-count">${table.rows.length} rows</span>
            </div>
            <div class="table-wrapper">
                <table class="data-table">
                    <thead><tr>${table.headers.map(h => `<th>${escapeHtml(h)}</th>`).join('')}</tr></thead>
                    <tbody>${rowsHtml}</tbody>
                </table>
            </div>
        `;
        container.appendChild(card);
    });
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

let editModalContext = null;

function openEditModal(type, name, args) {
    const modal = document.getElementById('edit-modal');
    const modalTitle = document.getElementById('modal-title');
    const modalFieldLabel = document.getElementById('modal-field-label');
    const modalFieldValue = document.getElementById('modal-field-value');
    const modalTableEditor = document.getElementById('modal-table-editor');
    const modalErrors = document.getElementById('modal-field-errors');
    modalErrors.innerHTML = '';
    modalFieldValue.value = '';
    modalTableEditor.classList.add('hidden');
    if (type === 'field') {
        modalTitle.textContent = 'Edit Field';
        modalFieldLabel.textContent = name;
        modalFieldValue.value = args.value === null || args.value === undefined ? '' : String(args.value);
        editModalContext = {type: 'field', name};
    } else if (type === 'table') {
        modalTitle.textContent = 'Edit Table Cell';
        modalFieldLabel.textContent = `${name} [Row ${args.row}] - ${args.header}`;
        modalFieldValue.value = args.value === null || args.value === undefined ? '' : String(args.value);
        editModalContext = {type: 'table', name, rowIndex: args.row, header: args.header};
    }
    modal.classList.add('active');
    modalFieldValue.focus();
}

async function saveEditModal() {
    const modal = document.getElementById('edit-modal');
    const newValue = document.getElementById('modal-field-value').value;
    if (!editModalContext) return;
    try {
        let result;
        if (editModalContext.type === 'field') {
            result = await apiCall(`/session/${currentSessionId}/field`, {
                method: 'PUT',
                body: JSON.stringify({field_name: editModalContext.name, value: newValue})
            });
        } else if (editModalContext.type === 'table') {
            const rowData = {};
            rowData[editModalContext.header] = newValue;
            result = await apiCall(`/session/${currentSessionId}/table/${editModalContext.name}/row/${editModalContext.rowIndex}`, {
                method: 'PUT',
                body: JSON.stringify(rowData)
            });
        }
        if (result.success) {
            showToast('Saved successfully', 'success');
            modal.classList.remove('active');
            await loadValidationStep();
        } else {
            showToast(result.error || 'Failed to save', 'error');
            document.getElementById('modal-field-errors').innerHTML = `<ul><li>${escapeHtml(result.error)}</li></ul>`;
        }
    } catch (e) {
        showToast('Error: ' + e.message, 'error');
    }
}

function closeEditModal() {
    document.getElementById('edit-modal').classList.remove('active');
    editModalContext = null;
}

async function loadTemplateStep() {
    setupUploadZone('template-upload-zone', 'template-file', async (files) => {
        if (files.length === 0) return;
        const formData = new FormData();
        formData.append('file', files[0]);
        const response = await fetch(`/api/session/${currentSessionId}/template`, {method: 'POST', body: formData});
        const result = await response.json();
        if (result.success) {
            renderNamedRanges(result.named_ranges);
            document.getElementById('template-info').classList.remove('hidden');
            document.getElementById('btn-next-dictionary').disabled = false;
            showToast('Шаблон загружен успешно', 'success');
        } else {
            showToast(result.error || 'Failed to load template', 'error');
        }
    });
}

async function loadDictionaryStep() {
    setupUploadZone('dictionary-upload-zone', 'dictionary-file', async (files) => {
        if (files.length === 0) return;
        const formData = new FormData();
        formData.append('file', files[0]);
        const response = await fetch(`/api/session/${currentSessionId}/dictionary`, {method: 'POST', body: formData});
        const result = await response.json();
        if (result.success) {
            renderMappings(result.mappings);
            document.getElementById('dictionary-info').classList.remove('hidden');
            document.getElementById('btn-next-documents').disabled = false;
            showToast('Dictionary loaded successfully', 'success');
        } else {
            showToast(result.error || 'Failed to load dictionary', 'error');
        }
    });
}

async function loadDocumentsStep() {
    setupUploadZone('documents-upload-zone', 'documents-file', async (files) => {
        if (files.length === 0) return;
        const formData = new FormData();
        Array.from(files).forEach(f => formData.append('files', f));
        const response = await fetch(`/api/session/${currentSessionId}/documents`, {method: 'POST', body: formData});
        const result = await response.json();
        if (result.success) {
            renderDocumentsList(files);
            document.getElementById('btn-next-extract').disabled = false;
            showToast(`${files.length} document(s) uploaded`, 'success');
        } else {
            showToast(result.error || 'Failed to upload documents', 'error');
        }
    });
}

async function startExtraction() {
    if (extractStarted) {
        console.warn('[startExtraction] Extraction is already running; ignoring duplicate click.');
        return;
    }
    if (!currentSessionId) {
        showToast('Сессия не создана. Обновите страницу и попробуйте снова.', 'error');
        console.error('[startExtraction] currentSessionId is empty');
        return;
    }

    const spinner = document.getElementById('extraction-spinner');
    const progress = document.getElementById('extraction-progress');
    const progressFill = document.getElementById('extraction-progress-fill');
    const status = document.getElementById('extraction-status');
    const resultPanel = document.getElementById('extraction-result');
    const jsonViewer = document.getElementById('extracted-json');
    const startButtons = [
        document.getElementById('btn-next-extract'),
        document.getElementById('btn-manual-extract')
    ].filter(Boolean);

    const missing = [];
    if (!spinner) missing.push('extraction-spinner');
    if (!progress) missing.push('extraction-progress');
    if (!progressFill) missing.push('extraction-progress-fill');
    if (!status) missing.push('extraction-status');
    if (!resultPanel) missing.push('extraction-result');
    if (!jsonViewer) missing.push('extracted-json');
    if (missing.length) {
        console.error('[startExtraction] Missing required HTML elements:', missing);
        showToast(`Ошибка интерфейса: отсутствуют элементы ${missing.join(', ')}`, 'error');
        return;
    }

    extractStarted = true;
    let extractionCompleted = false;
    let pollCount = 0;
    startButtons.forEach(btn => btn.disabled = true);
    spinner.classList.remove('hidden');
    progress.classList.remove('hidden');
    resultPanel.classList.add('hidden');
    progressFill.style.width = '2%';
    status.textContent = 'Отправка запроса на сервер…';
    jsonViewer.textContent = '';

    if (extractPollInterval) clearInterval(extractPollInterval);
    extractPollInterval = setInterval(() => {
        if (extractionCompleted) return;
        pollCount++;
        status.textContent = `LLM обрабатывает документы… (${pollCount} сек.)`;
        progressFill.style.width = `${Math.min(5 + pollCount, 90)}%`;
    }, 1000);

    try {
        console.log('[startExtraction] POST /session/' + currentSessionId + '/extract');
        const result = await apiCall(`/session/${currentSessionId}/extract`, { method: 'POST' }, 300000);
        extractionCompleted = true;
        clearInterval(extractPollInterval);
        extractPollInterval = null;

        if (!result || result.success !== true) {
            throw new Error((result && result.error) || 'Сервер не подтвердил успешное завершение экстракции');
        }

        extractedData = result.extracted_data ?? result.data ?? null;
        progressFill.style.width = '100%';
        status.textContent = 'Экстракция завершена';
        jsonViewer.textContent = JSON.stringify(extractedData, null, 2);
        resultPanel.classList.remove('hidden');
        showToast('Экстракция завершена', 'success');

        setTimeout(async () => {
            try {
                showStep(5);
                await loadValidationStep();
            } catch (e) {
                console.error('[startExtraction] Validation loading failed:', e);
                showToast('Данные извлечены, но не удалось загрузить валидацию: ' + e.message, 'error');
            }
        }, 500);
    } catch (e) {
        extractionCompleted = true;
        if (extractPollInterval) clearInterval(extractPollInterval);
        extractPollInterval = null;
        console.error('[startExtraction] FAILED:', e);
        spinner.classList.add('hidden');
        progressFill.style.width = '100%';
        status.textContent = 'Ошибка экстракции: ' + e.message;
        resultPanel.querySelector('h3').textContent = 'Ошибка экстракции';
        try {
            const logs = await apiCall(`/session/${currentSessionId}/logs`, { method: 'GET' }, 15000);
            jsonViewer.textContent = logs.success && Array.isArray(logs.logs) && logs.logs.length
                ? logs.logs.join('\n')
                : 'Ошибка: ' + e.message;
        } catch (logError) {
            console.warn('[startExtraction] Could not load server logs:', logError);
            jsonViewer.textContent = 'Ошибка: ' + e.message;
        }
        resultPanel.classList.remove('hidden');
        showToast('Ошибка извлечения: ' + e.message, 'error');
    } finally {
        extractStarted = false;
        startButtons.forEach(btn => btn.disabled = false);
        if (extractionCompleted) spinner.classList.add('hidden');
    }
}

async function loadExtractStep() {
    const btn = document.getElementById('btn-next-extract');
    const manualBtn = document.getElementById('btn-manual-extract');
    console.log('loadExtractStep: ready, waiting for user click');
    console.log('  btn-next-extract:', !!btn, 'disabled:', btn ? btn.disabled : 'N/A');
    console.log('  btn-manual-extract:', !!manualBtn);
    if (btn && !btn.dataset.handlerAttached) {
        btn.dataset.handlerAttached = 'true';
        btn.addEventListener('click', function(e) {
            console.log('[ADD-EVENT-LISTENER] btn-next-extract clicked');
            showStep(4);
            setTimeout(() => {
                console.log('[ADD-EVENT-LISTENER] setTimeout firing, startExtraction type:', typeof startExtraction);
                if (typeof startExtraction === 'function') {
                    startExtraction();
                } else {
                    console.error('[ADD-EVENT-LISTENER] startExtraction is NOT a function!');
                }
            }, 100);
        });
        console.log('loadExtractStep: addEventListener attached to btn-next-extract');
    }
    if (manualBtn && !manualBtn.dataset.handlerAttached) {
        manualBtn.dataset.handlerAttached = 'true';
        manualBtn.addEventListener('click', function(e) {
            console.log('[ADD-EVENT-LISTENER] btn-manual-extract clicked');
            showStep(4);
            setTimeout(() => {
                if (typeof startExtraction === 'function') {
                    startExtraction();
                } else {
                    console.error('[ADD-EVENT-LISTENER] startExtraction is NOT a function!');
                }
            }, 100);
        });
        console.log('loadExtractStep: addEventListener attached to btn-manual-extract');
    }
}

async function loadValidationStep() {
    const result = await apiCall(`/session/${currentSessionId}/validate`, {method: 'POST'});
    if (result.success) {
        validationResult = result;
        renderValidationSummary(result);
        renderFields(result.fields);
        renderTables(result.tables);
        document.getElementById('raw-json').textContent = formatJson(result);
        const hasErrors = !result.is_valid;
        document.getElementById('btn-next-generate').disabled = hasErrors;
        if (hasErrors) {
            showToast('Validation completed with errors. Please fix them before generating.', 'warning');
        } else {
            showToast('Validation passed', 'success');
        }
    } else {
        showToast(result.error || 'Validation failed', 'error');
    }
}

function setupTabs() {
    document.querySelectorAll('.tab-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
            document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
            btn.classList.add('active');
            document.getElementById(`tab-${btn.dataset.tab}`).classList.add('active');
        });
    });
}

async function loadGenerateStep() {
    const btn = document.getElementById('btn-generate');
    if (btn && btn.dataset.generateHandlerAttached) return;
    if (btn) btn.dataset.generateHandlerAttached = 'true';
    const spinner = document.getElementById('generation-spinner');
    const progress = document.getElementById('generation-progress');
    const progressFill = document.getElementById('generation-progress-fill');
    const status = document.getElementById('generation-status');
    const resultPanel = document.getElementById('generation-result');
    const downloadBtn = document.getElementById('btn-download');
    btn.addEventListener('click', async () => {
        const filename = document.getElementById('output-filename').value || 'output.xlsx';
        btn.disabled = true;
        spinner.classList.remove('hidden');
        progress.classList.remove('hidden');
        resultPanel.classList.add('hidden');
        let progressVal = 0;
        const progressInterval = setInterval(() => {
            progressVal = Math.min(progressVal + 20, 90);
            progressFill.style.width = `${progressVal}%`;
        }, 200);
        try {
            const result = await apiCall(`/session/${currentSessionId}/generate`, {
                method: 'POST',
                body: JSON.stringify({filename})
            });
            clearInterval(progressInterval);
            progressFill.style.width = '100%';
            if (result.success) {
                document.getElementById('output-path').textContent = result.output_path;
                resultPanel.classList.remove('hidden');
                showToast('File generated successfully', 'success');
            } else {
                showToast(result.error || 'Generation failed', 'error');
            }
        } catch (e) {
            clearInterval(progressInterval);
            showToast('Error: ' + e.message, 'error');
        } finally {
            btn.disabled = false;
            spinner.classList.add('hidden');
        }
    });
    downloadBtn.addEventListener('click', () => {
        window.location.href = `/api/download/${currentSessionId}/${document.getElementById('output-filename').value || 'output.xlsx'}`;
    });
}

document.addEventListener('DOMContentLoaded', async () => {
    try {
        console.log('DOMContentLoaded started');
        await initSession();
        console.log('initSession done');
        setupTabs();
        console.log('setupTabs done');
        await loadTemplateStep();
        console.log('loadTemplateStep done');
        await loadDictionaryStep();
        console.log('loadDictionaryStep done');
        await loadDocumentsStep();
        console.log('loadDocumentsStep done');
        await loadExtractStep();
        console.log('loadExtractStep done');
        await loadGenerateStep();
        console.log('loadGenerateStep done');

        document.getElementById('menu-start').addEventListener('click', () => {
            location.reload();
        });

        document.querySelectorAll('.menu-item').forEach(item => {
            item.addEventListener('click', () => {
                document.querySelectorAll('.menu-item').forEach(i => i.classList.remove('active'));
                item.classList.add('active');
            });
        });

        console.log('Attaching navigation handlers...');
        document.getElementById('btn-next-dictionary').addEventListener('click', () => {
            console.log('btn-next-dictionary clicked');
            showStep(2);
        });
        document.getElementById('btn-next-documents').addEventListener('click', () => {
            console.log('btn-next-documents clicked');
            showStep(3);
        });
        document.getElementById('btn-next-validate').addEventListener('click', () => {
            console.log('btn-next-validate clicked');
            showStep(5);
            loadValidationStep();
        });
        document.getElementById('btn-next-generate').addEventListener('click', () => {
            console.log('btn-next-generate clicked');
            showStep(6);
        });
        console.log('Button handlers attached');

        document.getElementById('modal-close').addEventListener('click', closeEditModal);
        document.getElementById('modal-cancel').addEventListener('click', closeEditModal);
        document.getElementById('modal-save').addEventListener('click', saveEditModal);
        document.getElementById('edit-modal').addEventListener('click', (e) => {
            if (e.target === document.getElementById('edit-modal')) closeEditModal();
        });

        document.body.addEventListener('click', (e) => {
            const editBtn = e.target.closest('.edit-field-btn');
            if (editBtn) {
                try {
                    const value = JSON.parse(editBtn.dataset.value);
                    openEditModal('field', editBtn.dataset.name, {value});
                } catch (err) {
                    openEditModal('field', editBtn.dataset.name, {value: editBtn.dataset.value});
                }
                return;
            }
            const cellBtn = e.target.closest('.edit-table-cell-btn');
            if (cellBtn) {
                try {
                    const value = JSON.parse(cellBtn.dataset.value);
                    openEditModal('table', cellBtn.dataset.table, {
                        row: parseInt(cellBtn.dataset.row),
                        header: cellBtn.dataset.header,
                        value
                    });
                } catch (err) {
                    openEditModal('table', cellBtn.dataset.table, {
                        row: parseInt(cellBtn.dataset.row),
                        header: cellBtn.dataset.header,
                        value: cellBtn.dataset.value
                    });
                }
            }
        });

        const toastStyle = document.createElement('style');
        toastStyle.textContent = `
            .toast { position:fixed; bottom:24px; right:24px; padding:12px 24px; border-radius:8px; color:#fff; font-weight:500; z-index:9999; animation: slideIn 0.3s ease; }
            .toast-success { background:var(--success,#10b981); }
            .toast-error { background:var(--danger,#ef4444); }
            .toast-warning { background:var(--warning,#f59e0b); }
            .toast-info { background:var(--primary,#2563eb); }
            .text-success { color:var(--success,#10b981); }
            @keyframes slideIn { from { transform:translateX(100px); opacity:0; } to { transform:translateX(0); opacity:1; } }
        `;
        document.head.appendChild(toastStyle);
        console.log('DOMContentLoaded completed successfully');
    } catch (err) {
        console.error('DOMContentLoaded error:', err);
    }
});
