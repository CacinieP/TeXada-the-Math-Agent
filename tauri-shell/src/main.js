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
  let uiLanguage = 'zh';
  let uiZoom = 1.0;
  let isComposingText = false;
  let historyType = 'all';
  let runtimeConfig = {
    maxOcrBytes: null,
    allowedImageTypes: new Set(),
  };
  let requestTimeoutMs = DEFAULT_REQUEST_TIMEOUT_MS;
  const MIN_UI_ZOOM = 0.8;
  const MAX_UI_ZOOM = 1.4;
  const UI_ZOOM_STEP = 0.1;

  const I18N = {
    zh: {
      'tab.complete': '补全',
      'tab.shorthand': '预设',
      'tab.history': '历史',
      'nl.placeholder': '输入数学描述…  如: 二重积分 f(x,y) 在 D 上',
      'nl.hint': 'Enter 发送 · Shift+Enter 换行 · Esc 关闭',
      'intent.waiting': '等待输入',
      'intent.processing': '处理中…',
      'intent.unknown': 'unknown',
      'result.renderMode': '渲染模式：',
      'result.pureLatexMode': '纯 LaTeX',
      'result.press': '按',
      'result.toggleMode': '切换模式',
      'result.renderPreview': '渲染预览',
      'result.latexStructure': '纯 LaTeX 结构预览',
      'result.latexSource': 'LaTeX 源码',
      'result.valid': '✓ Valid',
      'result.invalid': '✗ Invalid',
      'result.sourceModel': '🤖 model',
      'result.sourceShorthand': '⚡ shorthand',
      'result.ocrResult': '识别结果',
      'result.completionResult': '补全结果',
      'action.copySource': '复制源码',
      'action.copyMarkdown': '复制 Markdown',
      'action.copyClose': '复制并关闭',
      'action.retry': '重新生成',
      'action.copyResult': '复制结果',
      'action.save': '保存',
      'ocr.dropText': '拖放图片或粘贴截图',
      'ocr.dropHint': 'Cmd+V 粘贴剪贴板图片',
      'ocr.unsupportedType': '不支持的图片类型',
      'ocr.tooLarge': '图片过大，请使用 {limit} MB 以内的图片',
      'complete.placeholder': '输入部分 LaTeX… 如: \\\\sum_{i=1}^{',
      'complete.hint': 'Enter 补全 · Esc 关闭',
      'shorthand.keyPlaceholder': '预设键…',
      'shorthand.valuePlaceholder': 'LaTeX 预设公式…',
      'shorthand.add': '添加预设',
      'shorthand.search': '搜索预设…',
      'shorthand.loadError': '无法加载缩写库',
      'shorthand.noMatch': '无匹配的预设',
      'shorthand.emptyCustom': '暂无自定义预设',
      'shorthand.fillRequired': '请填写预设键和 LaTeX',
      'shorthand.saving': '保存中...',
      'shorthand.saved': '已保存',
      'shorthand.deleting': '删除中...',
      'shorthand.deleted': '已删除',
      'shorthand.deleteTitle': '删除预设',
      'shorthand.insertTitle': '点击在光标处键入预设公式',
      'shorthand.copyLatex': '复制 LaTeX',
      'shorthand.copyMarkdown': '复制 Markdown',
      'shorthand.copied': '已复制',
      'history.search': '搜索历史输入或 LaTeX…',
      'history.empty': '暂无历史记录',
      'history.loadError': '无法加载历史记录',
      'history.viewTitle': '点击查看历史结果',
      'history.filterAll': '全部',
      'history.filterNl': '自然语言',
      'history.filterCompletion': '补全',
      'history.filterOcr': 'OCR',
      'history.reuseInput': '复用输入',
      'history.copyLatex': '复制 LaTeX',
      'history.copyMarkdown': '复制 Markdown',
      'history.type.nl': '自然语言',
      'history.type.completion': '补全',
      'history.type.ocr': 'OCR',
      'history.type.text': '文本',
      'history.reuseNl': '已填入自然语言输入',
      'history.reuseCompletion': '已填入补全输入',
      'history.restored': '已打开历史结果',
      'settings.interface': '界面',
      'settings.language': '语言',
      'settings.zoom': '界面缩放',
      'settings.zoomIn': '放大',
      'settings.zoomOut': '缩小',
      'settings.zoomReset': '重置缩放',
      'settings.backendTitle': '后端连接',
      'settings.apiAddress': 'API 地址',
      'settings.apiDesc': 'TeXada FastAPI 服务地址',
      'settings.backend': '模型后端',
      'settings.ollamaHost': 'Ollama 地址',
      'settings.ollamaHostDesc': '默认 http://localhost:11434，可改任意端口',
      'settings.ollamaHostPlaceholder': '例如 http://localhost:11435',
      'settings.localTextModel': '本地文本模型',
      'settings.localVisionModel': '本地视觉模型',
      'settings.cloudEndpoint': '云端 Endpoint',
      'settings.cloudModel': '云端模型名',
      'settings.cloudVisionModel': '云端视觉模型',
      'settings.cloudApiKey': '云端 API Key',
      'settings.sameModelPlaceholder': '留空则使用同一模型',
      'settings.keepKeyPlaceholder': '留空则保持不变',
      'settings.keySavedPlaceholder': '已保存，留空则保持不变',
      'settings.keyEnterPlaceholder': '请输入 API Key',
      'settings.shortcuts': '快捷键',
      'settings.wake': '唤出 / 隐藏',
      'settings.toggleRenderMode': '切换渲染模式',
      'settings.about': '关于',
      'settings.loadError': '无法加载设置',
      'settings.saving': '保存中...',
      'settings.saved': '已保存',
      'settings.detecting': '检测中...',
      'settings.languageSaved': '已切换',
      'status.ready': 'Ready',
      'status.noApi': 'No API',
      'status.error': 'Error',
      'status.offline': 'Offline',
      'status.online': 'Online',
      'status.partialReady': '文本可用 · OCR 缺模型',
      'status.missingModel': '模型缺失',
      'status.notConfigured': '未配置',
      'status.notRunning': '未连接',
      'insert.fallbackCopied': '浏览器模式已复制；桌面端可直接键入',
      'insert.failed': '插入失败，已复制到剪贴板'
    },
    en: {
      'tab.complete': 'Complete',
      'tab.shorthand': 'Presets',
      'tab.history': 'History',
      'nl.placeholder': 'Describe a formula… e.g. double integral of f(x,y) over D',
      'nl.hint': 'Enter to send · Shift+Enter newline · Esc close',
      'intent.waiting': 'Waiting',
      'intent.processing': 'Processing…',
      'intent.unknown': 'unknown',
      'result.renderMode': 'Render mode:',
      'result.pureLatexMode': 'LaTeX',
      'result.press': 'Press',
      'result.toggleMode': 'to switch',
      'result.renderPreview': 'Rendered preview',
      'result.latexStructure': 'Plain LaTeX structure',
      'result.latexSource': 'LaTeX source',
      'result.valid': '✓ Valid',
      'result.invalid': '✗ Invalid',
      'result.sourceModel': '🤖 model',
      'result.sourceShorthand': '⚡ shorthand',
      'result.ocrResult': 'OCR result',
      'result.completionResult': 'Completion result',
      'action.copySource': 'Copy source',
      'action.copyMarkdown': 'Copy Markdown',
      'action.copyClose': 'Copy and close',
      'action.retry': 'Regenerate',
      'action.copyResult': 'Copy result',
      'action.save': 'Save',
      'ocr.dropText': 'Drop an image or paste a screenshot',
      'ocr.dropHint': 'Cmd+V to paste a clipboard image',
      'ocr.unsupportedType': 'Unsupported image type',
      'ocr.tooLarge': 'Image is too large. Use an image under {limit} MB',
      'complete.placeholder': 'Enter partial LaTeX… e.g. \\\\sum_{i=1}^{',
      'complete.hint': 'Enter to complete · Esc close',
      'shorthand.keyPlaceholder': 'Preset key…',
      'shorthand.valuePlaceholder': 'LaTeX preset…',
      'shorthand.add': 'Add preset',
      'shorthand.search': 'Search presets…',
      'shorthand.loadError': 'Unable to load snippets',
      'shorthand.noMatch': 'No matching presets',
      'shorthand.emptyCustom': 'No custom presets yet',
      'shorthand.fillRequired': 'Enter both a preset key and LaTeX',
      'shorthand.saving': 'Saving...',
      'shorthand.saved': 'Saved',
      'shorthand.deleting': 'Deleting...',
      'shorthand.deleted': 'Deleted',
      'shorthand.deleteTitle': 'Delete preset',
      'shorthand.insertTitle': 'Click to type the preset formula at the cursor',
      'shorthand.copyLatex': 'Copy LaTeX',
      'shorthand.copyMarkdown': 'Copy Markdown',
      'shorthand.copied': 'Copied',
      'history.search': 'Search history input or LaTeX…',
      'history.empty': 'No history yet',
      'history.loadError': 'Unable to load history',
      'history.viewTitle': 'Click to view this history result',
      'history.filterAll': 'All',
      'history.filterNl': 'Natural',
      'history.filterCompletion': 'Complete',
      'history.filterOcr': 'OCR',
      'history.reuseInput': 'Reuse input',
      'history.copyLatex': 'Copy LaTeX',
      'history.copyMarkdown': 'Copy Markdown',
      'history.type.nl': 'Natural',
      'history.type.completion': 'Completion',
      'history.type.ocr': 'OCR',
      'history.type.text': 'Text',
      'history.reuseNl': 'Filled natural language input',
      'history.reuseCompletion': 'Filled completion input',
      'history.restored': 'Opened history result',
      'settings.interface': 'Interface',
      'settings.language': 'Language',
      'settings.zoom': 'Interface zoom',
      'settings.zoomIn': 'Zoom in',
      'settings.zoomOut': 'Zoom out',
      'settings.zoomReset': 'Reset zoom',
      'settings.backendTitle': 'Backend',
      'settings.apiAddress': 'API address',
      'settings.apiDesc': 'TeXada FastAPI service address',
      'settings.backend': 'Model backend',
      'settings.ollamaHost': 'Ollama address',
      'settings.ollamaHostDesc': 'Default http://localhost:11434; any port is allowed',
      'settings.ollamaHostPlaceholder': 'e.g. http://localhost:11435',
      'settings.localTextModel': 'Local text model',
      'settings.localVisionModel': 'Local vision model',
      'settings.cloudEndpoint': 'Cloud endpoint',
      'settings.cloudModel': 'Cloud model',
      'settings.cloudVisionModel': 'Cloud vision model',
      'settings.cloudApiKey': 'Cloud API key',
      'settings.sameModelPlaceholder': 'Leave blank to use the same model',
      'settings.keepKeyPlaceholder': 'Leave blank to keep unchanged',
      'settings.keySavedPlaceholder': 'Saved; leave blank to keep unchanged',
      'settings.keyEnterPlaceholder': 'Enter API key',
      'settings.shortcuts': 'Shortcuts',
      'settings.wake': 'Show / hide',
      'settings.toggleRenderMode': 'Toggle render mode',
      'settings.about': 'About',
      'settings.loadError': 'Unable to load settings',
      'settings.saving': 'Saving...',
      'settings.saved': 'Saved',
      'settings.detecting': 'Detecting...',
      'settings.languageSaved': 'Changed',
      'status.ready': 'Ready',
      'status.noApi': 'No API',
      'status.error': 'Error',
      'status.offline': 'Offline',
      'status.online': 'Online',
      'status.partialReady': 'Text ready · OCR missing',
      'status.missingModel': 'Model missing',
      'status.notConfigured': 'Not configured',
      'status.notRunning': 'Disconnected',
      'insert.fallbackCopied': 'Copied in browser mode; desktop mode types directly',
      'insert.failed': 'Insert failed; copied to clipboard'
    }
  };

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
    historySearch: document.getElementById('history-search'),
    historyFilter: document.getElementById('history-filter'),
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
    uiLanguageSelect: document.getElementById('ui-language-select'),
    uiZoomInput: document.getElementById('ui-zoom-input'),
    uiZoomValue: document.getElementById('ui-zoom-value'),
    zoomInBtn: document.getElementById('btn-zoom-in'),
    zoomOutBtn: document.getElementById('btn-zoom-out'),
    zoomResetBtn: document.getElementById('btn-zoom-reset'),
    uiLanguageStatus: document.getElementById('ui-language-status'),
    apiBaseValue: document.getElementById('api-base-value'),
  };

  // ── Helpers ──
  function $(sel) { return document.querySelector(sel); }
  function $$(sel) { return document.querySelectorAll(sel); }

  function isMacPlatform() {
    return /Mac|iPhone|iPad|iPod/.test(navigator.platform || '');
  }

  function normalizeLanguage(value) {
    return value === 'en' ? 'en' : 'zh';
  }

  function normalizeZoom(value) {
    const zoom = Number(value);
    if (!Number.isFinite(zoom)) return 1.0;
    return Math.min(MAX_UI_ZOOM, Math.max(MIN_UI_ZOOM, Math.round(zoom * 10) / 10));
  }

  function t(key, values = {}) {
    const raw = (I18N[uiLanguage] && I18N[uiLanguage][key]) || I18N.zh[key] || key;
    return raw.replace(/\{(\w+)\}/g, (_, name) => String(values[name] ?? ''));
  }

  function applyLanguage() {
    document.documentElement.lang = uiLanguage === 'en' ? 'en' : 'zh-CN';
    document.querySelectorAll('[data-i18n]').forEach(el => {
      el.textContent = t(el.dataset.i18n);
    });
    document.querySelectorAll('[data-i18n-placeholder]').forEach(el => {
      el.placeholder = t(el.dataset.i18nPlaceholder);
    });
    document.querySelectorAll('[data-i18n-title]').forEach(el => {
      el.title = t(el.dataset.i18nTitle);
    });
    if (els.uiLanguageSelect) els.uiLanguageSelect.value = uiLanguage;
    updateZoomControl();
    if (els.apiBaseValue && ['检测中...', 'Detecting...'].includes(els.apiBaseValue.textContent)) {
      els.apiBaseValue.textContent = t('settings.detecting');
    }
    applyPlatformLabels();
    if (!lastResult && !isProcessing) setIntent('🔍', t('intent.waiting'));
    if (currentTab === 'history' && historyData.length) renderHistory(historyData);
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

  function isEditableTarget(target) {
    if (!target || target === document || target === window) return false;
    if (target.isContentEditable) return true;
    const editable = target.closest?.('input, textarea, select, [contenteditable]:not([contenteditable="false"]), [role="textbox"], [role="searchbox"]');
    return !!editable && !editable.disabled;
  }

  function isTextEntryEvent(e) {
    if (isEditableTarget(e.target) || isEditableTarget(document.activeElement)) return true;
    if (typeof e.composedPath !== 'function') return false;
    return e.composedPath().some(node => isEditableTarget(node));
  }

  function isImeComposing(e) {
    return isComposingText || e.isComposing || e.keyCode === 229;
  }

  function isWindowDragBlocked(target) {
    return !!target?.closest?.([
      'button',
      'input',
      'select',
      'textarea',
      'a',
      'label',
      '[contenteditable="true"]',
      '.tab-item',
      '.mode-opt',
      '.action-btn',
      '.formula-click-target',
      '.drop-zone',
      '.shorthand-card',
      '.history-item',
      '.search-box',
      '.setting-control',
      '.zoom-control',
      '.latex-source',
      '.ocr-preview',
    ].join(', '));
  }

  function bindWindowDrag() {
    const dragSurface = document.getElementById('app');
    if (!dragSurface) return;
    const startDrag = () => {
      if (!isTauri) return;
      try {
        const currentWindow = window.__TAURI__?.window?.getCurrentWindow?.();
        if (currentWindow?.startDragging) {
          currentWindow.startDragging().catch(() => invoke('start_dragging').catch(() => {}));
          return;
        }
      } catch (_) {
        // Fall through to the Rust command wrapper below.
      }
      invoke('start_dragging').catch(() => {});
    };
    dragSurface.addEventListener('mousedown', e => {
      if (e.button !== 0 || e.detail > 1 || isWindowDragBlocked(e.target)) return;
      startDrag();
    });
  }

  function updateAppVisualSize() {
    const app = document.getElementById('app');
    if (!app) return;
    const viewportWidth = window.innerWidth || 560;
    const viewportHeight = window.innerHeight || 600;
    app.style.width = `${viewportWidth / uiZoom}px`;
    app.style.height = `${viewportHeight / uiZoom}px`;
  }

  function updateZoomControl() {
    const percent = Math.round(uiZoom * 100);
    if (els.uiZoomInput) els.uiZoomInput.value = String(percent);
    if (els.uiZoomValue) els.uiZoomValue.textContent = `${percent}%`;
  }

  function applyZoom() {
    document.documentElement.style.setProperty('--ui-zoom', String(uiZoom));
    updateZoomControl();
    updateAppVisualSize();
    localStorage.setItem('texada-ui-zoom', String(uiZoom));
  }

  function setZoom(value, persist = false) {
    uiZoom = normalizeZoom(value);
    applyZoom();
    if (persist) persistUiSettings();
  }

  function adjustZoom(delta) {
    setZoom(uiZoom + delta, true);
  }

  function setIntent(icon, message) {
    els.nlIntent.textContent = '';
    const iconEl = document.createElement('span');
    iconEl.className = 'intent-icon';
    iconEl.textContent = icon;
    els.nlIntent.append(iconEl, ' ' + message);
  }

  function backendStatusText(info) {
    if (!info) return t('status.offline');
    if (info.status === 'partial_ready') return t('status.partialReady');
    if (info.status === 'missing_model') return t('status.missingModel');
    if (info.status === 'not_configured') return t('status.notConfigured');
    if (info.status === 'not_running') return t('status.notRunning');
    if (info.status === 'ready' || info.status === 'ok') {
      return info.model || t('status.ready');
    }
    return info.message || info.status || t('status.error');
  }

  function backendStatusTitle(info) {
    if (!info) return '';
    const parts = [];
    if (info.endpoint) parts.push(`Endpoint: ${info.endpoint}`);
    if (info.model) parts.push(`Text: ${info.model}`);
    if (info.vision) parts.push(`Vision: ${info.vision}`);
    if (info.missing_models && info.missing_models.length) {
      parts.push(`Missing: ${info.missing_models.join(', ')}`);
    }
    if (info.next_action) parts.push(`Next: ${info.next_action}`);
    return parts.join('\n');
  }

  function setStatus(online, text, state = '', details = null) {
    const dot = els.statusDot.querySelector('.dot');
    const span = els.statusDot.querySelector('span');
    dot.className = 'dot';
    if (!online) dot.classList.add('offline');
    if (online && state === 'partial_ready') dot.classList.add('warning');
    span.textContent = text || (online ? t('status.online') : t('status.offline'));
    els.statusDot.title = backendStatusTitle(details);
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
      const isOnline = Boolean(info.ready) || info.status === 'ok' || info.status === 'ready' || info.status === 'partial_ready';
      setStatus(isOnline, backendStatusText(info), info.status, info);
    } catch (e) {
      if (isTauri) {
        try {
          const info = await invoke('get_status');
          const isOnline = Boolean(info.ready) || info.status === 'ok' || info.status === 'ready' || info.status === 'partial_ready';
          setStatus(isOnline, backendStatusText(info), info.status, info);
        } catch (e2) {
          setStatus(false, t('status.noApi'));
        }
      } else {
        setStatus(false, t('status.noApi'));
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
    if (tab === 'settings') {
      loadUiSettings();
      loadBackendSettings();
    }
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

  async function apiGetUiSettings() {
    return await apiJson('/api/settings/ui');
  }

  async function apiSaveUiSettings() {
    return await apiJson('/api/settings/ui', {
      method: 'POST',
      body: { ui_language: uiLanguage, ui_zoom: uiZoom },
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
    setIntent('⏳', t('intent.processing'));

    try {
      const res = await apiConvert(text);
      lastResult = res;
      showResult(res);
      saveHistoryFallback({
        input_text: text,
        input_type: 'nl',
        latex: res.latex,
        intent: res.intent,
        source: res.source,
        render_mode: renderMode,
        valid: res.valid,
      });
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
    els.resultValid.textContent = res.valid ? t('result.valid') : t('result.invalid');
    els.resultSource.className = 'source-badge ' + (res.source === 'shorthand' ? 'shorthand' : 'model');
    els.resultSource.textContent = res.source === 'shorthand' ? t('result.sourceShorthand') : t('result.sourceModel');

    setIntent('∫', `${res.intent || t('intent.unknown')} · ${Number(res.latency_ms || 0).toFixed(1)}ms`);

    syncRenderModeOptions();
    updateRender();
    bindNlResultButtons();
    bindModeOptions();
  }

  function updateRender() {
    if (!lastResult) return;
    if (renderMode === 'katex') {
      els.katexSection.style.display = 'block';
      els.latexSection.style.display = 'none';
      renderKatexPreview(els.renderPreview, lastResult.latex, lastResult.katex_html);
    } else {
      els.katexSection.style.display = 'none';
      els.latexSection.style.display = 'block';
      els.latexPreview.innerHTML = highlightLatex(lastResult.latex);
    }
  }

  function renderKatexPreview(target, latex, fallbackHtml = '', displayMode = true) {
    if (!target) return;
    if (window.katex) {
      try {
        target.innerHTML = '';
        window.katex.render(latex, target, {
          throwOnError: false,
          displayMode,
        });
        return;
      } catch (e) {
        // Fall back below; the user should still see a usable formula string.
      }
    }
    if (fallbackHtml) {
      target.innerHTML = fallbackHtml;
    } else {
      target.textContent = latex;
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

  function formulaText(kind) {
    if (!lastResult) return '';
    if (kind === 'markdown') return `$$${lastResult.latex}$$`;
    if (kind === 'latex') return lastResult.latex;
    return lastResult.copy_text || lastResult.latex;
  }

  function markdownFormula(latex) {
    const text = String(latex || '').trim();
    if ((text.startsWith('$$') && text.endsWith('$$')) ||
        (text.startsWith('\\[') && text.endsWith('\\]'))) {
      return text;
    }
    return `$$${latex}$$`;
  }

  function latexForRender(latex) {
    const text = String(latex || '').trim();
    if (text.startsWith('$$') && text.endsWith('$$')) {
      return text.slice(2, -2).trim();
    }
    if (text.startsWith('\\[') && text.endsWith('\\]')) {
      return text.slice(2, -2).trim();
    }
    return latex;
  }

  async function insertAtCursor(text) {
    if (!text) return;
    try {
      if (isTauri) {
        await invoke('insert_text_at_cursor', { text });
      } else {
        await copyToClipboard(text);
        setIntent('📋', t('insert.fallbackCopied'));
      }
    } catch (e) {
      await copyToClipboard(text);
      setIntent('📋', t('insert.failed'));
    }
  }

  function bindFormulaInsertHandlers(root = document) {
    root.querySelectorAll('.formula-click-target').forEach(target => {
      target.onclick = e => {
        if (e.target.closest('button')) return;
        const text = target.dataset.insertText || formulaText(target.dataset.insertTarget);
        insertAtCursor(text);
      };
    });
  }

  // ── Keyboard ──
  document.addEventListener('compositionstart', () => {
    isComposingText = true;
  }, true);

  document.addEventListener('compositionend', () => {
    isComposingText = false;
  }, true);

  document.addEventListener('keydown', e => {
    if (isImeComposing(e)) return;

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

    // Cmd/Ctrl + plus/minus/0 → interface zoom
    if (e.metaKey || e.ctrlKey) {
      if (e.key === '+' || e.key === '=') {
        e.preventDefault();
        adjustZoom(UI_ZOOM_STEP);
        return;
      }
      if (e.key === '-') {
        e.preventDefault();
        adjustZoom(-UI_ZOOM_STEP);
        return;
      }
      if (e.key === '0') {
        e.preventDefault();
        setZoom(1.0, true);
        return;
      }
    }

    // Number keys → switch tab
    if (!isTextEntryEvent(e) && !e.metaKey && !e.ctrlKey && !e.altKey && /^[1-6]$/.test(e.key)) {
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
    syncRenderModeOptions();
    updateRender();
  }

  function syncRenderModeOptions() {
    $$('.mode-opt').forEach(m => {
      m.classList.toggle('active', m.dataset.mode === renderMode);
    });
  }

  function bindModeOptions() {
    $$('.mode-opt').forEach(m => {
      m.onclick = () => {
        renderMode = m.dataset.mode;
        syncRenderModeOptions();
        updateRender();
      };
    });
  }

  // ── Buttons ──
  function bindNlResultButtons() {
    const copyMainBtn = $('#btn-copy-main');
    const copySrcBtn = $('#btn-copy-src');
    const copyMdBtn = $('#btn-copy-md');
    const retryBtn = $('#btn-retry');
    if (copyMainBtn) copyMainBtn.onclick = copyMain;
    if (copySrcBtn) copySrcBtn.onclick = () => {
      if (lastResult) copyToClipboard(lastResult.latex);
    };
    if (copyMdBtn) copyMdBtn.onclick = () => {
      if (lastResult) copyToClipboard(`$$${lastResult.latex}$$`);
    };
    if (retryBtn) retryBtn.onclick = doConvert;
    bindFormulaInsertHandlers(els.nlResult);
  }

  bindModeOptions();
  bindNlResultButtons();
  bindWindowDrag();

  if ($('#btn-save-backend')) {
    $('#btn-save-backend').addEventListener('click', saveBackendSettings);
  }

  if ($('#btn-add-shorthand')) {
    $('#btn-add-shorthand').addEventListener('click', addShorthandFromForm);
  }

  if (els.uiLanguageSelect) {
    els.uiLanguageSelect.addEventListener('change', () => saveUiSettings());
  }

  if (els.uiZoomInput) {
    els.uiZoomInput.addEventListener('input', e => {
      setZoom(Number(e.currentTarget.value) / 100, false);
    });
    els.uiZoomInput.addEventListener('change', () => persistUiSettings());
  }
  if (els.zoomInBtn) {
    els.zoomInBtn.addEventListener('click', () => adjustZoom(UI_ZOOM_STEP));
  }
  if (els.zoomOutBtn) {
    els.zoomOutBtn.addEventListener('click', () => adjustZoom(-UI_ZOOM_STEP));
  }
  if (els.zoomResetBtn) {
    els.zoomResetBtn.addEventListener('click', () => setZoom(1.0, true));
  }

  async function loadUiSettings() {
    try {
      const cfg = await apiGetUiSettings();
      uiLanguage = normalizeLanguage(cfg.ui_language);
      uiZoom = normalizeZoom(cfg.ui_zoom);
      localStorage.setItem('texada-ui-language', uiLanguage);
      localStorage.setItem('texada-ui-zoom', String(uiZoom));
    } catch (e) {
      uiLanguage = normalizeLanguage(localStorage.getItem('texada-ui-language') || uiLanguage);
      uiZoom = normalizeZoom(localStorage.getItem('texada-ui-zoom') || uiZoom);
    }
    if (els.uiLanguageStatus) els.uiLanguageStatus.textContent = '';
    applyZoom();
    applyLanguage();
    if (lastResult) showResult(lastResult);
  }

  async function saveUiSettings() {
    if (els.uiLanguageSelect) uiLanguage = normalizeLanguage(els.uiLanguageSelect.value);
    localStorage.setItem('texada-ui-language', uiLanguage);
    applyLanguage();
    if (lastResult) showResult(lastResult);
    await persistUiSettings();
  }

  async function persistUiSettings() {
    if (els.uiLanguageStatus) els.uiLanguageStatus.textContent = t('settings.saving');
    try {
      const cfg = await apiSaveUiSettings();
      uiLanguage = normalizeLanguage(cfg.ui_language);
      uiZoom = normalizeZoom(cfg.ui_zoom);
      localStorage.setItem('texada-ui-language', uiLanguage);
      localStorage.setItem('texada-ui-zoom', String(uiZoom));
      applyZoom();
      applyLanguage();
      if (lastResult) showResult(lastResult);
      if (els.uiLanguageStatus) els.uiLanguageStatus.textContent = t('settings.languageSaved');
    } catch (e) {
      if (els.uiLanguageStatus) els.uiLanguageStatus.textContent = String(e).replace(/^Error:\s*/, '');
    }
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
      els.openaiKeyInput.placeholder = cfg.openai_api_key_set ? t('settings.keySavedPlaceholder') : t('settings.keyEnterPlaceholder');
      els.backendSaveStatus.textContent = '';
    } catch (e) {
      els.backendSaveStatus.textContent = t('settings.loadError');
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

    els.backendSaveStatus.textContent = t('settings.saving');
    try {
      const cfg = await apiSaveBackendSettings(payload);
      els.openaiKeyInput.value = '';
      els.openaiKeyInput.placeholder = cfg.openai_api_key_set ? t('settings.keySavedPlaceholder') : t('settings.keyEnterPlaceholder');
      els.backendSaveStatus.textContent = t('settings.saved');
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
      showErrorIn(els.ocrResult, `${t('ocr.unsupportedType')}: ${file.type || 'unknown'}`);
      return;
    }
    if (runtimeConfig.maxOcrBytes && file.size > runtimeConfig.maxOcrBytes) {
      const limitMb = (runtimeConfig.maxOcrBytes / (1024 * 1024)).toFixed(1);
      showErrorIn(els.ocrResult, t('ocr.tooLarge', { limit: limitMb }));
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
      saveHistoryFallback({
        input_text: file.name || 'image',
        input_type: 'ocr',
        latex: res.latex,
        intent: res.intent,
        source: res.source,
        render_mode: renderMode,
        valid: res.valid,
      });
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
        <div class="result-label">${t('result.ocrResult')} <span class="valid-badge ${res.valid ? 'ok' : 'err'}">${res.valid ? t('result.valid') : t('result.invalid')}</span></div>
        <div class="render-preview formula-click-target" data-insert-target="copy">${escapeHtml(res.latex)}</div>
      </div>
      <div class="action-row">
        <button class="action-btn primary" data-copy-result>📋 ${t('action.copyResult')}</button>
      </div>
    `;
    const resultText = res.copy_text || res.latex;
    els.ocrResult.querySelector('[data-insert-target]').dataset.insertText = resultText;
    els.ocrResult.querySelector('[data-copy-result]').dataset.copyResult = resultText;
    renderKatexPreview(
      els.ocrResult.querySelector('[data-insert-target]'),
      res.latex,
      res.katex_html || ''
    );
    els.ocrResult.querySelector('[data-copy-result]').addEventListener('click', e => {
      copyToClipboard(e.currentTarget.dataset.copyResult);
    });
    bindFormulaInsertHandlers(els.ocrResult);
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
      saveHistoryFallback({
        input_text: text,
        input_type: 'completion',
        latex: res.latex,
        intent: res.intent,
        source: res.source,
        render_mode: renderMode,
        valid: res.valid,
      });
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
        <div class="result-label">${t('result.completionResult')} <span class="valid-badge ${res.valid ? 'ok' : 'err'}">${res.valid ? t('result.valid') : t('result.invalid')}</span></div>
        <div class="render-preview formula-click-target" data-insert-target="copy">${escapeHtml(res.latex)}</div>
      </div>
      <div class="action-row">
        <button class="action-btn primary" data-copy-result>📋 ${t('action.copyResult')}</button>
      </div>
    `;
    const resultText = res.copy_text || res.latex;
    els.completeResult.querySelector('[data-insert-target]').dataset.insertText = resultText;
    els.completeResult.querySelector('[data-copy-result]').dataset.copyResult = resultText;
    renderKatexPreview(
      els.completeResult.querySelector('[data-insert-target]'),
      res.latex,
      res.katex_html || ''
    );
    els.completeResult.querySelector('[data-copy-result]').addEventListener('click', e => {
      copyToClipboard(e.currentTarget.dataset.copyResult);
    });
    bindFormulaInsertHandlers(els.completeResult);
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
      els.shorthandGrid.innerHTML = `<div class="empty-state"><div class="text">${t('shorthand.loadError')}</div></div>`;
    }
  }

  function renderShorthands(items) {
    if (!items || !items.length) {
      const msg = allShorthands.length ? t('shorthand.noMatch') : t('shorthand.emptyCustom');
      els.shorthandGrid.innerHTML = `<div class="empty-state"><div class="text">${msg}</div></div>`;
      return;
    }
    els.shorthandGrid.innerHTML = items.map((i, index) => `
      <div class="shorthand-card formula-click-target" data-shorthand-index="${index}" title="${t('shorthand.insertTitle')}">
        <div class="shorthand-card-head">
          <div class="shorthand-key">${escapeHtml(i.key)}</div>
          ${i.editable ? `<button class="action-btn shorthand-delete" title="${t('shorthand.deleteTitle')}" data-delete-key="${escapeHtml(i.key)}">×</button>` : ''}
        </div>
        <div class="shorthand-render" data-shorthand-render="${index}">${escapeHtml(i.value)}</div>
        <div class="shorthand-val">${escapeHtml(i.value)}</div>
        <div class="shorthand-actions">
          <button class="action-btn shorthand-action" data-shorthand-copy-latex="${index}" title="${t('shorthand.copyLatex')}" aria-label="${t('shorthand.copyLatex')}">LaTeX</button>
          <button class="action-btn shorthand-action" data-shorthand-copy-markdown="${index}" title="${t('shorthand.copyMarkdown')}" aria-label="${t('shorthand.copyMarkdown')}">MD</button>
        </div>
      </div>
    `).join('');

    els.shorthandGrid.querySelectorAll('.shorthand-card').forEach(card => {
      const item = items[Number(card.dataset.shorthandIndex)];
      card.dataset.insertText = markdownFormula(item.value);
    });
    els.shorthandGrid.querySelectorAll('[data-shorthand-render]').forEach(target => {
      const item = items[Number(target.dataset.shorthandRender)];
      renderKatexPreview(target, latexForRender(item.value), '', false);
    });
    bindFormulaInsertHandlers(els.shorthandGrid);
    els.shorthandGrid.querySelectorAll('[data-shorthand-copy-latex]').forEach(btn => {
      btn.addEventListener('click', e => {
        e.stopPropagation();
        const item = items[Number(e.currentTarget.dataset.shorthandCopyLatex)];
        copyToClipboard(item.value);
        els.shorthandSaveStatus.textContent = t('shorthand.copied');
      });
    });
    els.shorthandGrid.querySelectorAll('[data-shorthand-copy-markdown]').forEach(btn => {
      btn.addEventListener('click', e => {
        e.stopPropagation();
        const item = items[Number(e.currentTarget.dataset.shorthandCopyMarkdown)];
        copyToClipboard(markdownFormula(item.value));
        els.shorthandSaveStatus.textContent = t('shorthand.copied');
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
      els.shorthandSaveStatus.textContent = t('shorthand.fillRequired');
      return;
    }
    els.shorthandSaveStatus.textContent = t('shorthand.saving');
    try {
      await apiAddShorthand(key, value);
      els.shorthandKeyInput.value = '';
      els.shorthandValueInput.value = '';
      els.shorthandSaveStatus.textContent = t('shorthand.saved');
      await loadShorthands();
    } catch (e) {
      els.shorthandSaveStatus.textContent = String(e).replace(/^Error:\s*/, '');
    }
  }

  async function deleteShorthand(key) {
    els.shorthandSaveStatus.textContent = t('shorthand.deleting');
    try {
      await apiDeleteShorthand(key);
      els.shorthandSaveStatus.textContent = t('shorthand.deleted');
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

  function normalizeHistoryItem(item) {
    return {
      id: Number(item.id || 0),
      input: item.input_text || item.input || '',
      type: item.input_type || item.type || 'nl',
      latex: item.latex || '',
      intent: item.intent || '',
      source: item.source || '',
      renderMode: item.render_mode || item.renderMode || renderMode,
      valid: item.valid !== undefined ? Boolean(item.valid) : true,
      latencyMs: Number(item.latency_ms || item.latencyMs || 0),
      tokensUsed: Number(item.tokens_used || item.tokensUsed || 0),
      time: item.created_at || item.time || '',
    };
  }

  function normalizeLocalHistoryItem(item) {
    let input = item.input_text || item.input || '';
    let type = item.input_type || item.type || 'nl';
    if (input.startsWith('[补全] ')) {
      type = 'completion';
      input = input.slice('[补全] '.length);
    } else if (input.startsWith('[OCR] ')) {
      type = 'ocr';
      input = input.slice('[OCR] '.length);
    }
    return normalizeHistoryItem({
      ...item,
      input_text: input,
      input_type: type,
      created_at: item.created_at || item.time,
    });
  }

  function saveHistoryFallback(entry) {
    const localEntry = normalizeHistoryItem({
      ...entry,
      created_at: new Date().toISOString(),
    });
    historyData.unshift(localEntry);
    if (historyData.length > 100) historyData.pop();
    localStorage.setItem('texada-history', JSON.stringify(historyData.slice(0, 100)));
  }

  function loadHistoryLocal() {
    try {
      const raw = JSON.parse(localStorage.getItem('texada-history') || '[]');
      historyData = raw.map(normalizeLocalHistoryItem);
    } catch (e) {
      historyData = [];
    }
  }

  function filterHistoryItems(items) {
    const q = (els.historySearch?.value || '').trim().toLowerCase();
    return items.filter(item => {
      if (historyType !== 'all' && item.type !== historyType) return false;
      if (!q) return true;
      return [item.input, item.latex, item.intent, item.source, item.type]
        .some(value => String(value || '').toLowerCase().includes(q));
    });
  }

  async function apiHistory(q, type, limit = 80) {
    const params = new URLSearchParams({ limit: String(limit) });
    if (q) params.set('q', q);
    if (type && type !== 'all') params.set('type', type);
    return await apiJson(`/api/history?${params.toString()}`);
  }

  async function loadHistory() {
    const q = (els.historySearch?.value || '').trim();
    try {
      const items = await apiHistory(q, historyType);
      historyData = items.map(normalizeHistoryItem);
      renderHistory(historyData);
    } catch (e) {
      loadHistoryLocal();
      renderHistory(filterHistoryItems(historyData));
    }
  }

  function historyTypeLabel(type) {
    return t(`history.type.${type || 'nl'}`);
  }

  function formatHistoryTime(value) {
    if (!value) return '';
    const date = typeof value === 'number'
      ? new Date(value)
      : new Date(String(value).replace(' ', 'T'));
    if (Number.isNaN(date.getTime())) return String(value);
    return date.toLocaleString(uiLanguage === 'en' ? 'en-US' : 'zh-CN', {
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
    });
  }

  function reuseHistoryInput(item) {
    if (!item.input) return;
    if (item.type === 'completion') {
      els.completeInput.value = item.input;
      switchTab('complete');
      setTimeout(() => els.completeInput.focus(), 50);
      setIntent('↺', t('history.reuseCompletion'));
      return;
    }
    els.nlInput.value = item.input;
    switchTab('nl');
    setTimeout(() => els.nlInput.focus(), 50);
    setIntent('↺', t('history.reuseNl'));
  }

  function historyRenderMode(mode) {
    return mode === 'katex' || mode === 'latex' ? mode : renderMode;
  }

  function historyResultFromItem(item) {
    const mode = historyRenderMode(item.renderMode);
    return {
      latex: item.latex || '',
      katex_html: '',
      latex_highlighted: null,
      copy_text: mode === 'katex' ? markdownFormula(item.latex || '') : (item.latex || ''),
      valid: item.valid,
      source: item.source || 'model',
      intent: item.intent || historyTypeLabel(item.type),
      confidence: 1,
      latency_ms: item.latencyMs || 0,
      tokens_used: item.tokensUsed || 0,
    };
  }

  function viewHistoryResult(item) {
    if (!item || !item.latex) return;
    renderMode = historyRenderMode(item.renderMode);
    lastResult = historyResultFromItem(item);

    if (item.type === 'completion') {
      if (item.input) els.completeInput.value = item.input;
      switchTab('complete');
      showCompleteResult(lastResult);
    } else if (item.type === 'ocr') {
      switchTab('ocr');
      if (els.ocrDrop) els.ocrDrop.style.display = 'none';
      if (els.ocrPreview) els.ocrPreview.style.display = 'none';
      showOcrResult(lastResult);
    } else {
      if (item.input) els.nlInput.value = item.input;
      switchTab('nl');
      showResult(lastResult);
    }

    setIntent('↺', t('history.restored'));
  }

  function renderHistory(items) {
    if (!items.length) {
      els.historyList.innerHTML = `<div class="empty-state"><div class="text">${t('history.empty')}</div></div>`;
      return;
    }
    els.historyList.innerHTML = items.slice(0, 80).map((h, index) => {
      const canReuse = h.type !== 'ocr' && h.input;
      const statusKey = h.valid ? 'result.valid' : 'result.invalid';
      const latexPreview = h.latex.length > 80 ? `${h.latex.substring(0, 80)}...` : h.latex;
      return `
      <div class="history-item" data-history-index="${index}" title="${t('history.viewTitle')}">
        <div class="history-input">
          <div class="history-input-head">
            <span class="history-type">${escapeHtml(historyTypeLabel(h.type))}</span>
            <span class="history-time">${escapeHtml(formatHistoryTime(h.time))}</span>
            <span class="valid-badge ${h.valid ? 'ok' : 'err'}">${t(statusKey)}</span>
          </div>
          <div class="history-input-text">${escapeHtml(h.input)}</div>
          <div class="history-input-meta">
            <span class="history-latex">${escapeHtml(latexPreview)}</span>
          </div>
        </div>
        <div class="history-actions">
          ${canReuse ? `<button class="action-btn history-action" data-history-reuse="${index}" title="${t('history.reuseInput')}" aria-label="${t('history.reuseInput')}">${t('history.reuseInput')}</button>` : ''}
          <button class="action-btn history-action" data-history-copy-latex="${index}" title="${t('history.copyLatex')}" aria-label="${t('history.copyLatex')}">LaTeX</button>
          <button class="action-btn history-action" data-history-copy-markdown="${index}" title="${t('history.copyMarkdown')}" aria-label="${t('history.copyMarkdown')}">MD</button>
        </div>
      </div>
      `;
    }).join('');

    els.historyList.querySelectorAll('[data-history-index]').forEach(row => {
      row.addEventListener('click', e => {
        if (e.target.closest('button')) return;
        viewHistoryResult(items[Number(e.currentTarget.dataset.historyIndex)]);
      });
    });
    els.historyList.querySelectorAll('[data-history-reuse]').forEach(btn => {
      btn.addEventListener('click', e => {
        e.stopPropagation();
        reuseHistoryInput(items[Number(e.currentTarget.dataset.historyReuse)]);
      });
    });
    els.historyList.querySelectorAll('[data-history-copy-latex]').forEach(btn => {
      btn.addEventListener('click', e => {
        e.stopPropagation();
        const item = items[Number(e.currentTarget.dataset.historyCopyLatex)];
        copyToClipboard(item.latex);
      });
    });
    els.historyList.querySelectorAll('[data-history-copy-markdown]').forEach(btn => {
      btn.addEventListener('click', e => {
        e.stopPropagation();
        const item = items[Number(e.currentTarget.dataset.historyCopyMarkdown)];
        copyToClipboard(markdownFormula(item.latex));
      });
    });
  }

  if (els.historySearch) {
    let historySearchTimer = null;
    els.historySearch.addEventListener('input', () => {
      clearTimeout(historySearchTimer);
      historySearchTimer = setTimeout(loadHistory, 180);
    });
  }

  if (els.historyFilter) {
    els.historyFilter.addEventListener('click', e => {
      const btn = e.target.closest('[data-history-type]');
      if (!btn) return;
      historyType = btn.dataset.historyType || 'all';
      els.historyFilter.querySelectorAll('[data-history-type]').forEach(item => {
        item.classList.toggle('active', item === btn);
      });
      loadHistory();
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

  uiLanguage = normalizeLanguage(localStorage.getItem('texada-ui-language') || uiLanguage);
  uiZoom = normalizeZoom(localStorage.getItem('texada-ui-zoom') || uiZoom);
  applyZoom();
  applyLanguage();
  window.addEventListener('resize', updateAppVisualSize);
  await loadRuntimeConfig();
  await loadUiSettings();

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
