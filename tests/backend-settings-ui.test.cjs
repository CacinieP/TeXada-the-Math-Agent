'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../tauri-shell/src/main.js'), 'utf8');
const settings = source.slice(source.indexOf('  async function loadBackendSettings()'), source.indexOf('  // ── llama-server runtime'));
const visibility = source.slice(source.indexOf('  function llamaSettingsDraft()'), source.indexOf('  function renderLlamaStatus'));
const defaults = {
  backend: 'llama_server', ollama_host: 'http://localhost:11434', model_name: 'text-a', vision_model_name: 'ocr-b',
  openai_base_url: 'https://example.test/v1', openai_model_name: 'remote-text', openai_vision_model_name: 'remote-ocr',
  openai_api_key_set: true, openai_vision_api_key_set: true, openai_vision_base_url: 'https://ocr.example.test/v1', inference_timeout_seconds: 90, api_request_timeout_seconds: 240,
  llama_server_host: 'http://127.0.0.1:8080', llama_server_binary: '', llama_models_dir: '',
};
function fixture() {
  const panels = ['llama_server', 'ollama', 'openai_compatible', 'llama_server', 'llama_server'].map(backendPanel => ({dataset: {backendPanel}, hidden: false}));
  const els = {};
  for (const name of ['backendSelect', 'ollamaHostInput', 'localModelInput', 'localVisionModelInput', 'openaiEndpointInput', 'openaiModelInput', 'openaiVisionModelInput', 'openaiVisionEndpointInput', 'openaiVisionKeyInput', 'openaiKeyInput', 'inferenceTimeoutInput', 'apiTimeoutInput', 'llamaHostInput', 'llamaBinaryInput', 'llamaModelsDirInput', 'backendSaveStatus', 'btnLlamaStart', 'btnLlamaStop', 'btnLlamaPull']) els[name] = { value: '', disabled: false, textContent: '' };
  const nodes = {'backend-save-note': {hidden: false}, 'btn-save-backend': {disabled: false}};
  const sent = [];
  let persisted = {...defaults};
  const context = {
    els, savedBackend: null, savedLlamaSettings: null, backendSettingsSaving: false, DEFAULT_REQUEST_TIMEOUT_MS: 240000,
    document: {querySelectorAll: () => panels, getElementById: id => nodes[id]}, t: key => key,
    apiGetBackendSettings: async () => ({...persisted}),
    apiSaveBackendSettings: async payload => { sent.push({...payload}); persisted = {...persisted, ...payload}; return {...persisted}; },
    refreshLlamaStatus: async () => {}, checkBackend: async () => {},
  };
  vm.createContext(context); vm.runInContext(settings + visibility, context);
  return {context, els, panels, nodes, sent, persisted: () => persisted};
}

test('three backend choices show only their own fields and retain text/OCR drafts', async () => {
  const f = fixture(); await f.context.loadBackendSettings();
  f.els.localModelInput.value = 'draft-text'; f.els.localVisionModelInput.value = 'draft-ocr';
  for (const backend of ['ollama', 'openai_compatible', 'llama_server']) {
    f.els.backendSelect.value = backend; f.context.updateLlamaSectionVisibility();
    for (const panel of f.panels) assert.equal(panel.hidden, panel.dataset.backendPanel !== backend);
  }
  assert.equal(f.els.localModelInput.value, 'draft-text'); assert.equal(f.els.localVisionModelInput.value, 'draft-ocr');
});

test('saving local settings cannot overwrite hidden remote drafts or transmit their API key', async () => {
  const f = fixture(); await f.context.loadBackendSettings();
  f.els.openaiKeyInput.value = 'unsaved-private-key'; f.els.openaiVisionKeyInput.value = 'ocr-draft-key'; f.els.openaiEndpointInput.value = 'invalid hidden draft';
  f.els.backendSelect.value = 'ollama'; f.els.localModelInput.value = 'new-text'; f.els.localVisionModelInput.value = 'new-ocr';
  await f.context.saveBackendSettings();
  assert.deepEqual(Object.keys(f.sent[0]).sort(), ['backend','inference_timeout_seconds','api_request_timeout_seconds','ollama_host','model_name','vision_model_name'].sort());
  assert.equal(f.persisted().openai_base_url, defaults.openai_base_url); assert.equal(f.els.openaiKeyInput.value, 'unsaved-private-key');
  assert.equal(f.els.openaiVisionKeyInput.value, 'ocr-draft-key');
  await f.context.loadBackendSettings();
  assert.equal(f.els.localModelInput.value, 'new-text'); assert.equal(f.els.localVisionModelInput.value, 'new-ocr');
});

test('built-in save leaves Ollama models untouched; remote save keeps separate roles and blank key unchanged', async () => {
  const f = fixture(); await f.context.loadBackendSettings();
  f.els.localModelInput.value = ''; await f.context.saveBackendSettings();
  assert.equal(f.persisted().model_name, defaults.model_name);
  f.els.backendSelect.value = 'openai_compatible'; f.els.openaiModelInput.value = 'text-new'; f.els.openaiVisionModelInput.value = 'ocr-new';
  await f.context.saveBackendSettings(); assert.equal(f.persisted().openai_model_name, 'text-new'); assert.equal(f.persisted().openai_vision_model_name, 'ocr-new');
  assert.equal('openai_api_key' in f.sent[1], false);
  f.els.openaiKeyInput.value = 'new-key'; await f.context.saveBackendSettings();
  assert.equal(f.sent[2].openai_api_key, 'new-key'); assert.equal(f.els.openaiKeyInput.value, '');
});

test('unsaved backend and failed save keep runtime controls disabled; successful save enables them', async () => {
  const f = fixture(); await f.context.loadBackendSettings();
  f.els.backendSelect.value = 'ollama'; await f.context.saveBackendSettings();
  f.els.backendSelect.value = 'llama_server'; f.context.updateLlamaSectionVisibility();
  assert.equal(f.els.btnLlamaStart.disabled, true); assert.equal(f.nodes['backend-save-note'].hidden, false);
  const save = f.context.apiSaveBackendSettings;
  f.context.apiSaveBackendSettings = async () => {throw new Error('HTTP 422');};
  await f.context.saveBackendSettings();
  assert.equal(f.els.btnLlamaStart.disabled, true); assert.equal(f.els.backendSelect.disabled, false);
  f.context.apiSaveBackendSettings = save; await f.context.saveBackendSettings();
  assert.equal(f.els.btnLlamaStart.disabled, false); assert.equal(f.nodes['backend-save-note'].hidden, true);
});

test('in-flight saves disable controls and ignore duplicate save clicks', async () => {
  const f = fixture(); await f.context.loadBackendSettings();
  let finish;
  f.context.apiSaveBackendSettings = payload => new Promise(resolve => {finish = () => resolve({...defaults,...payload});});
  const saving = f.context.saveBackendSettings();
  assert.equal(f.els.backendSelect.disabled, true); assert.equal(f.els.btnLlamaStart.disabled, true);
  await f.context.saveBackendSettings(); finish(); await saving;
  assert.equal(f.els.backendSelect.disabled, false); assert.equal(f.els.btnLlamaStart.disabled, false);
});


test('editing runtime paths disables service actions until that exact draft is saved', async () => {
  const f = fixture(); await f.context.loadBackendSettings();
  f.els.llamaModelsDirInput.value = '/new-model-directory'; f.context.updateLlamaSectionVisibility();
  assert.equal(f.els.btnLlamaPull.disabled, true);
  await f.context.saveBackendSettings(); assert.equal(f.els.btnLlamaPull.disabled, false);
  f.els.llamaHostInput.value = 'http://127.0.0.1:8081'; f.context.updateLlamaSectionVisibility();
  assert.equal(f.els.btnLlamaStart.disabled, true);
});


test('remote text and OCR each save their own endpoint, model and key', async () => {
  const f = fixture(); await f.context.loadBackendSettings();
  f.els.backendSelect.value = 'openai_compatible';
  f.els.openaiEndpointInput.value = 'https://text.example.test/v1';
  f.els.openaiVisionEndpointInput.value = 'https://vision.example.test/v1';
  f.els.openaiKeyInput.value = 'text-key'; f.els.openaiVisionKeyInput.value = 'vision-key';
  await f.context.saveBackendSettings();
  assert.equal(f.sent[0].openai_base_url, 'https://text.example.test/v1');
  assert.equal(f.sent[0].openai_vision_base_url, 'https://vision.example.test/v1');
  assert.equal(f.sent[0].openai_api_key, 'text-key');
  assert.equal(f.sent[0].openai_vision_api_key, 'vision-key');
  assert.equal(f.els.openaiKeyInput.value, ''); assert.equal(f.els.openaiVisionKeyInput.value, '');
  await f.context.saveBackendSettings();
  assert.equal('openai_vision_api_key' in f.sent[1], false);
});

test('unverified and failed inference stay visible without restarting API wait', async () => {
  const statusSource = source.slice(source.indexOf('  function backendStatusText('), source.indexOf('  async function apiJson('));
  const checkSource = source.slice(source.indexOf('  async function checkBackend('), source.indexOf('  function waitForBackendStartup('));
  for (const status of ['unverified', 'inference_failed']) {
    const info = {backend: 'ollama', status, ready: false, message: 'Inference needs attention', next_action: 'Switch to built-in llama-server'};
    const classes = new Set();
    const dot = {classList: {add: value => classes.add(value)}};
    const span = {};
    const statusDot = {querySelector: selector => selector === '.dot' ? dot : span};
    const context = {els: {statusDot}, t: key => key, isTauri: false, apiJson: async () => info};
    vm.createContext(context); vm.runInContext(statusSource + checkSource, context);
    assert.equal(await context.checkBackend(), true); // API reachable, inference not ready
    assert.equal(span.textContent, info.message);
    assert.match(statusDot.title, /Switch to built-in/);
    assert.ok(classes.has('offline'));
    if (status === 'unverified') assert.ok(classes.has('warning'));
  }
});
