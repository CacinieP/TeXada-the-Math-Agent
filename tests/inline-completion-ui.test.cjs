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
const keyboardStart = source.indexOf("  document.addEventListener('keydown', e => {",
  source.indexOf('  // ── Keyboard ──'));
const keyboardEnd = source.indexOf('  function toggleRenderMode()', keyboardStart);
assert.ok(keyboardStart > 0 && keyboardEnd > keyboardStart, 'global keyboard handler not found');
const keyboardSource = source.slice(keyboardStart, keyboardEnd);
const tabStart = source.indexOf('  function switchTab(tab) {');
const tabEnd = source.indexOf("  els.tabBar.addEventListener('click'", tabStart);
assert.ok(tabStart > 0 && tabEnd > tabStart, 'tab switch function not found');
const tabSource = source.slice(tabStart, tabEnd);

const API_BASE = 'http://127.0.0.1:19321';
const SUGGESTION = { text: '\\placeholder{}', rule: 'binary_operand' };

function tick() {
  return new Promise(resolve => setTimeout(resolve, 0));
}

function makeContext(response, options = {}) {
  const listeners = {};
  const calls = [];
  const timers = [];
  const cancelledTimers = new Set();
  const documentListeners = {};
  const invocations = [];
  const pendingResponses = [];
  const document = {
    activeElement: null,
    execCommand: options.execCommand || (() => true),
    addEventListener(type, fn) {
      (documentListeners[type] = documentListeners[type] || []).push(fn);
    },
  };
  const input = {
    value: '',
    selectionStart: 0,
    selectionEnd: 0,
    scrollTop: 0,
    scrollLeft: 0,
    focusCalls: 0,
    selectionRanges: [],
    rangeTexts: [],
    classList: { contains: name => name === 'input-box' },
    focus() { this.focusCalls += 1; document.activeElement = this; },
    blur() {
      document.activeElement = null;
      for (const listener of listeners.blur || []) listener();
    },
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
  document.activeElement = input;
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
    currentTab: 'complete',
    isTauri: true,
    isImeComposing: event => !!event.isComposing || event.keyCode === 229,
    isTextEntryEvent: () => true,
    invoke: (...args) => invocations.push(args),
    $$: () => [],
    setupOcr: () => {},
    els: { completeInput: input, completeGhost: ghost },
    document,
    window: new EventTarget(),
    setTimeout: (fn) => { timers.push(fn); return timers.length; },
    clearTimeout: id => cancelledTimers.add(id),
    fetch: async (url, init) => {
      const payload = JSON.parse(init.body);
      calls.push({ url, payload });
      // The server echoes the binding it was given.
      const result = {
        ok: true,
        json: async () => ({
          text: response === null ? null : response.text,
          rule: response === null ? null : response.rule,
          insert_at: 'cursor',
          source_hash: payload.source_hash,
          edit_version: payload.edit_version,
        }),
      };
      if (options.deferResponse) {
        return new Promise(resolve => pendingResponses.push(() => resolve(result)));
      }
      return result;
    },
    calls, listeners, timers, input, ghost, spans, cancelledTimers,
    documentListeners, invocations, pendingResponses,
  };
  return context;
}

async function runModule(context, driver) {
  vm.createContext(context);
  vm.runInContext(moduleSource + '\n' + keyboardSource + '\n' + tabSource + '\n' + driver + '\nvoid 0;', context);
  // Let the fire-and-forget request promise settle.
  await tick();
  await tick();
  return context;
}

async function flushDebounce(context) {
  const active = context.timers.filter((_, index) => !context.cancelledTimers.has(index + 1));
  assert.equal(active.length, 1, 'expected one active debounced request');
  active[0]();
  await tick();
  await tick();
}

function keyEvent(key, extra = {}) {
  const event = new Event('keydown', { bubbles: true, cancelable: true });
  Object.assign(event, { key, ...extra });
  return event;
}

function bubbleKey(context, event) {
  // Node has no DOM parent tree. Use its native Event cancellation semantics
  // and route the same event through the actual input/document listeners.
  for (const listener of context.listeners.keydown || []) listener(event);
  if (!event.cancelBubble) {
    for (const listener of context.documentListeners.keydown || []) listener(event);
  }
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
    els.completeInput.selectionEnd = 2;
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

  context.listeners.keydown[0](keyEvent('Escape'));

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
  context.listeners.keyup[0]({ type: 'keyup', key: '+' });
  assert.equal(context.ghost.hidden, true);
});

test('ghost text never calls the agent endpoints', async () => {
  const context = makeContext(SUGGESTION);
  await runModule(context, `
    els.completeInput.value = '\\\\frac{a}{';
    els.completeInput.selectionStart = 9;
    els.completeInput.selectionEnd = 9;
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

test('a bubbling Escape dismisses only the ghost; the next Escape hides the window', async () => {
  const context = makeContext(SUGGESTION);
  await runModule(context, `
    els.completeInput.value = 'x+';
    els.completeInput.setSelectionRange(2, 2);
    ${scheduleAndFlush}
  `);
  await flushDebounce(context);
  const first = keyEvent('Escape');
  bubbleKey(context, first);
  assert.equal(first.defaultPrevented, true);
  assert.equal(context.ghost.hidden, true);
  assert.equal(context.input.value, 'x+');
  assert.equal(context.input.selectionStart, 2);
  assert.equal(context.input.selectionEnd, 2);
  assert.deepEqual(context.invocations, []);

  bubbleKey(context, keyEvent('Escape'));
  assert.deepEqual(context.invocations, [['hide_window']]);
});

test('the document handler respects Escape already consumed by another control', async () => {
  const context = makeContext(SUGGESTION);
  await runModule(context, 'bindInlineCompletion();');
  const event = keyEvent('Escape');
  event.preventDefault();
  bubbleKey(context, event);
  assert.deepEqual(context.invocations, []);
});

for (const key of ['Tab', 'Escape']) {
  for (const ime of [{ isComposing: true }, { keyCode: 229 }]) {
    test(`${key} belongs to the IME during ${JSON.stringify(ime)}`, async () => {
      const context = makeContext(SUGGESTION, { execCommand: () => false });
      await runModule(context, `
        els.completeInput.value = 'x+';
        els.completeInput.setSelectionRange(2, 2);
        ${scheduleAndFlush}
      `);
      await flushDebounce(context);
      const event = keyEvent(key, ime);
      bubbleKey(context, event);
      assert.equal(event.defaultPrevented, false);
      assert.equal(context.input.value, 'x+');
      assert.equal(context.ghost.hidden, false);
      assert.deepEqual(context.input.rangeTexts, []);
      assert.deepEqual(context.invocations, []);
    });
  }
}

const requestText = '\\frac{}{b}';
const requestCursor = 6;
const changedContexts = {
  'blur then refocus': context => { context.input.blur(); context.input.focus(); },
  'keyboard caret move then return': context => {
    context.input.setSelectionRange(0, 0);
    context.listeners.keyup[0]();
    context.input.setSelectionRange(requestCursor, requestCursor);
  },
  'mouse caret move': context => {
    context.input.setSelectionRange(0, 0);
    context.listeners.mouseup[0]();
  },
  'tab switch then return': context => {
    vm.runInContext("switchTab('ocr'); switchTab('complete');", context);
  },
  'source change without an input event': context => { context.input.value += '+z'; },
  'selection extends from the original caret': context => {
    context.input.setSelectionRange(requestCursor, requestCursor + 1);
  },
};

for (const [name, change] of Object.entries(changedContexts)) {
  test(`a pending response is discarded after ${name}`, async () => {
    const context = makeContext(SUGGESTION, { deferResponse: true, execCommand: () => false });
    await runModule(context, `
      els.completeInput.value = ${JSON.stringify(requestText)};
      els.completeInput.setSelectionRange(${requestCursor}, ${requestCursor});
      bindInlineCompletion();
      globalThis.pending = requestInlineSuggestion();
    `);
    assert.equal(context.calls.length, 1);
    change(context);
    const valueAfterChange = context.input.value;
    context.pendingResponses[0]();
    await context.pending;
    assert.equal(context.ghost.hidden, true);
    bubbleKey(context, keyEvent('Tab'));
    assert.equal(context.input.value, valueAfterChange);
    assert.deepEqual(context.input.rangeTexts, []);
  });
}

for (const [name, change] of Object.entries(changedContexts)) {
  test(`Tab cannot accept a displayed candidate after ${name}`, async () => {
    const context = makeContext(SUGGESTION, { execCommand: () => false });
    await runModule(context, `
      els.completeInput.value = ${JSON.stringify(requestText)};
      els.completeInput.setSelectionRange(${requestCursor}, ${requestCursor});
      ${scheduleAndFlush}
    `);
    await flushDebounce(context);
    assert.equal(context.ghost.hidden, false);
    change(context);
    const valueAfterChange = context.input.value;
    const event = keyEvent('Tab');
    bubbleKey(context, event);
    assert.equal(event.defaultPrevented, false, 'rejected acceptance leaves normal Tab navigation');
    assert.equal(context.ghost.hidden, true);
    assert.equal(context.input.value, valueAfterChange);
    assert.deepEqual(context.input.rangeTexts, []);
  });
}

test('a pending suggestion is invalidated when the field loses focus without a blur event', async () => {
  const context = makeContext(SUGGESTION, { deferResponse: true });
  await runModule(context, `
    els.completeInput.value = 'x+';
    els.completeInput.setSelectionRange(2, 2);
    bindInlineCompletion();
    globalThis.pending = requestInlineSuggestion();
  `);
  context.document.activeElement = null;
  context.pendingResponses[0]();
  await context.pending;
  assert.equal(context.ghost.hidden, true);
});

test('ordinary keyup preserves the debounce and a valid middle insertion preserves both sides', async () => {
  const context = makeContext(SUGGESTION, { execCommand: () => false });
  await runModule(context, `
    els.completeInput.value = ${JSON.stringify(requestText)};
    els.completeInput.setSelectionRange(${requestCursor}, ${requestCursor});
    ${scheduleAndFlush}
  `);
  context.listeners.keyup[0]();
  await flushDebounce(context);
  assert.equal(context.calls.length, 1);
  assert.equal(context.ghost.hidden, false);
  const event = keyEvent('Tab');
  bubbleKey(context, event);
  assert.equal(event.defaultPrevented, true);
  assert.equal(context.input.value,
    requestText.slice(0, requestCursor) + SUGGESTION.text + requestText.slice(requestCursor));
});

test('blur cancels a debounced request before it reaches the API', async () => {
  const context = makeContext(SUGGESTION);
  await runModule(context, `
    els.completeInput.value = 'x+';
    els.completeInput.setSelectionRange(2, 2);
    ${scheduleAndFlush}
  `);
  context.input.blur();
  for (const [index, timer] of context.timers.entries()) {
    if (!context.cancelledTimers.has(index + 1)) timer();
  }
  await tick();
  assert.equal(context.calls.length, 0);
  assert.equal(context.ghost.hidden, true);
});

test('an older response cannot replace or clear a newer valid suggestion', async () => {
  const context = makeContext(SUGGESTION, { deferResponse: true });
  await runModule(context, `
    els.completeInput.value = 'x+';
    els.completeInput.setSelectionRange(2, 2);
    bindInlineCompletion();
    globalThis.older = requestInlineSuggestion();
    globalThis.newer = requestInlineSuggestion();
  `);
  context.pendingResponses[1]();
  await context.newer;
  assert.equal(context.ghost.hidden, false);
  context.pendingResponses[0]();
  await context.older;
  assert.equal(context.ghost.hidden, false);
  assert.equal(context.spans['.ghost-text'].textContent, SUGGESTION.text);
});

test('paste then Left schedules the empty denominator instead of losing the request', async () => {
  const context = makeContext(SUGGESTION, { execCommand: () => false });
  await runModule(context, `
    els.completeInput.value = '\\\\frac{a}{}';
    els.completeInput.setSelectionRange(10, 10);
    bindInlineCompletion();
  `);
  context.listeners.input[0]();
  context.input.setSelectionRange(9, 9);
  context.listeners.keyup[0]({ type: 'keyup', key: 'ArrowLeft' });
  await flushDebounce(context);
  assert.equal(context.calls.length, 1);
  assert.equal(context.calls[0].payload.before_cursor, '\\frac{a}{');
  assert.equal(context.calls[0].payload.after_cursor, '}');
  assert.equal(context.ghost.hidden, false);
  bubbleKey(context, keyEvent('Tab'));
  assert.equal(context.input.value, '\\frac{a}{\\placeholder{}}');
});

for (const event of [{ type: 'keyup', key: 'ArrowLeft' }, { type: 'mouseup' }]) {
  test(`caret navigation starts a request without an existing binding: ${event.type}`, async () => {
    const context = makeContext(SUGGESTION);
    await runModule(context, `
      els.completeInput.value = '\\\\frac{a}{}';
      els.completeInput.setSelectionRange(9, 9);
      bindInlineCompletion();
    `);
    context.listeners[event.type][0](event);
    await flushDebounce(context);
    assert.equal(context.calls.length, 1);
    assert.equal(context.calls[0].payload.before_cursor, '\\frac{a}{');
    assert.equal(context.calls[0].payload.after_cursor, '}');
    assert.equal(context.ghost.hidden, false);
  });
}

test('a new caret gets its own valid candidate while the old pending response is rejected', async () => {
  const context = makeContext(SUGGESTION, { deferResponse: true, execCommand: () => false });
  await runModule(context, `
    els.completeInput.value = '\\\\frac{a}{}';
    els.completeInput.setSelectionRange(10, 10);
    bindInlineCompletion();
    globalThis.older = requestInlineSuggestion();
  `);
  context.input.setSelectionRange(9, 9);
  context.listeners.keyup[0]({ type: 'keyup', key: 'ArrowLeft' });
  await flushDebounce(context);
  assert.equal(context.calls.length, 2);
  context.pendingResponses[0]();
  await context.older;
  assert.equal(context.ghost.hidden, true);
  context.pendingResponses[1]();
  await tick();
  await tick();
  assert.equal(context.ghost.hidden, false);
  bubbleKey(context, keyEvent('Tab'));
  assert.equal(context.input.value, '\\frac{a}{\\placeholder{}}');
});

test('an existing selection does not request a candidate that could replace source text', async () => {
  const context = makeContext(SUGGESTION);
  await runModule(context, `
    els.completeInput.value = '\\\\frac{a}{}';
    els.completeInput.setSelectionRange(9, 10);
    bindInlineCompletion();
    requestInlineSuggestion();
  `);
  assert.equal(context.calls.length, 0);
  assert.equal(context.ghost.hidden, true);
  assert.equal(context.input.value, '\\frac{a}{}');
});

test('Escape cancels an unseen pending suggestion while preserving the window shortcut', async () => {
  const context = makeContext(SUGGESTION, { deferResponse: true });
  await runModule(context, `
    els.completeInput.value = 'x+';
    els.completeInput.setSelectionRange(2, 2);
    bindInlineCompletion();
    globalThis.pending = requestInlineSuggestion();
  `);
  const event = keyEvent('Escape');
  bubbleKey(context, event);
  assert.deepEqual(context.invocations, [['hide_window']]);
  context.pendingResponses[0]();
  await context.pending;
  assert.equal(context.ghost.hidden, true);
  assert.equal(context.input.value, 'x+');
});

test('window blur invalidates a pending suggestion even when the textarea retains focus', async () => {
  const context = makeContext(SUGGESTION, { deferResponse: true });
  await runModule(context, `
    els.completeInput.value = 'x+';
    els.completeInput.setSelectionRange(2, 2);
    bindInlineCompletion();
    globalThis.pending = requestInlineSuggestion();
  `);
  context.window.dispatchEvent(new Event('blur'));
  assert.equal(context.document.activeElement, context.input);
  context.window.dispatchEvent(new Event('focus'));
  context.pendingResponses[0]();
  await context.pending;
  assert.equal(context.ghost.hidden, true);
  assert.equal(context.input.value, 'x+');
});
