'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(require('node:path').join(__dirname, '../tauri-shell/src/main.js'), 'utf8');
const start = source.indexOf('  async function llamaPull()');
const end = source.indexOf('\n  // ── OCR', start);
const functionSource = source.slice(start, end);

test('model download uses the resolved backend and consumes split progress events', async () => {
  let calledUrl;
  let refreshed = false;
  const encoded = new TextEncoder().encode('{"file":"model.gguf","received":4,"total":4,"done":true}\n');
  const chunks = [encoded.slice(0, 11), encoded.slice(11)];
  const context = {
    API_BASE: 'http://127.0.0.1:19321',
    els: { llamaPullProgress: { textContent: '' } },
    t: key => key,
    TextDecoder,
    fetch: async url => {
      calledUrl = url;
      return { ok: true, body: { getReader: () => ({ read: async () => chunks.length
        ? { done: false, value: chunks.shift() } : { done: true } }) } };
    },
    refreshLlamaStatus: async () => { refreshed = true; },
  };
  vm.createContext(context);
  await vm.runInContext(functionSource + '\nllamaPull();', context);
  assert.equal(calledUrl, 'http://127.0.0.1:19321/api/llama/pull');
  assert.equal(context.els.llamaPullProgress.textContent, 'llama.pullDone: model.gguf');
  assert.equal(refreshed, true);
});
