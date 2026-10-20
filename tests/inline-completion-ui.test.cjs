'use strict';
/* Inline completion ghost-text UI tests (#40 slice 3).
 *
 * Slices the inline-completion module out of main.js and drives it in a vm
 * with mocked DOM/fetch/timers, mirroring tests/runtime-download-ui.test.cjs.
 */
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

const source = fs.readFileSync(
  path.join(__dirname, '../tauri-shell/src/main.js'), 'utf8',
);
const start = source.indexOf('  // ── Inline completion');
const end = source.indexOf('  // ── Completion ──', start);
assert.ok(start > 0 && end > start, 'inline completion module markers not found');
const moduleSource = source.slice(start, end);

const API_BASE = 'http://127.0.0.1:19321';
const SUGGESTION = { text: '\\placeholder{}', rule: 'binary_operand' };

function tick() {
  return new Promise(resolve => setTimeout(resolve, 0));
}

function makeContext(response, options = {}) {
  const listeners = {};
  const calls = [];
  const timers = [];
  const input = {
    value: '',
    selectionStart: 0,
    selectionEnd: 0,
    scrollTop: 0,
    scrollLeft: 0,
    focusCalls: 0,
    selectionRanges: [],
    rangeTexts: [],
    focus() { this.focusCalls += 1; },
    setSelectionRange(start, end) {
      this.selectionRanges.push([start, end]);
      this.selectionStart = start;
      this.selectionEnd = end;
    },
    setRangeText(text, start, end) {
      this.rangeTexts.push([text, start, end]);
      this.value = this.value.slice(0, start) + text + this.value.slice(end);
      this.selectionStart = this.selectionEnd = start + text.length;
    },
    addEventListener(type, fn) { (listeners[type] = listeners[type] || []).push(fn); },
  };
  const spans = {
    '.ghost-typed': { textContent: '' },
    '.ghost-text': { textContent: '' },
  };
  const ghost = {
    hidden: true,
    scrollTop: 0,
    scrollLeft: 0,
    querySelector(selector) { return spans[selector] || null; },
  };
  const context = {
    API_BASE,
    els: { completeInput: input, completeGhost: ghost },
    document: { execCommand: options.execCommand || (() => true) },
    setTimeout: (fn) => { timers.push(fn); return timers.length; },
    clearTimeout: () => {},
    fetch: async (url, init) => {
      const payload = JSON.parse(init.body);
      calls.push({ url, payload });
      // The server echoes the binding it was given.
      return {
        ok: true,
        json: async () => ({
          text: response === null ? null : response.text,
          rule: response === null ? null : response.rule,
          insert_at: 'cursor',
          source_hash: payload.source_hash,
          edit_version: payload.edit_version,
        }),
      };
    },
    calls, listeners, timers, input, ghost, spans,
  };
  return context;
}

async function runModule(context, driver) {
  vm.createContext(context);
  await vm.runInContext(moduleSource + '\n' + driver, context);
  // Let the fire-and-forget request promise settle.
  await tick();
  await tick();
  return context;
}

async function flushDebounce(context) {
  assert.equal(context.timers.length, 1, 'expected one debounced request');
  context.timers[0]();
  await tick();
  await tick();
}

const scheduleAndFlush = `
  bindInlineCompletion();
  scheduleInlineSuggestion();
`;

test('ghost text request splits the cursor context and echoes the binding', async () => {
  const context = makeContext(SUGGESTION);
  await runModule(context, `
    els.completeInput.value = 'x+';
    els.completeInput.selectionStart = 2;
    els.completeInput.selectionEnd = 2;
    ${scheduleAndFlush}
  `);
  await flushDebounce(context);

  assert.equal(context.calls.length, 1);
  assert.equal(context.calls[0].url, API_BASE + '/api/complete/inline');
  assert.deepEqual(context.calls[0].payload.before_cursor, 'x+');
  assert.equal(context.calls[0].payload.after_cursor, '');
  assert.match(context.calls[0].payload.source_hash, /^[0-9a-f]{8}$/);
  assert.equal(context.calls[0].payload.edit_version, 1);

  assert.equal(context.ghost.hidden, false);
  assert.equal(context.spans['.ghost-typed'].textContent, 'x+');
  assert.equal(context.spans['.ghost-text'].textContent, SUGGESTION.text);
});

test('a stale response is discarded instead of rendering', async () => {
  const context = makeContext(SUGGESTION);
  await runModule(context, `
    els.completeInput.value = 'x+';
    els.completeInput.selectionStart = 2;
    (async () => {
      const pending = requestInlineSuggestion();
      inlineEditVersion += 1;  // a newer keystroke wins the race
      await pending;
    })()
  `);

  assert.equal(context.calls.length, 1);
  assert.equal(context.ghost.hidden, true, 'stale candidate must not render');
});

test('no suggestion hides the ghost', async () => {
  const context = makeContext(null);
  await runModule(context, `
    els.completeInput.value = 'x+';
    els.completeInput.selectionStart = 2;
    els.completeInput.selectionEnd = 2;
    ${scheduleAndFlush}
  `);
  await flushDebounce(context);

  assert.equal(context.calls.length, 1);
  assert.equal(context.ghost.hidden, true);
});

test('Tab accepts the suggestion through the undoable input stack', async () => {
  const commands = [];
  const context = makeContext(SUGGESTION, {
    execCommand: (name, ...rest) => { commands.push([name, ...rest]); return true; },
  });
  await runModule(context, `
    els.completeInput.value = 'x+';
    els.completeInput.selectionStart = 2;
    els.completeInput.selectionEnd = 2;
    ${scheduleAndFlush}
  `);
  await flushDebounce(context);
  assert.equal(context.ghost.hidden, false);

  context.listeners.keydown[0]({ key: 'Tab', preventDefault() {} });

  assert.deepEqual(commands, [['insertText', false, SUGGESTION.text]]);
  assert.equal(context.input.focusCalls, 1);
  assert.deepEqual(context.input.selectionRanges.at(-1), [2, 2]);
  assert.equal(vm.runInContext('inlineEditVersion', context), 2);
  assert.equal(context.ghost.hidden, true);
});

test('Tab falls back to setRangeText when execCommand is unavailable', async () => {
  const context = makeContext(SUGGESTION, { execCommand: () => false });
  await runModule(context, `
    els.completeInput.value = 'x+';
    els.completeInput.selectionStart = 2;
    els.completeInput.selectionEnd = 2;
    ${scheduleAndFlush}
  `);
  await flushDebounce(context);

  context.listeners.keydown[0]({ key: 'Tab', preventDefault() {} });
  assert.deepEqual(context.input.rangeTexts, [[SUGGESTION.text, 2, 2]]);
  assert.equal(context.input.value, 'x+' + SUGGESTION.text);
  assert.equal(context.ghost.hidden, true);
});

test('Escape dismisses the ghost without touching the text', async () => {
  const commands = [];
  const context = makeContext(SUGGESTION, {
    execCommand: (name, ...rest) => { commands.push([name, ...rest]); return true; },
  });
  await runModule(context, `
    els.completeInput.value = 'x+';
    els.completeInput.selectionStart = 2;
    els.completeInput.selectionEnd = 2;
    ${scheduleAndFlush}
  `);
  await flushDebounce(context);
  assert.equal(context.ghost.hidden, false);

  context.listeners.keydown[0]({ key: 'Escape', preventDefault() {} });

  assert.equal(commands.length, 0, 'Escape must not insert anything');
  assert.equal(context.input.value, 'x+');
  assert.equal(context.ghost.hidden, true);
});

test('moving the cursor dismisses the stale ghost', async () => {
  const context = makeContext(SUGGESTION);
  await runModule(context, `
    els.completeInput.value = 'x+';
    els.completeInput.selectionStart = 2;
    els.completeInput.selectionEnd = 2;
    ${scheduleAndFlush}
  `);
  await flushDebounce(context);
  assert.equal(context.ghost.hidden, false);

  context.input.selectionStart = 0;  // arrow key / click moved the caret
  context.listeners.keyup[0]();
  assert.equal(context.ghost.hidden, true);
});

test('ghost text never calls the agent endpoints', async () => {
  const context = makeContext(SUGGESTION);
  await runModule(context, `
    els.completeInput.value = '\\\\frac{a}{';
    els.completeInput.selectionStart = 9;
    ${scheduleAndFlush}
  `);
  await flushDebounce(context);

  assert.ok(context.calls.length >= 1);
  for (const call of context.calls) {
    assert.equal(call.url, API_BASE + '/api/complete/inline');
  }
});

test('the suggestion is capped for display', async () => {
  const context = makeContext({ text: 'y'.repeat(500), rule: 'long' });
  await runModule(context, `
    els.completeInput.value = 'x+';
    els.completeInput.selectionStart = 2;
    els.completeInput.selectionEnd = 2;
    ${scheduleAndFlush}
  `);
  await flushDebounce(context);

  assert.equal(context.spans['.ghost-text'].textContent.length, 200);
});
