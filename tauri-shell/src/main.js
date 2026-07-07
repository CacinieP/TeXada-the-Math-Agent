// TeXada Shell Frontend
(async () => {
  const isTauri = typeof window.__TAURI__ !== 'undefined';
  const invoke = isTauri ? window.__TAURI__.core.invoke : null;
  const API_BASE = await window.TeXadaRuntime.resolveApiBase({ invoke });
  const DEFAULT_REQUEST_TIMEOUT_MS = 120000;

  // ── State ──
  let currentTab = 'nl';
  let renderMode = 'katex'; // 'katex' | 'latex'
  let lastResult = null;
  let isProcessing = false;
  let allShorthands = [];
  let runtimeConfig = {
    maxOcrBytes: null,
    allowedImageTypes: new Set(),
  };
  let requestTimeoutMs = DEFAULT_REQUEST_TIMEOUT_MS;

  // ── DOM refs ──
  const els = {
    nlInput: document.getElementById('nl-input'),
    nlIntent: document.getElementById('nl-intent'),
    nlProcessing: document.getElementById('nl-processing'),
    nlResult: document.getElementById('nl-result'),
    renderPreview: document.getElementById('render-preview'),
    latexPreview: document.getElementById('latex-preview'),
    latexCode: document.getElementById('latex-code'),
    markdownCode: document.getElementById('markdown-code'),
    resultValid: document.getElementById('result-valid'),
    resultSource: document.getElementById('result-source'),
    katexSection: document.getElementById('katex-result-section'),
    latexSection: document.getElementById('latex-result-section'),
    statusDot: document.getElementById('status-dot'),
    tabBar: document.getElementById('tab-bar'),
    shorthandGrid: document.getElementById('shorthand-grid'),
    shorthandSearch: document.getElementById('shorthand-search'),
    shorthandKeyInput: document.getElementById('shorthand-key-input'),
    shorthandValueInput: document.getElementById('shorthand-value-input'),
    shorthandSaveStatus: document.getElementById('shorthand-save-status'),
    historyList: document.getElementById('history-list'),
    ocrDrop: document.getElementById('ocr-drop'),
    ocrPreview: document.getElementById('ocr-preview'),
    ocrThumb: document.getElementById('ocr-thumb'),
    ocrFilename: document.getElementById('ocr-filename'),
    ocrSize: document.getElementById('ocr-size'),
    ocrProcessing: document.getElementById('ocr-processing'),
    ocrResult: document.getElementById('ocr-result'),
    completeInput: document.getElementById('complete-input'),
    completeProcessing: document.getElementById('complete-processing'),
    completeResult: document.getElementById('complete-result'),
    backendSelect: document.getElementById('backend-select'),
    ollamaHostInput: document.getElementById('ollama-host-input'),
    localModelInput: document.getElementById('local-model-input'),
    localVisionModelInput: document.getElementById('local-vision-model-input'),
    openaiEndpointInput: document.getElementById('openai-endpoint-input'),
    openaiModelInput: document.getElementById('openai-model-input'),
    openaiVisionModelInput: document.getElementById('openai-vision-model-input'),
    openaiKeyInput: document.getElementById('openai-key-input'),
    backendSaveStatus: document.getElementById('backend-save-status'),
    apiBaseValue: document.getElementById('api-base-value'),
  };

  // ── Helpers ──
  function $(sel) { return document.querySelector(sel); }
  function $$(sel) { return document.querySelectorAll(sel); }

  function isMacPlatform() {
    return /Mac|iPhone|iPad|iPod/.test(navigator.platform || '');
  }

  function applyPlatformLabels() {
    const shortcuts = {
      wake: isMacPlatform() ? '⌥⌘T' : 'Ctrl+Alt+T',
      mode: isMacPlatform() ? '⌘K' : 'Ctrl+K',
    };
    document.querySelectorAll('[data-shortcut]').forEach(el => {
      const value = shortcuts[el.dataset.shortcut];
      if (value) el.textContent = value;
    });
  }

  function setIntent(icon, message) {
    els.nlIntent.textContent = '';
    const iconEl = document.createElement('span');
    iconEl.className = 'intent-icon';
    iconEl.textContent = icon;
    els.nlIntent.append(iconEl, ' ' + message);
  }

  function setStatus(online, text) {
    const dot = els.statusDot.querySelector('.dot');
    const span = els.statusDot.querySelector('span');
    dot.className = 'dot' + (online ? '' : ' offline');
    span.textContent = text || (online ? 'Online' : 'Offline');
  }

  async function apiJson(path, options = {}) {
    const method = options.method || 'GET';
    const body = options.body;

    if (isTauri) {
      return await invoke('api_json', {
        method,
        path,
        body: body === undefined ? null : body,
      });
    }

    const fetchOptions = { method };
    const controller = typeof AbortController !== 'undefined' ? new AbortController() : null;
    let timer = null;
    if (controller) {
      fetchOptions.signal = controller.signal;
      timer = setTimeout(() => controller.abort(), requestTimeoutMs);
    }
    if (body !== undefined) {
      fetchOptions.headers = { 'Content-Type': 'application/json' };
      fetchOptions.body = JSON.stringify(body);
    }
    try {
      const res = await fetch(`${API_BASE}${path}`, fetchOptions);
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        throw new Error(data.detail || `HTTP ${res.status}`);
      }
      return data;
    } catch (e) {
      if (e && e.name === 'AbortError') {
        throw new Error(`请求超时（${Math.round(requestTimeoutMs / 1000)}s）`);
      }
      throw e;
    } finally {
      if (timer) clearTimeout(timer);
    }
  }

  async function loadRuntimeConfig() {
    if (els.apiBaseValue) els.apiBaseValue.textContent = API_BASE;
    try {
      const cfg = await apiJson('/api/runtime');
      runtimeConfig = {
        maxOcrBytes: Number(cfg.max_ocr_bytes) || null,
        allowedImageTypes: new Set(cfg.allowed_image_mime_types || []),
      };
      requestTimeoutMs = Number(cfg.request_timeout_ms) || DEFAULT_REQUEST_TIMEOUT_MS;
      if (els.apiBaseValue) els.apiBaseValue.textContent = cfg.api_base_url || API_BASE;
    } catch (e) {
      runtimeConfig = { maxOcrBytes: null, allowedImageTypes: new Set() };
    }
  }

  async function checkBackend() {
    try {
      const info = isTauri ? await invoke('get_status') : await apiJson('/api/status');
      const isOnline = info.status === 'ok' || info.status === 'ready' || info.status === 'no_model';
      const text = info.status === 'ready' || info.status === 'ok'
        ? (info.model || 'Ready')
        : (info.message || info.status);
      setStatus(isOnline, text);
    } catch (e) {
      if (isTauri) {
        try {
          const info = await invoke('get_status');
          setStatus(info.status === 'ok', info.status === 'ok' ? info.model || 'Ready' : 'Error');
        } catch (e2) {
          setStatus(false, 'No API');
        }
      } else {
        setStatus(false, 'No API');
      }
    }
  }

  // ── Tabs ──
  function switchTab(tab) {
    currentTab = tab;
    $$('.tab-item').forEach(t => t.classList.toggle('active', t.dataset.tab === tab));
    $$('.tab-content').forEach(c => c.classList.toggle('active', c.id === 'tab-' + tab));

    if (tab === 'shorthand') loadShorthands();
    if (tab === 'history') loadHistory();
    if (tab === 'nl') setTimeout(() => els.nlInput.focus(), 50);
    if (tab === 'complete') setTimeout(() => els.completeInput.focus(), 50);
    if (tab === 'ocr') setupOcr();
    if (tab === 'settings') loadBackendSettings();
  }

  els.tabBar.addEventListener('click', e => {
    const item = e.target.closest('.tab-item');
    if (item) switchTab(item.dataset.tab);
  });

  // ── API helpers ──
  async function apiConvert(text) {
    if (isTauri) {
      return await invoke('convert_text', { text, renderMode });
    }
    return await apiJson('/api/convert', {
      method: 'POST',
      body: { text, render_mode: renderMode },
    });
  }

  async function apiComplete(text) {
    if (isTauri) {
      return await invoke('complete_latex', { text, renderMode });
    }
    return await apiJson('/api/complete', {
      method: 'POST',
      body: { text, render_mode: renderMode },
    });
  }

  async function apiOcr(imageData) {
    if (isTauri) {
      return await invoke('convert_image', { image: imageData, renderMode });
    }
    const form = new FormData();
    form.append('image', new Blob([imageData], { type: 'image/png' }), 'upload.png');
    const controller = typeof AbortController !== 'undefined' ? new AbortController() : null;
    let timer = null;
    if (controller) timer = setTimeout(() => controller.abort(), requestTimeoutMs);
    let res;
    try {
      res = await fetch(`${API_BASE}/api/ocr?render_mode=${encodeURIComponent(renderMode)}`, {
        method: 'POST',
        body: form,
        signal: controller ? controller.signal : undefined,
      });
    } catch (e) {
      if (e && e.name === 'AbortError') {
        throw new Error(`请求超时（${Math.round(requestTimeoutMs / 1000)}s）`);
      }
      throw e;
    } finally {
      if (timer) clearTimeout(timer);
    }
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      throw new Error(body.detail || `HTTP ${res.status}`);
    }
    return await res.json();
  }

  async function apiGetBackendSettings() {
    return await apiJson('/api/settings/backend');
  }

  async function apiSaveBackendSettings(payload) {
    return await apiJson('/api/settings/backend', {
      method: 'POST',
      body: payload,
    });
  }

  async function apiAddShorthand(key, value) {
    return await apiJson('/api/shorthands', {
      method: 'POST',
      body: { key, value },
    });
  }

  async function apiDeleteShorthand(key) {
    return await apiJson(`/api/shorthands/${encodeURIComponent(key)}`, {
      method: 'DELETE',
    });
  }

  // ── NL Convert ──
  async function doConvert() {
    const text = els.nlInput.value.trim();
    if (!text || isProcessing) return;

    isProcessing = true;
    els.nlProcessing.classList.add('active');
    els.nlResult.style.display = 'none';
    setIntent('⏳', '处理中…');

    try {
      const res = await apiConvert(text);
      lastResult = res;
      showResult(res);
      saveHistory(text, res.latex);
    } catch (e) {
      showError(String(e));
    } finally {
      isProcessing = false;
      els.nlProcessing.classList.remove('active');
    }
  }

  function showResult(res) {
    // 如果之前被 showError 替换过，恢复原始结构
    if (els.nlResult.dataset.originalHtml) {
      els.nlResult.innerHTML = els.nlResult.dataset.originalHtml;
      delete els.nlResult.dataset.originalHtml;
      // 重新获取可能被销毁的子元素引用
      els.latexCode = document.getElementById('latex-code');
      els.markdownCode = document.getElementById('markdown-code');
      els.renderPreview = document.getElementById('render-preview');
      els.latexPreview = document.getElementById('latex-preview');
      els.resultValid = document.getElementById('result-valid');
      els.resultSource = document.getElementById('result-source');
      els.katexSection = document.getElementById('katex-result-section');
      els.latexSection = document.getElementById('latex-result-section');
    }
    els.nlResult.style.display = 'block';
    els.latexCode.textContent = res.latex;
    els.markdownCode.textContent = `$$${res.latex}$$`;

    els.resultValid.className = 'valid-badge ' + (res.valid ? 'ok' : 'err');
    els.resultValid.textContent = res.valid ? '✓ Valid' : '✗ Invalid';
    els.resultSource.className = 'source-badge ' + (res.source === 'shorthand' ? 'shorthand' : 'model');
    els.resultSource.textContent = res.source === 'shorthand' ? '⚡ shorthand' : '🤖 model';

    setIntent('∫', `${res.intent || 'unknown'} · ${Number(res.latency_ms || 0).toFixed(1)}ms`);

    updateRender();
  }

  function updateRender() {
    if (!lastResult) return;
    if (renderMode === 'katex' && lastResult.katex_html) {
      els.katexSection.style.display = 'block';
      els.latexSection.style.display = 'none';
      els.renderPreview.innerHTML = lastResult.katex_html;
      // Re-render with KaTeX JS if needed
      if (window.katex) {
        try {
          els.renderPreview.innerHTML = '';
          window.katex.render(lastResult.latex, els.renderPreview, {
            throwOnError: false,
            displayMode: true,
          });
        } catch (e) {
          els.renderPreview.textContent = lastResult.latex;
        }
      }
    } else {
      els.katexSection.style.display = 'none';
      els.latexSection.style.display = 'block';
      els.latexPreview.innerHTML = highlightLatex(lastResult.latex);
    }
  }

  function highlightLatex(latex) {
    // Simple syntax highlighting for pure latex view
    let html = latex
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/(\\[a-zA-Z]+)/g, '<span class="latex-structural">$1</span>')
      .replace(/([{}])/g, '<span class="latex-delimiter">$1</span>')
      .replace(/([～^])/g, '<span class="latex-operator">$1</span>');
    return html;
  }

  function showError(msg) {
    els.nlResult.style.display = 'block';
    // 保存原始结构（首次出错时）
    if (!els.nlResult.dataset.originalHtml) {
      els.nlResult.dataset.originalHtml = els.nlResult.innerHTML;
    }
    els.nlResult.innerHTML = `<div class="error-box" style="padding:16px"><span class="icon">⚠️</span><div>${escapeHtml(msg)}</div></div>`;
  }

  // ── Clipboard ──
  async function copyToClipboard(text) {
    if (isTauri) {
      await invoke('write_clipboard', { text });
    } else {
      await navigator.clipboard.writeText(text);
    }
  }

  async function pasteFromClipboard() {
    if (isTauri) {
      try {
        return await invoke('read_clipboard');
      } catch (e) {
        return '';
      }
    } else {
      try {
        return await navigator.clipboard.readText();
      } catch (e) {
        return '';
      }
    }
  }

  async function copyMain() {
    if (!lastResult) return;
    await copyToClipboard(lastResult.copy_text || lastResult.latex);
    if (isTauri) await invoke('hide_window');
  }

  // ── Keyboard ──
  document.addEventListener('keydown', e => {
    // Esc → hide
    if (e.key === 'Escape') {
      e.preventDefault();
      if (isTauri) invoke('hide_window');
      return;
    }

    // Cmd/Ctrl + K → toggle render mode
    if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
      e.preventDefault();
      toggleRenderMode();
      return;
    }

    // Number keys → switch tab
    if (!e.metaKey && !e.ctrlKey && !e.altKey && /^[1-6]$/.test(e.key)) {
      const tabs = ['nl', 'ocr', 'complete', 'shorthand', 'history', 'settings'];
      switchTab(tabs[parseInt(e.key) - 1]);
      return;
    }

    // Enter in input → submit (unless shift)
    const activeInput = document.activeElement;
    if (activeInput && activeInput.classList.contains('input-box')) {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        if (currentTab === 'nl') doConvert();
        if (currentTab === 'complete') doComplete();
      }
    }
  });

  function toggleRenderMode() {
    renderMode = renderMode === 'katex' ? 'latex' : 'katex';
    $$('.mode-opt').forEach(m => m.classList.toggle('active', m.dataset.mode === renderMode));
    updateRender();
  }

  $$('.mode-opt').forEach(m => {
    m.addEventListener('click', () => {
      renderMode = m.dataset.mode;
      $$('.mode-opt').forEach(x => x.classList.toggle('active', x === m));
      updateRender();
    });
  });

  // ── Buttons ──
  $('#btn-copy-main').addEventListener('click', copyMain);
  $('#btn-copy-src').addEventListener('click', () => {
    if (lastResult) copyToClipboard(lastResult.latex);
  });
  $('#btn-copy-md').addEventListener('click', () => {
    if (lastResult) copyToClipboard(`$$${lastResult.latex}$$`);
  });
  $('#btn-retry').addEventListener('click', doConvert);

  if ($('#btn-save-backend')) {
    $('#btn-save-backend').addEventListener('click', saveBackendSettings);
  }

  if ($('#btn-add-shorthand')) {
    $('#btn-add-shorthand').addEventListener('click', addShorthandFromForm);
  }

  async function loadBackendSettings() {
    if (!els.backendSelect) return;
    try {
      const cfg = await apiGetBackendSettings();
      els.backendSelect.value = cfg.backend || 'ollama';
      els.ollamaHostInput.value = cfg.ollama_host || '';
      els.localModelInput.value = cfg.model_name || '';
      els.localVisionModelInput.value = cfg.vision_model_name || '';
      els.openaiEndpointInput.value = cfg.openai_base_url || '';
      els.openaiModelInput.value = cfg.openai_model_name || '';
      els.openaiVisionModelInput.value = cfg.openai_vision_model_name || '';
      els.openaiKeyInput.value = '';
      els.openaiKeyInput.placeholder = cfg.openai_api_key_set ? '已保存，留空则保持不变' : '请输入 API Key';
      els.backendSaveStatus.textContent = '';
    } catch (e) {
      els.backendSaveStatus.textContent = '无法加载设置';
    }
  }

  async function saveBackendSettings() {
    if (!els.backendSelect) return;
    const payload = {
      backend: els.backendSelect.value,
      ollama_host: els.ollamaHostInput.value.trim(),
      model_name: els.localModelInput.value.trim(),
      vision_model_name: els.localVisionModelInput.value.trim(),
      openai_base_url: els.openaiEndpointInput.value.trim(),
      openai_model_name: els.openaiModelInput.value.trim(),
      openai_vision_model_name: els.openaiVisionModelInput.value.trim(),
    };
    const key = els.openaiKeyInput.value.trim();
    if (key) payload.openai_api_key = key;

    els.backendSaveStatus.textContent = '保存中...';
    try {
      const cfg = await apiSaveBackendSettings(payload);
      els.openaiKeyInput.value = '';
      els.openaiKeyInput.placeholder = cfg.openai_api_key_set ? '已保存，留空则保持不变' : '请输入 API Key';
      els.backendSaveStatus.textContent = '已保存';
      await checkBackend();
    } catch (e) {
      els.backendSaveStatus.textContent = String(e).replace(/^Error:\s*/, '');
    }
  }

  // ── OCR ──
  function setupOcr() {
    const dropZone = els.ocrDrop;
    if (!dropZone) return;

    dropZone.addEventListener('dragover', e => { e.preventDefault(); dropZone.classList.add('drag-over'); });
    dropZone.addEventListener('dragleave', () => dropZone.classList.remove('drag-over'));
    dropZone.addEventListener('drop', e => {
      e.preventDefault();
      dropZone.classList.remove('drag-over');
      const file = e.dataTransfer.files[0];
      if (file) handleOcrFile(file);
    });

    // Guard: only register paste listener once
    if (!window._ocrPasteRegistered) {
      window._ocrPasteRegistered = true;
      document.addEventListener('paste', e => {
      if (currentTab !== 'ocr') return;
      const items = e.clipboardData.items;
      for (const item of items) {
        if (item.type.startsWith('image/')) {
          const file = item.getAsFile();
          if (file) handleOcrFile(file);
          break;
        }
      }
    });
    } // end guard
  }

  async function handleOcrFile(file) {
    const allowedTypes = runtimeConfig.allowedImageTypes;
    if (allowedTypes.size && !allowedTypes.has(file.type)) {
      showErrorIn(els.ocrResult, `不支持的图片类型: ${file.type || 'unknown'}`);
      return;
    }
    if (runtimeConfig.maxOcrBytes && file.size > runtimeConfig.maxOcrBytes) {
      const limitMb = (runtimeConfig.maxOcrBytes / (1024 * 1024)).toFixed(1);
      showErrorIn(els.ocrResult, `图片过大，请使用 ${limitMb} MB 以内的图片`);
      return;
    }

    els.ocrDrop.style.display = 'none';
    els.ocrPreview.style.display = 'flex';
    els.ocrFilename.textContent = file.name;
    els.ocrSize.textContent = (file.size / 1024).toFixed(1) + ' KB';
    els.ocrProcessing.classList.add('active');
    els.ocrResult.style.display = 'none';

    const buf = await file.arrayBuffer();
    try {
      const res = await apiOcr(new Uint8Array(buf));
      lastResult = res;
      showOcrResult(res);
      saveHistory('[OCR] ' + file.name, res.latex);
    } catch (e) {
      showErrorIn(els.ocrResult, String(e));
    } finally {
      els.ocrProcessing.classList.remove('active');
    }
  }

  function showOcrResult(res) {
    els.ocrResult.style.display = 'block';
    els.ocrResult.innerHTML = `
      <div class="result-section">
        <div class="result-label">识别结果 <span class="valid-badge ${res.valid ? 'ok' : 'err'}">${res.valid ? '✓ Valid' : '✗ Invalid'}</span></div>
        <div class="render-preview">${escapeHtml(res.latex)}</div>
      </div>
      <div class="action-row">
        <button class="action-btn primary" data-copy-result="${escapeHtml(res.copy_text || res.latex)}">📋 复制结果</button>
      </div>
    `;
    els.ocrResult.querySelector('[data-copy-result]').addEventListener('click', e => {
      copyToClipboard(e.currentTarget.dataset.copyResult);
    });
  }

  // ── Completion ──
  async function doComplete() {
    const text = els.completeInput.value.trim();
    if (!text || isProcessing) return;
    isProcessing = true;
    els.completeProcessing.classList.add('active');
    els.completeResult.style.display = 'none';
    try {
      const res = await apiComplete(text);
      lastResult = res;
      showCompleteResult(res);
      saveHistory('[补全] ' + text, res.latex);
    } catch (e) {
      showErrorIn(els.completeResult, String(e));
    } finally {
      isProcessing = false;
      els.completeProcessing.classList.remove('active');
    }
  }

  function showCompleteResult(res) {
    els.completeResult.style.display = 'block';
    els.completeResult.innerHTML = `
      <div class="result-section">
        <div class="result-label">补全结果 <span class="valid-badge ${res.valid ? 'ok' : 'err'}">${res.valid ? '✓ Valid' : '✗ Invalid'}</span></div>
        <div class="render-preview">${escapeHtml(res.latex)}</div>
      </div>
      <div class="action-row">
        <button class="action-btn primary" data-copy-result="${escapeHtml(res.copy_text || res.latex)}">📋 复制结果</button>
      </div>
    `;
    els.completeResult.querySelector('[data-copy-result]').addEventListener('click', e => {
      copyToClipboard(e.currentTarget.dataset.copyResult);
    });
  }

  function showErrorIn(el, msg) {
    el.style.display = 'block';
    el.innerHTML = `<div class="error-box"><span class="icon">⚠️</span><div>${escapeHtml(msg)}</div></div>`;
  }

  // ── Shorthand ──
  async function loadShorthands() {
    try {
      const items = await apiJson('/api/shorthands');
      allShorthands = items || [];
      renderShorthands(allShorthands);
    } catch (e) {
      els.shorthandGrid.innerHTML = '<div class="empty-state"><div class="text">无法加载缩写库</div></div>';
    }
  }

  function renderShorthands(items) {
    if (!items || !items.length) {
      const msg = allShorthands.length ? '无匹配的缩写' : '暂无自定义缩写';
      els.shorthandGrid.innerHTML = `<div class="empty-state"><div class="text">${msg}</div></div>`;
      return;
    }
    els.shorthandGrid.innerHTML = items.map(i => `
      <div class="shorthand-card" data-key="${escapeHtml(i.key)}">
        <div class="shorthand-card-head">
          <div class="shorthand-key">${escapeHtml(i.key)}</div>
          ${i.editable ? `<button class="action-btn shorthand-delete" title="删除缩写" data-delete-key="${escapeHtml(i.key)}">×</button>` : ''}
        </div>
        <div class="shorthand-val">${escapeHtml(i.value)}</div>
      </div>
    `).join('');

    els.shorthandGrid.querySelectorAll('.shorthand-card').forEach(c => {
      c.addEventListener('click', () => {
        const key = c.dataset.key;
        els.nlInput.value = key;
        switchTab('nl');
        doConvert();
      });
    });
    els.shorthandGrid.querySelectorAll('[data-delete-key]').forEach(btn => {
      btn.addEventListener('click', async e => {
        e.stopPropagation();
        await deleteShorthand(e.currentTarget.dataset.deleteKey);
      });
    });
  }

  async function addShorthandFromForm() {
    const key = (els.shorthandKeyInput.value || '').trim();
    const value = (els.shorthandValueInput.value || '').trim();
    if (!key || !value) {
      els.shorthandSaveStatus.textContent = '请填写缩写键和 LaTeX';
      return;
    }
    els.shorthandSaveStatus.textContent = '保存中...';
    try {
      await apiAddShorthand(key, value);
      els.shorthandKeyInput.value = '';
      els.shorthandValueInput.value = '';
      els.shorthandSaveStatus.textContent = '已保存';
      await loadShorthands();
    } catch (e) {
      els.shorthandSaveStatus.textContent = String(e).replace(/^Error:\s*/, '');
    }
  }

  async function deleteShorthand(key) {
    els.shorthandSaveStatus.textContent = '删除中...';
    try {
      await apiDeleteShorthand(key);
      els.shorthandSaveStatus.textContent = '已删除';
      await loadShorthands();
    } catch (e) {
      els.shorthandSaveStatus.textContent = String(e).replace(/^Error:\s*/, '');
    }
  }

  // Client-side shorthand search filter (data already fully loaded)
  if (els.shorthandSearch) {
    els.shorthandSearch.addEventListener('input', () => {
      const q = els.shorthandSearch.value.trim().toLowerCase();
      const filtered = !q ? allShorthands : allShorthands.filter(i =>
        (i.key || '').toLowerCase().includes(q) || (i.value || '').toLowerCase().includes(q)
      );
      renderShorthands(filtered);
    });
  }

  // ── History ──
  let historyData = [];
  function saveHistory(input, latex) {
    historyData.unshift({ input, latex, time: Date.now() });
    if (historyData.length > 100) historyData.pop();
    localStorage.setItem('texada-history', JSON.stringify(historyData.slice(0, 50)));
  }

  function loadHistoryLocal() {
    try {
      historyData = JSON.parse(localStorage.getItem('texada-history') || '[]');
    } catch (e) {
      historyData = [];
    }
  }

  async function loadHistory() {
    try {
      const items = await apiJson('/api/history?limit=50');
      renderHistory(items.map(h => ({ input: h.input_text || h.input, latex: h.latex, time: h.created_at })));
    } catch (e) {
      loadHistoryLocal();
      renderHistory(historyData);
    }
  }

  function renderHistory(items) {
    if (!items.length) {
      els.historyList.innerHTML = '<div class="empty-state"><div class="text">暂无历史记录</div></div>';
      return;
    }
    els.historyList.innerHTML = items.slice(0, 50).map(h => `
      <div class="history-item" data-latex="${escapeHtml(h.latex)}">
        <div class="history-input">
          <div class="history-input-text">${escapeHtml(h.input)}</div>
          <div class="history-input-meta">
            <span>${escapeHtml(h.latex.substring(0, 40))}${h.latex.length > 40 ? '…' : ''}</span>
          </div>
        </div>
        <div class="history-render">📋</div>
      </div>
    `).join('');

    els.historyList.querySelectorAll('.history-item').forEach(item => {
      item.addEventListener('click', () => {
        copyToClipboard(item.dataset.latex);
      });
    });
  }

  function escapeHtml(str) {
    return String(str)
      .replace(/&/g,'&amp;')
      .replace(/</g,'&lt;')
      .replace(/>/g,'&gt;')
      .replace(/"/g,'&quot;')
      .replace(/'/g,'&#39;');
  }

  applyPlatformLabels();
  await loadRuntimeConfig();

  // ── Auto-focus & clipboard on show ──
  async function onWindowShown() {
    await checkBackend();
    if (currentTab === 'nl') {
      const clip = await pasteFromClipboard();
      // Only auto-fill if clipboard looks like a math description (heuristic)
      if (clip && clip.length > 0 && clip.length < 500 && !els.nlInput.value) {
        els.nlInput.value = clip;
      }
      els.nlInput.focus();
    }
  }

  // Listen for Tauri window show events
  if (isTauri && window.__TAURI__.event) {
    window.__TAURI__.event.listen('tauri://focus', onWindowShown);
  }

  // Also run on load
  onWindowShown();

  // ── Blur hide ──
  if (isTauri) {
    window.addEventListener('blur', () => {
      // Optional: auto-hide when focus leaves the window
      // invoke('hide_window');
    });
  }

  // ── Drag support on header ──
  // Tauri with -webkit-app-region: drag handles this automatically

  console.log('TeXada Shell loaded. Tauri:', isTauri);
})();
