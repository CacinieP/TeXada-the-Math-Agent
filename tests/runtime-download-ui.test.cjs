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

function pullElements() {
  return {
    llamaPullProgress: { textContent: '' },
    llamaPullTrack: {
      hidden: true,
      classList: { add() {}, remove() {} },
      attributes: {},
      setAttribute(name, value) { this.attributes[name] = value; },
    },
    llamaPullFill: { style: {} },
  };
}

function pullContext(events) {
  const encoded = events
    .map(event => new TextEncoder().encode(JSON.stringify(event) + '\n'))
    .reduce((parts, chunk) => parts.concat(Array.from(chunk)), []);
  const chunks = encoded.length ? [new Uint8Array(encoded)] : [];
  const context = {
    API_BASE: 'http://127.0.0.1:19321',
    els: pullElements(),
    t: key => key,
    TextDecoder,
    Date: { now: () => 0 },
    fetch: async () => ({
      ok: true,
      body: { getReader: () => ({ read: async () => chunks.length
        ? { done: false, value: chunks.shift() } : { done: true } }) },
    }),
    refreshLlamaStatus: async () => {},
  };
  return context;
}

test('model download drives a determinate progress bar with size and speed', async () => {
  const context = pullContext([
    { file: 'model.gguf', received: 512, total: 1024, done: false },
  ]);
  vm.createContext(context);
  await vm.runInContext(functionSource + '\nllamaPull();', context);

  const { llamaPullTrack, llamaPullFill, llamaPullProgress } = context.els;
  assert.equal(llamaPullTrack.hidden, false);
  assert.equal(llamaPullTrack.attributes['aria-valuenow'], '50');
  assert.equal(llamaPullFill.style.width, '50%');
  assert.equal(llamaPullProgress.textContent, 'llama.pullProgress');
  assert.equal(
    vm.runInContext('formatPullSize(1536 * 1024)', context),
    '1.5',
  );
});

test('a finished download fills the bar and marks it done', async () => {
  const context = pullContext([
    { file: 'model.gguf', received: 1024, total: 1024, done: true },
  ]);
  const done = [];
  context.els.llamaPullTrack.classList.add = name => done.push(name);
  vm.createContext(context);
  await vm.runInContext(functionSource + '\nllamaPull();', context);

  assert.equal(context.els.llamaPullTrack.attributes['aria-valuenow'], '100');
  assert.equal(context.els.llamaPullFill.style.width, '100%');
  assert.deepEqual(done, ['done']);
});

test('a failed download hides the progress bar', async () => {
  const context = pullContext([
    { file: 'model.gguf', received: 512, total: 1024, done: false, error: 'boom' },
  ]);
  vm.createContext(context);
  await vm.runInContext(functionSource + '\nllamaPull();', context);

  assert.equal(context.els.llamaPullProgress.textContent, 'llama.pullFailed: boom');
  assert.equal(context.els.llamaPullTrack.hidden, true);
});
