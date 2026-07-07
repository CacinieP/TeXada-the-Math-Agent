(function () {
  'use strict';

  const DEFAULT_API_PORT = '18732';

  function normalizeApiBase(value) {
    const raw = String(value || '').trim();
    if (!raw) return '';
    try {
      return new URL(raw, window.location.href).origin;
    } catch (e) {
      return raw.replace(/\/+$/, '');
    }
  }

  function readMeta(name) {
    const el = document.querySelector(`meta[name="${name}"]`);
    return el ? el.getAttribute('content') : '';
  }

  function readQuery(name) {
    try {
      return new URLSearchParams(window.location.search).get(name) || '';
    } catch (e) {
      return '';
    }
  }

  function readLocalStorage(key) {
    try {
      return window.localStorage ? window.localStorage.getItem(key) || '' : '';
    } catch (e) {
      return '';
    }
  }

  function explicitApiBase() {
    const cfg = window.__TEXADA_CONFIG__ || {};
    return normalizeApiBase(
      cfg.apiBase ||
      cfg.api_base ||
      readQuery('texadaApiBase') ||
      readQuery('apiBase') ||
      readLocalStorage('texada.apiBase') ||
      readMeta('texada-api-base')
    );
  }

  function derivedLocalApiBase() {
    const protocol = window.location.protocol === 'https:' ? 'https:' : 'http:';
    const host = window.location.hostname || '127.0.0.1';
    const port = readLocalStorage('texada.apiPort') || readMeta('texada-api-port') || DEFAULT_API_PORT;
    return `${protocol}//${host}:${port}`;
  }

  async function resolveApiBase(options = {}) {
    if (options.invoke) {
      try {
        const bridged = normalizeApiBase(await options.invoke('get_api_base'));
        if (bridged) return bridged;
      } catch (e) {
        // Browser development and older shells may not expose the bridge command.
      }
    }

    const explicit = explicitApiBase();
    if (explicit) return explicit;
    return derivedLocalApiBase();
  }

  window.TeXadaRuntime = {
    normalizeApiBase,
    resolveApiBase,
  };
})();
