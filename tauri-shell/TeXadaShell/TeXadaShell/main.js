// TeXada Shell Frontend — Swift WebView Edition
(async function() {
  'use strict';

  // ── Environment detection ──
  const isTauri = typeof window.__TAURI__ !== 'undefined';
  const isSwift = !isTauri && window.webkit && window.webkit.messageHandlers && window.webkit.messageHandlers.texada;

  let reqId = 0;
  const pending = new Map();
  let API_BASE = '';

  // ── Bridge ──
  async function invoke(cmd, payload) {
    if (isTauri) {
      return window.__TAURI__.core.invoke(cmd, payload);
    }
    if (isSwift) {
      return new Promise((resolve, reject) => {
        const id = 'r' + (++reqId);
        pending.set(id, { resolve, reject });
        window.webkit.messageHandlers.texada.postMessage({ cmd, id, ...payload });
      });
    }
    // Fallback for browser dev
    if (cmd === 'convert_text') {
      const res = await fetch(API_BASE + '/api/convert', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text: payload.text, render_mode: 'katex' })
      });
      return res.json();
    }
    if (cmd === 'get_status') {
      const res = await fetch(API_BASE + '/api/status');
      return res.json();
    }
    throw new Error('No bridge available for ' + cmd);
  }

  function normalizeApiBase(value) {
    const raw = String(value || '').trim();
    if (!raw) return '';
    try {
      return new URL(raw, window.location.href).origin;
    } catch (e) {
      return raw.replace(/\/+$/, '');
    }
  }

  function browserApiBase() {
    const cfg = window.__TEXADA_CONFIG__ || {};
    const explicit = normalizeApiBase(cfg.apiBase || cfg.api_base);
    if (explicit) return explicit;
    const protocol = window.location.protocol === 'https:' ? 'https:' : 'http:';
    const host = window.location.hostname || '127.0.0.1';
    return `${protocol}//${host}:18732`;
  }

  async function resolveApiBase() {
    try {
      const bridged = normalizeApiBase(await invoke('get_api_base'));
      if (bridged) return bridged;
    } catch (e) {
      // Browser development can run without a native bridge.
    }
    return browserApiBase();
  }

  API_BASE = await resolveApiBase();

  function readClipboard() {
    if (isSwift) return invoke('read_clipboard');
    if (isTauri) return window.__TAURI__.core.invoke('read_clipboard');
    return navigator.clipboard.readText().catch(() => '');
  }

  function writeClipboard(text) {
    if (isSwift) return invoke('write_clipboard', { text });
    if (isTauri) return window.__TAURI__.core.invoke('write_clipboard', { text });
    return navigator.clipboard.writeText(text);
  }

  function hideWindow() {
    if (isSwift) return invoke('hide_window');
    if (isTauri) return window.__TAURI__.core.invoke('hide_window');
  }

  // ── Swift bridge callback ──
  window.texadaSwiftBridge = {
    onResult(id, result) {
      const p = pending.get(id);
      if (!p) return;
      pending.delete(id);
      if (result.ok === false) {
        p.reject(new Error(result.error || 'Unknown error'));
      } else if (result.ok === true && result.data !== undefined) {
        p.resolve(result.data);
      } else if (result.ok === true && result.text !== undefined) {
        p.resolve(result.text);
      } else {
        p.resolve(result);
      }
    },
    onWindowShown() {
      onWindowShownHandler();
    }
  };

  // ── State ──
  let currentTab = 'nl';
  let renderMode = 'katex';
  let lastResult = null;
  let isProcessing = false;

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
    historyList: document.getElementById('history-list'),
  };

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

  async function checkBackend() {
    try {
      const info = await invoke('get_status');
      const isOnline = info.status === 'ok' || info.status === 'ready';
      setStatus(isOnline, isOnline ? (info.model || 'Ready') : 'Error');
    } catch (e) {
      setStatus(false, 'No API');
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
  }

  els.tabBar.addEventListener('click', e => {
    const item = e.target.closest('.tab-item');
    if (item) switchTab(item.dataset.tab);
  });

  // ── NL Convert ──
  async function doConvert() {
    const text = els.nlInput.value.trim();
    if (!text || isProcessing) return;
    isProcessing = true;
    els.nlProcessing.classList.add('active');
    els.nlResult.style.display = 'none';
    setIntent('⏳', '处理中…');

    try {
      const res = await invoke('convert_text', { text });
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
    els.nlResult.style.display = 'block';
    els.latexCode.textContent = res.latex;
    els.markdownCode.textContent = '$$' + res.latex + '$$';
    els.resultValid.className = 'valid-badge ' + (res.valid ? 'ok' : 'err');
    els.resultValid.textContent = res.valid ? '✓ Valid' : '✗ Invalid';
    els.resultSource.className = 'source-badge ' + (res.source === 'shorthand' ? 'shorthand' : 'model');
    els.resultSource.textContent = res.source === 'shorthand' ? '⚡ shorthand' : '🤖 model';
    setIntent('∫', (res.intent || 'unknown') + ' · ' + Number(res.latency_ms || 0).toFixed(1) + 'ms');
    updateRender();
  }

  function updateRender() {
    if (!lastResult) return;
    if (renderMode === 'katex') {
      els.katexSection.style.display = 'block';
      els.latexSection.style.display = 'none';
      if (window.katex) {
        try {
          els.renderPreview.innerHTML = '';
          window.katex.render(lastResult.latex, els.renderPreview, { throwOnError: false, displayMode: true });
        } catch (e) {
          els.renderPreview.textContent = lastResult.latex;
        }
      } else if (lastResult.katex_html) {
        els.renderPreview.innerHTML = lastResult.katex_html;
      } else {
        els.renderPreview.textContent = lastResult.latex;
      }
    } else {
      els.katexSection.style.display = 'none';
      els.latexSection.style.display = 'block';
      els.latexPreview.innerHTML = highlightLatex(lastResult.latex);
    }
  }

  function highlightLatex(latex) {
    return String(latex)
      .replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')
      .replace(/(\\\\[a-zA-Z]+)/g, '<span style="color:#bb9af7">$1</span>')
      .replace(/([{}])/g, '<span style="color:#565f89">$1</span>')
      .replace(/([～^])/g, '<span style="color:#ff9e64">$1</span>');
  }

  function showError(msg) {
    els.nlResult.style.display = 'block';
    els.nlResult.innerHTML = '<div class="error-box"><span class="icon">⚠️</span><div>' + escapeHtml(msg) + '</div></div>';
  }

  async function copyMain() {
    if (!lastResult) return;
    await writeClipboard(lastResult.copy_text || lastResult.latex);
    await hideWindow();
  }

  // ── Keyboard ──
  document.addEventListener('keydown', e => {
    if (e.key === 'Escape') { e.preventDefault(); hideWindow(); return; }
    if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
      e.preventDefault(); toggleRenderMode(); return;
    }
    if (!e.metaKey && !e.ctrlKey && !e.altKey && /^[1-6]$/.test(e.key)) {
      const tabs = ['nl', 'ocr', 'complete', 'shorthand', 'history', 'settings'];
      switchTab(tabs[parseInt(e.key) - 1]);
      return;
    }
    const activeInput = document.activeElement;
    if (activeInput && activeInput.classList.contains('input-box')) {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        if (currentTab === 'nl') doConvert();
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

  // ── Header drag (JS-coordinated) ──
  const header = document.querySelector('.panel-header');
  if (header) {
    header.addEventListener('mousedown', e => {
      if (e.button !== 0) return;
      // Let clicks on interactive children behave normally
      if (e.target.closest('.panel-kbd, .panel-status')) return;
      invoke('start_window_drag', { x: e.screenX, y: e.screenY });
    });
    window.addEventListener('mouseup', e => {
      if (e.button === 0) invoke('end_window_drag', {});
    });
  }

  // ── Buttons ──
  $('#btn-copy-main').addEventListener('click', copyMain);
  $('#btn-copy-src').addEventListener('click', () => { if (lastResult) writeClipboard(lastResult.latex); });
  $('#btn-copy-md').addEventListener('click', () => { if (lastResult) writeClipboard('$$' + lastResult.latex + '$$'); });
  $('#btn-retry').addEventListener('click', doConvert);

  // ── Shorthand ──
  async function loadShorthands() {
    try {
      const res = await fetch(API_BASE + '/api/shorthands');
      const items = await res.json();
      renderShorthands(items);
    } catch (e) {
      els.shorthandGrid.innerHTML = '<div class="empty-state"><div class="text">无法加载缩写库</div></div>';
    }
  }
  function renderShorthands(items) {
    if (!items || !items.length) {
      els.shorthandGrid.innerHTML = '<div class="empty-state"><div class="text">暂无自定义缩写</div></div>';
      return;
    }
    els.shorthandGrid.innerHTML = items.map(i =>
      '<div class="shorthand-card" data-key="' + escapeHtml(i.key) + '">' +
      '<div class="shorthand-key">' + escapeHtml(i.key) + '</div>' +
      '<div class="shorthand-val">' + escapeHtml(i.value) + '</div></div>'
    ).join('');
    els.shorthandGrid.querySelectorAll('.shorthand-card').forEach(c => {
      c.addEventListener('click', () => {
        els.nlInput.value = c.dataset.key;
        switchTab('nl');
        doConvert();
      });
    });
  }

  // ── History ──
  let historyData = [];
  function saveHistory(input, latex) {
    historyData.unshift({ input, latex, time: Date.now() });
    if (historyData.length > 100) historyData.pop();
    try { localStorage.setItem('texada-history', JSON.stringify(historyData.slice(0, 50))); } catch(e){}
  }
  function loadHistoryLocal() {
    try { historyData = JSON.parse(localStorage.getItem('texada-history') || '[]'); } catch(e){ historyData = []; }
  }
  async function loadHistory() {
    loadHistoryLocal();
    renderHistory(historyData);
  }
  function renderHistory(items) {
    if (!items.length) {
      els.historyList.innerHTML = '<div class="empty-state"><div class="text">暂无历史记录</div></div>';
      return;
    }
    els.historyList.innerHTML = items.slice(0, 50).map(h =>
      '<div class="history-item" data-latex="' + escapeHtml(h.latex) + '">' +
      '<div class="history-input"><div class="history-input-text">' + escapeHtml(h.input) + '</div>' +
      '<div class="history-input-meta"><span>' + escapeHtml(h.latex.substring(0,40)) + (h.latex.length>40?'…':'') + '</span></div></div>' +
      '<div class="history-render">📋</div></div>'
    ).join('');
    els.historyList.querySelectorAll('.history-item').forEach(item => {
      item.addEventListener('click', () => { writeClipboard(item.dataset.latex); });
    });
  }

  function escapeHtml(str) {
    return String(str).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
  }

  applyPlatformLabels();

  // ── Auto-focus & clipboard on show ──
  async function onWindowShownHandler() {
    try { await checkBackend(); } catch (e) { console.warn('checkBackend failed', e); }
    if (currentTab === 'nl') {
      let clip = '';
      try { clip = await readClipboard(); } catch (e) { console.warn('readClipboard failed', e); }
      if (clip && clip.length > 0 && clip.length < 500 && !els.nlInput.value) {
        els.nlInput.value = clip;
      }
      // Delay focus so the WebView / window can finish becoming key.
      setTimeout(() => {
        if (els.nlInput) {
          els.nlInput.focus();
          els.nlInput.click();
        }
      }, 50);
    }
  }

  // Also run on load for browser dev mode
  if (!isSwift && !isTauri) {
    onWindowShownHandler();
  }

  console.log('TeXada Shell loaded. Tauri:', isTauri, 'Swift:', isSwift);
})();
