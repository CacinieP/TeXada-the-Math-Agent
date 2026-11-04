'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const { ReadableStream } = require('node:stream/web');
const source = fs.readFileSync(require('node:path').join(__dirname, '../tauri-shell/src/main.js'), 'utf8');
const start = source.indexOf('  async function llamaPull()');
const end = source.indexOf('\n  // ── OCR', start);
const functionSource = source.slice(start, end);
const visibilitySource = source.slice(source.indexOf('  function llamaSettingsDraft()'), source.indexOf('  function renderLlamaStatus('));
const i18nSource = source.slice(source.indexOf('  const I18N = {'), source.indexOf('  // ── DOM refs ──'));
const translationSource = source.slice(source.indexOf('  function t(key, values = {})'), source.indexOf('  function applyLanguage()'));
const COMPLETE = { all_done: true, success: true };
const MIB = 1024 * 1024;

function controlledStream() {
  let controller;
  let cancellations = 0;
  const stream = new ReadableStream({
    start(value) { controller = value; },
    cancel() { cancellations += 1; },
  });
  return {
    stream,
    enqueue: bytes => controller.enqueue(bytes),
    event: event => controller.enqueue(new TextEncoder().encode(JSON.stringify(event) + '\n')),
    close: () => controller.close(),
    error: error => controller.error(error),
    get cancellations() { return cancellations; },
  };
}

function closedStream(events) {
  const controlled = controlledStream();
  events.forEach(controlled.event);
  controlled.close();
  return controlled;
}

function fixture(responses = [], language = 'en') {
  const attributes = {};
  const buttonAttributes = {};
  const classes = new Set();
  const requests = [];
  let clock = 0;
  let refreshes = 0;
  const els = {
    backendSelect: { value: 'llama_server' },
    llamaHostInput: { value: '' }, llamaBinaryInput: { value: '' }, llamaModelsDirInput: { value: '' },
    btnLlamaPull: {
      disabled: false,
      setAttribute: (name, value) => { buttonAttributes[name] = value; },
      getAttribute: name => buttonAttributes[name],
      removeAttribute: name => { delete buttonAttributes[name]; },
    },
    llamaPullProgress: { textContent: '' },
    llamaPullTrack: {
      hidden: true,
      classList: { add: name => classes.add(name), remove: name => classes.delete(name) },
      setAttribute: (name, value) => { attributes[name] = value; },
    },
    llamaPullFill: { style: {} },
  };
  const context = {
    API_BASE: 'http://127.0.0.1:19321',
    els, TextDecoder, llamaPullActive: false,
    savedBackend: 'llama_server', savedLlamaSettings: { host: '', binary: '', models: '' },
    backendSettingsSaving: false,
    document: { querySelectorAll: () => [], getElementById: () => null },
    uiLanguage: language, Date: { now: () => clock },
    fetch: async (url, options) => {
      requests.push({ url, options });
      const response = responses.shift();
      assert.ok(response, 'unexpected request');
      if (response instanceof Error) throw response;
      return { ok: (response.status || 200) < 400, status: response.status || 200, body: response.controlled.stream };
    },
    refreshLlamaStatus: async () => { refreshes += 1; },
  };
  vm.createContext(context);
  // Use the actual application translations and interpolation helper; a stub
  // that leaves placeholders intact conceals missing t(key, values) arguments.
  vm.runInContext(i18nSource + '\n' + translationSource + '\n' + functionSource + '\n' + visibilitySource, context);
  return {
    context, els, attributes, classes, requests,
    start: () => vm.runInContext('llamaPull()', context),
    setClock: value => { clock = value; },
    get refreshes() { return refreshes; },
  };
}

async function settle() {
  await new Promise(resolve => setImmediate(resolve));
  await new Promise(resolve => setImmediate(resolve));
}

function assertRecovered(f, controlled) {
  assert.equal(f.context.llamaPullActive, false);
  assert.equal(f.els.btnLlamaPull.disabled, false);
  assert.equal(f.els.btnLlamaPull.getAttribute('aria-busy'), undefined);
  assert.equal(controlled.stream.locked, false);
}

test('model download uses the resolved backend and consumes split progress events', async () => {
  const controlled = controlledStream();
  const bytes = new TextEncoder().encode([
    JSON.stringify({ file: '模型.gguf', received: 4, total: 4, done: true }), JSON.stringify(COMPLETE),
  ].join('\n') + '\n');
  // Split the event and a multi-byte filename character across actual stream chunks.
  for (const chunk of [bytes.slice(0, 10), bytes.slice(10, 11), bytes.slice(11)]) controlled.enqueue(chunk);
  controlled.close();
  const f = fixture([{ controlled }]); await f.start();
  assert.equal(f.requests[0].url, 'http://127.0.0.1:19321/api/llama/pull');
  assert.deepEqual(JSON.parse(f.requests[0].options.body), { mirror: false });
  assert.equal(f.els.llamaPullProgress.textContent, 'Model download complete');
  assert.equal(f.refreshes, 1);
  assertRecovered(f, controlled);
});

test('model download drives a determinate progress bar with size and speed', async () => {
  const controlled = controlledStream(); const f = fixture([{ controlled }]);
  const downloading = f.start();
  controlled.event({ file: 'model.gguf', received: MIB, total: 4 * MIB, done: false });
  await settle(); f.setClock(1000);
  controlled.event({ file: 'model.gguf', received: 2 * MIB, total: 4 * MIB, done: false });
  await settle();
  assert.equal(f.els.llamaPullTrack.hidden, false);
  assert.equal(f.attributes['aria-valuenow'], '50');
  assert.equal(f.els.llamaPullFill.style.width, '50%');
  assert.match(f.els.llamaPullProgress.textContent, /model\.gguf: 50%.*1\.0 MB\/s/);
  assert.equal(vm.runInContext('formatPullSize(1536 * 1024)', f.context), '1.5');
  controlled.event(COMPLETE); controlled.close(); await downloading;
});

for (const [language, expected] of [
  ['zh', '权重.gguf：50% · 256.0/512.0 MB · 1.0 MB/s · 剩余约 5 分钟'],
  ['en', '权重.gguf: 50% · 256.0/512.0 MB · 1.0 MB/s · ETA 5 min'],
]) {
  test(`production ${language} translations retain filename, percent, sizes, speed and ETA`, async () => {
    const controlled = controlledStream(); const f = fixture([{ controlled }], language);
    const downloading = f.start();
    controlled.event({ file: '权重.gguf', received: 128 * MIB, total: 512 * MIB });
    await settle(); f.setClock(128000);
    controlled.event({ file: '权重.gguf', received: 256 * MIB, total: 512 * MIB });
    await settle();
    assert.equal(f.els.llamaPullProgress.textContent, expected);
    assert.doesNotMatch(f.els.llamaPullProgress.textContent, /\{(?:file|percent|received|total|rate|minutes|speed)\}/);
    controlled.event(COMPLETE); controlled.close(); await downloading;
    assert.equal(f.els.llamaPullProgress.textContent, language === 'zh' ? '模型下载完成' : 'Model download complete');
  });
}

test('only the overall terminal event marks the download complete', async () => {
  const controlled = controlledStream(); const f = fixture([{ controlled }]);
  const downloading = f.start();
  controlled.event({ file: 'model.gguf', received: 1024, total: 1024, done: true });
  await settle();
  assert.equal(f.classes.has('done'), false);
  assert.notEqual(f.els.llamaPullProgress.textContent, 'Model download complete');
  controlled.event(COMPLETE); controlled.close(); await downloading;
  assert.equal(f.attributes['aria-valuenow'], '100');
  assert.equal(f.els.llamaPullFill.style.width, '100%');
  assert.equal(f.classes.has('done'), true);
  assertRecovered(f, controlled);
});

test('a failed download preserves the real error and hides the progress bar', async () => {
  const controlled = closedStream([
    { file: 'model.gguf', received: 512, total: 1024, error: 'checksum mismatch' },
    { all_done: true, success: false, error: 'checksum mismatch' },
  ]);
  const f = fixture([{ controlled }]); await f.start();
  assert.equal(f.els.llamaPullProgress.textContent, 'Download failed: checksum mismatch');
  assert.equal(f.els.llamaPullTrack.hidden, true);
  assertRecovered(f, controlled);
});

test('all verified existing files still reach the overall completed state', async () => {
  const controlled = closedStream([
    { file: 'model.gguf', received: 10, total: 10, done: true, skipped: true, role: 'text' },
    { file: 'model.gguf', received: 10, total: 10, done: true, skipped: true, role: 'vision' },
    { file: 'projector.gguf', received: 20, total: 20, done: true, skipped: true }, COMPLETE,
  ]);
  const f = fixture([{ controlled }]); await f.start();
  assert.equal(f.els.llamaPullProgress.textContent, 'Model download complete');
  assert.equal(f.classes.has('done'), true);
  assertRecovered(f, controlled);
});

for (const [name, events] of [
  ['empty stream', []],
  ['partial progress', [{ file: 'model.gguf', received: 17, total: 100, done: false }]],
  ['one finished file', [{ file: 'model.gguf', received: 100, total: 100, done: true }]],
  ['only skipped files', [{ file: 'model.gguf', received: 100, total: 100, done: true, skipped: true }]],
]) {
  test(`EOF without an overall terminal is retryable interruption: ${name}`, async () => {
    const controlled = closedStream(events); const f = fixture([{ controlled }]); await f.start();
    assert.match(f.els.llamaPullProgress.textContent, /^Download interrupted.*retry or resume/);
    assert.equal(f.classes.has('done'), false);
    assert.equal(f.els.llamaPullTrack.hidden, true);
    assertRecovered(f, controlled);
  });
}

for (const [name, bytes] of [
  ['bad JSON', new TextEncoder().encode('{not JSON}\n')],
  ['invalid UTF-8', new Uint8Array([0xff, 0x0a])],
  ['truncated UTF-8', new Uint8Array([0xe4])],
  ['wrong terminal type', new TextEncoder().encode('{"all_done":true,"success":"true"}\n')],
]) {
  test(`malformed stream is interrupted and its reader is released: ${name}`, async () => {
    const controlled = controlledStream(); controlled.enqueue(bytes);
    if (name === 'truncated UTF-8') controlled.close();
    const f = fixture([{ controlled }]); await f.start();
    assert.match(f.els.llamaPullProgress.textContent, /^Download interrupted/);
    if (name !== 'truncated UTF-8') assert.equal(controlled.cancellations, 1);
    assertRecovered(f, controlled);
  });
}

test('a complete final JSON record is consumed even without a trailing newline', async () => {
  const controlled = controlledStream();
  controlled.enqueue(new TextEncoder().encode(JSON.stringify(COMPLETE))); controlled.close();
  const f = fixture([{ controlled }]); await f.start();
  assert.equal(f.els.llamaPullProgress.textContent, 'Model download complete');
  assertRecovered(f, controlled);
});

test('a successful terminal cannot launder an earlier file error', async () => {
  const controlled = closedStream([{ file: 'model.gguf', error: 'HTTP 403' }, COMPLETE]);
  const f = fixture([{ controlled }]); await f.start();
  assert.equal(f.els.llamaPullProgress.textContent, 'Download failed: HTTP 403');
  assert.equal(f.classes.has('done'), false);
  assertRecovered(f, controlled);
});

test('a failure terminal without detail still fails', async () => {
  const controlled = closedStream([{ all_done: true, success: false }]);
  const f = fixture([{ controlled }]); await f.start();
  assert.equal(f.els.llamaPullProgress.textContent, 'Download failed');
  assertRecovered(f, controlled);
});

test('new file progress starts its own resume speed baseline without completion styling', async () => {
  const controlled = controlledStream(); const f = fixture([{ controlled }]);
  const downloading = f.start();
  controlled.event({ file: 'weights', received: 100 * MIB, total: 101 * MIB, resumed: true });
  await settle(); f.setClock(1000);
  controlled.event({ file: 'weights', received: 101 * MIB, total: 101 * MIB, done: true });
  await settle(); f.setClock(2000);
  controlled.event({ file: 'projector', received: MIB, total: 4 * MIB });
  await settle();
  assert.equal(f.classes.has('done'), false);
  assert.equal(f.attributes['aria-valuenow'], '25');
  assert.doesNotMatch(f.els.llamaPullProgress.textContent, /MB\/s/);
  f.setClock(3000);
  controlled.event({ file: 'projector', received: 2 * MIB, total: 4 * MIB });
  await settle();
  assert.match(f.els.llamaPullProgress.textContent, /projector: 50%.*1\.0 MB\/s/);
  controlled.event(COMPLETE); controlled.close(); await downloading;
});

test('duplicate clicks do not create another request or reenable the active download button', async () => {
  const controlled = controlledStream(); const f = fixture([{ controlled }]);
  const downloading = f.start(); await settle(); await f.start();
  f.context.updateLlamaSectionVisibility();
  assert.equal(f.requests.length, 1);
  assert.equal(f.els.btnLlamaPull.disabled, true);
  assert.equal(f.els.btnLlamaPull.getAttribute('aria-busy'), 'true');
  controlled.event(COMPLETE); controlled.close(); await downloading;
  assertRecovered(f, controlled);
});

test('interrupted download can be retried with resumed bytes', async () => {
  const interrupted = closedStream([{ file: 'weights', received: 10, total: 20 }]);
  const resumed = closedStream([{ file: 'weights', received: 20, total: 20, done: true, resumed: true }, COMPLETE]);
  const f = fixture([{ controlled: interrupted }, { controlled: resumed }]);
  await f.start(); assert.match(f.els.llamaPullProgress.textContent, /^Download interrupted/);
  assertRecovered(f, interrupted); await f.start();
  assert.equal(f.requests.length, 2);
  assert.equal(f.els.llamaPullProgress.textContent, 'Model download complete');
  assertRecovered(f, resumed);
});

test('HTTP errors never complete successfully and their response stream is canceled', async () => {
  const controlled = controlledStream(); const f = fixture([{ controlled, status: 403 }]);
  await f.start();
  assert.equal(f.els.llamaPullProgress.textContent, 'Download failed: HTTP 403');
  assert.equal(controlled.cancellations, 1);
  assertRecovered(f, controlled);
});

test('a rejected read preserves the network error and restores controls', async () => {
  const controlled = controlledStream(); const f = fixture([{ controlled }]);
  const downloading = f.start(); await settle();
  controlled.error(new Error('network interrupted')); await downloading;
  assert.equal(f.els.llamaPullProgress.textContent, 'Download failed: network interrupted');
  assertRecovered(f, controlled);
});

test('completion cannot enable a download button while its saved settings are dirty', async () => {
  const controlled = controlledStream(); const f = fixture([{ controlled }]);
  const downloading = f.start(); await settle();
  f.els.llamaModelsDirInput.value = '/different-model-directory';
  controlled.event(COMPLETE); controlled.close(); await downloading;
  assert.equal(f.context.llamaPullActive, false);
  assert.equal(f.els.btnLlamaPull.disabled, true);
  f.els.llamaModelsDirInput.value = ''; f.context.updateLlamaSectionVisibility();
  assert.equal(f.els.btnLlamaPull.disabled, false);
});
