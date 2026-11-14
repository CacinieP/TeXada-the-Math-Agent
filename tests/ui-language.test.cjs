'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname, '../tauri-shell/src/main.js'), 'utf8');
const initialLanguage = source.slice(
  source.indexOf('  const webviewLanguage ='),
  source.indexOf('  let uiZoom ='),
);
const normalizeLanguage = source.slice(
  source.indexOf('  function normalizeLanguage('),
  source.indexOf('  function normalizeZoom('),
);
const settingsUi = source.slice(
  source.indexOf('  function applyUiSettingsResponse('),
  source.indexOf('  async function loadBackendSettings('),
);

function fixture({ platform, language, isDesktop = true, storedLanguage }) {
  const storage = new Map(storedLanguage ? [['texada-ui-language', storedLanguage]] : []);
  const requests = [];
  const context = vm.createContext({
    isDesktop,
    navigator: { platform, language },
    localStorage: {
      getItem: key => storage.get(key),
      setItem: (key, value) => storage.set(key, value),
      removeItem: key => storage.delete(key),
    },
    normalizeZoom: Number,
    els: {},
    applyZoom() {},
    applyLanguage() {},
    refreshResultLabels() {},
    apiSaveUiSettings: async settings => {
      requests.push({ ...settings });
      return { ui_language: 'en', ui_language_explicit: false, ui_zoom: settings.ui_zoom };
    },
  });
  vm.runInContext(`${initialLanguage}\nlet uiZoom = 1.2;\n${normalizeLanguage}\n${settingsUi}`, context);
  return { storage, requests, run: code => vm.runInContext(code, context) };
}

test('Linux backend locale corrects the WebView default without persisting it', async () => {
  const f = fixture({ platform: 'Linux x86_64', language: 'zh-CN', storedLanguage: 'zh' });
  assert.equal(f.run('uiLanguage'), 'zh');
  await f.run('persistUiSettings()');
  assert.equal(f.run('uiLanguage'), 'en');
  assert.deepEqual(f.requests, [{ ui_zoom: 1.2 }]);
  assert.equal(f.storage.has('texada-ui-language'), false);
});

test('other platforms use the WebView locale until a preference is saved', () => {
  const f = fixture({ platform: 'Win32', language: 'zh-TW' });
  f.run('applyUiSettingsResponse({ui_language: "en", ui_language_explicit: false, ui_zoom: 1})');
  assert.equal(f.run('uiLanguage'), 'zh');
  f.run('applyUiSettingsResponse({ui_language: "en", ui_language_explicit: true, ui_zoom: 1})');
  assert.equal(f.run('uiLanguage'), 'en');
  assert.equal(f.storage.get('texada-ui-language'), 'en');
});
