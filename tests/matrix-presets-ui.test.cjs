'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

const source = fs.readFileSync(path.join(__dirname, '../tauri-shell/src/main.js'), 'utf8');
const matrixCode = source.slice(source.indexOf('  // ── Parameterized matrix presets'), source.indexOf('  // ── Shorthand ──'));
const traceCode = source.slice(source.indexOf('  function agentTraceView('), source.indexOf('  function inlineAgentTrace('));

function fixture() {
  const values = {
    kind: 'tridiagonal', rows: '10', columns: '10', element: 'a', diagonal: 'a_i',
    upper: 'b_i', lower: 'c_i', bracket: 'pmatrix', display: 'expanded', index_start: '1',
  };
  const fields = Object.fromEntries(Object.entries(values).map(([name, value]) => [name, {value}]));
  fields.rows.focus = function () { this.focused = true; };
  fields.display.expandedOption = {disabled: false};
  fields.display.querySelector = () => fields.display.expandedOption;
  const groups = {
    '[data-matrix-general]': [{hidden: true, querySelector: () => fields.columns}, {hidden: true, querySelector: () => fields.element}],
    '[data-matrix-tridiagonal]': ['diagonal', 'upper', 'lower'].map(name => ({hidden: false, querySelector: () => fields[name]})),
  };
  const handlers = {};
  const els = {
    matrixForm: {
      details: {open: false},
      elements: {namedItem: name => fields[name]}, valid: true, attributes: {},
      reportValidity() { return this.valid; },
      querySelectorAll: selector => groups[selector],
      setAttribute(name, value) { this.attributes[name] = value; },
      addEventListener(name, handler) { handlers[name] = handler; },
      closest() { return this.details; },
    },
    matrixRowsLabel: {dataset: {}, textContent: ''},
    matrixStatus: {textContent: '', focus() { this.focused = true; }},
    matrixResult: {hidden: false}, generateMatrixBtn: {disabled: false},
  };
  const sent = [];
  const shown = [];
  const gate = [];
  const reviews = new Map();
  const tabs = [];
  const context = {
    els, matrixDraftRevision: 0, matrixProcessing: false, renderMode: 'katex', resultReviews: reviews,
    t: (key, values = {}) => key + (values.verdict ? ' ' + values.verdict : ''),
    isImeComposing: event => event.isComposing,
    apiJson: async (url, options) => { sent.push({url, options}); return {latex: 'x', valid: true, committed: true}; },
    clearReview: root => { delete root._texadaResult; },
    updateReviewGate: (root, result) => gate.push(result),
    switchTab: tab => tabs.push(tab), setTimeout: callback => callback(), setIntent() {},
    historyTypeLabel: type => type,
  };
  vm.createContext(context);
  vm.runInContext(matrixCode, context);
  context.showMatrixResult = result => { shown.push(result); els.matrixResult._texadaResult = result; els.matrixResult.hidden = false; };
  return {context, els, fields, groups, handlers, sent, shown, gate, reviews, tabs};
}

test('matrix form sends typed dimensions, selected direction expressions and origin', async () => {
  const f = fixture();
  f.fields.upper.value = 'c_i'; f.fields.lower.value = 'b_i'; f.fields.index_start.value = '0';
  await f.context.submitMatrixForm({preventDefault() {}});
  const request = JSON.parse(JSON.stringify(f.sent[0]));
  assert.equal(request.url, '/api/matrix');
  assert.equal(request.options.method, 'POST');
  assert.deepEqual(request.options.body, {
    spec: {kind: 'tridiagonal', rows: 10, columns: 10, diagonal: 'a_i', upper: 'c_i', lower: 'b_i', bracket: 'pmatrix', display: 'expanded', index_start: 0},
    render_mode: 'katex',
  });
  assert.equal(f.shown.length, 1);
  assert.equal(f.els.generateMatrixBtn.disabled, false);
  assert.equal(f.els.matrixForm.attributes['aria-busy'], 'false');
});

test('general matrices keep rectangular and symbolic dimensions with relevant controls enabled', () => {
  const f = fixture();
  f.fields.kind.value = 'general'; f.fields.rows.value = ' m '; f.fields.columns.value = ' n ';
  f.context.updateMatrixFields();
  const spec = f.context.matrixSpecFromForm();
  assert.equal(spec.rows, 'm'); assert.equal(spec.columns, 'n');
  assert.equal(spec.diagonal, undefined); assert.equal(spec.element, 'a');
  assert.equal(f.fields.columns.disabled, false); assert.equal(f.fields.element.disabled, false);
  assert.equal(f.fields.diagonal.disabled, true);
  assert.equal(f.els.matrixRowsLabel.dataset.i18n, 'matrix.rows');
  f.fields.kind.value = 'tridiagonal'; f.context.updateMatrixFields();
  assert.equal(f.fields.columns.disabled, true); assert.equal(f.fields.diagonal.disabled, false);
  assert.equal(f.context.matrixSpecFromForm().columns, 'm');
  assert.equal(f.context.matrixSpecFromForm().element, undefined);
});

test('typing a symbolic order selects compact display before blur or submission', async () => {
  const f = fixture();
  f.context.bindMatrixForm();
  f.fields.rows.value = 'n';
  f.handlers.input();
  assert.equal(f.fields.display.value, 'compact');
  assert.equal(f.fields.display.expandedOption.disabled, true);
  await f.context.submitMatrixForm({preventDefault() {}});
  assert.equal(f.sent[0].options.body.spec.display, 'compact');
  assert.equal(f.sent[0].options.body.spec.rows, 'n');
  assert.equal(f.sent[0].options.body.spec.columns, 'n');
  f.fields.rows.value = '10';
  f.handlers.input();
  assert.equal(f.fields.display.expandedOption.disabled, false);
  assert.equal(f.fields.display.value, 'compact');
});

test('symbolic columns affect general matrices while hidden column drafts leave square display selectable', () => {
  const f = fixture();
  f.context.bindMatrixForm();
  f.fields.kind.value = 'general'; f.fields.columns.value = 'm';
  f.handlers.change();
  assert.equal(f.fields.display.value, 'compact');
  assert.equal(f.fields.display.expandedOption.disabled, true);
  f.fields.kind.value = 'tridiagonal';
  f.handlers.change();
  assert.equal(f.fields.display.expandedOption.disabled, false);
  assert.equal(f.fields.display.value, 'compact');
  f.fields.display.value = 'expanded'; f.handlers.change();
  assert.equal(f.fields.display.value, 'expanded');
});

test('valid submission disables repeat posting and discards adoption when the draft changes in flight', async () => {
  const f = fixture();
  let finish;
  f.context.apiJson = async (...args) => { f.sent.push(args); return new Promise(resolve => { finish = resolve; }); };
  const pending = f.context.submitMatrixForm({preventDefault() {}});
  assert.equal(f.els.generateMatrixBtn.disabled, true);
  assert.equal(f.els.matrixResult.hidden, true);
  await f.context.submitMatrixForm({preventDefault() {}});
  assert.equal(f.sent.length, 1);
  f.context.invalidateMatrixResult();
  finish({latex: 'old', valid: true, committed: true});
  await pending;
  assert.equal(f.shown[0]._reviewInputChanged, true);
  assert.equal(f.shown[0]._reviewBlocked, true);
  assert.equal(f.els.matrixStatus.textContent, 'result.sourceEdited');
});

test('editing a completed draft blocks its copy and insert gate and invalidates review', () => {
  const f = fixture();
  const result = {latex: 'x', valid: true, committed: true};
  f.els.matrixResult._texadaResult = result;
  let invalidated = 0;
  f.reviews.set(f.els.matrixResult, {invalidate() { invalidated += 1; }});
  f.context.invalidateMatrixResult();
  assert.equal(result._reviewBlocked, true); assert.equal(result._reviewInputChanged, true);
  assert.equal(invalidated, 1); assert.equal(f.gate.length, 1);
});

test('invalid form and failed request preserve an unavailable result and focus the error', async () => {
  const f = fixture();
  f.els.matrixForm.valid = false;
  await f.context.submitMatrixForm({preventDefault() {}});
  assert.equal(f.sent.length, 0);
  f.els.matrixForm.valid = true;
  f.els.matrixResult._texadaResult = {latex: 'old'};
  f.context.apiJson = async () => { throw new Error('Unsupported matrix dimension'); };
  await f.context.submitMatrixForm({preventDefault() {}});
  assert.equal(f.els.matrixResult._texadaResult, undefined);
  assert.equal(f.els.matrixResult.hidden, true);
  assert.equal(f.els.matrixStatus.focused, true);
  assert.equal(f.els.matrixStatus.textContent, 'Unsupported matrix dimension');
  assert.equal(f.els.generateMatrixBtn.disabled, false);
});

test('IME Enter is kept out of matrix submission', () => {
  const f = fixture();
  f.context.bindMatrixForm();
  let prevented = 0;
  f.handlers.keydown({key: 'Enter', isComposing: true, preventDefault() { prevented += 1; }});
  f.handlers.keydown({key: 'Enter', isComposing: false, preventDefault() { prevented += 1; }});
  assert.equal(prevented, 1);
});

test('trace shows revision-bound checks and marks unsupported recognition as unchecked', () => {
  const context = {t: (key, values = {}) => key + (values.verdict ? ' ' + values.verdict : ''), escapeHtml: text => String(text)};
  vm.createContext(context); vm.runInContext(traceCode, context);
  const checked = context.agentTraceView({revision: 2, agent_trace: [{step: 1, matrix_constraints: [{revision: 2, verdict: 'MATCH'}]}]});
  assert.match(checked.rows, /matrix\.MATCH/);
  const stale = context.agentTraceView({revision: 3, agent_trace: [{step: 1, matrix_constraints: [{revision: 2, verdict: 'MATCH'}]}]});
  assert.match(stale.rows, /matrix\.NOT_CHECKED/);
  const unknown = context.agentTraceView({revision: 1, agent_trace: [{step: 1, matrix_recognition: {verdict: 'NOT_CHECKED'}}]});
  assert.match(unknown.rows, /matrix\.NOT_CHECKED/);
});

test('structured parameter errors identify the field and server validation message', async () => {
  const context = {
    isTauri: false, API_BASE: 'http://localhost',
    fetch: async () => ({ok: false, status: 422, json: async () => ({detail: [{loc: ['body', 'spec', 'rows'], msg: 'Use dimensions from 1 to 20'}]})}),
  };
  vm.createContext(context);
  vm.runInContext(source.slice(source.indexOf('  async function apiJson('), source.indexOf('  async function loadRuntimeConfig(')), context);
  await assert.rejects(context.apiJson('/api/matrix'), error => {
    assert.equal(error.status, 422);
    assert.match(error.message, /spec\.rows — Use dimensions from 1 to 20/);
    return true;
  });
});

function loadHistoryActions(context) {
  vm.runInContext(source.slice(source.indexOf('  function reuseHistoryInput('), source.indexOf('  function renderHistory(')), context);
}

test('new matrix history restores controls and regenerates through the matrix API', async () => {
  const f = fixture();
  loadHistoryActions(f.context);
  f.els.matrixResult._texadaResult = {latex: 'old', committed: true};
  const spec = {
    kind: 'tridiagonal', rows: 'n', columns: 'n', diagonal: '2', upper: '-1', lower: '-1',
    bracket: 'bmatrix', display: 'compact', index_start: 0,
  };
  f.context.reuseHistoryInput({type: 'matrix', input: '矩阵预设 ' + JSON.stringify(spec)});
  assert.deepEqual(f.tabs, ['shorthand']);
  assert.equal(f.fields.rows.value, 'n');
  assert.equal(f.fields.upper.value, '-1');
  assert.equal(f.fields.bracket.value, 'bmatrix');
  assert.equal(f.fields.index_start.value, '0');
  assert.equal(f.els.matrixResult._texadaResult._reviewBlocked, true);
  assert.equal(f.els.matrixForm.details.open, true);
  await f.context.submitMatrixForm({preventDefault() {}});
  assert.equal(f.sent[0].url, '/api/matrix');
  assert.deepEqual(JSON.parse(JSON.stringify(f.sent[0].options.body.spec)), spec);
});

test('legacy nl matrix histories and history viewing use the preset entry', () => {
  const f = fixture();
  loadHistoryActions(f.context);
  f.context.markdownFormula = latex => '$$' + latex + '$$';
  const item = {
    type: 'nl', input: '矩阵预设 ' + JSON.stringify({rows: 3, columns: 4}),
    latex: 'matrix', valid: true, renderMode: 'katex',
  };
  f.context.reuseHistoryInput(item);
  assert.equal(f.fields.kind.value, 'general');
  assert.equal(f.fields.columns.value, '4');
  f.context.viewHistoryResult(item);
  assert.equal(f.shown[0].latex, 'matrix');
  assert.equal(f.shown[0].agent_trace, undefined);
  assert.equal(f.shown[0].revision, undefined);
  assert.ok(f.tabs.every(tab => tab === 'shorthand'));
});

test('invalid or unknown history parameters cannot alter controls or enter NL', () => {
  for (const spec of [{rows: false}, {rows: 21}, {rows: 'n', columns: 'm', kind: 'tridiagonal'}, {display: 'unrecognized'}, {extra: '<img>'}]) {
    const f = fixture();
    loadHistoryActions(f.context);
    const before = f.fields.rows.value;
    f.context.reuseHistoryInput({type: 'matrix', input: '矩阵预设 ' + JSON.stringify(spec)});
    assert.equal(f.fields.rows.value, before);
    assert.equal(f.els.matrixStatus.textContent, 'history.invalidMatrix');
    assert.deepEqual(f.tabs, ['shorthand']);
    assert.equal(f.sent.length, 0);
  }
});

test('restoring matrix history during a request prevents adoption of the old response', async () => {
  const f = fixture();
  loadHistoryActions(f.context);
  let finish;
  f.context.apiJson = async () => new Promise(resolve => { finish = resolve; });
  const pending = f.context.submitMatrixForm({preventDefault() {}});
  f.context.reuseHistoryInput({type: 'matrix', input: '矩阵预设 ' + JSON.stringify({rows: 2, columns: 3})});
  finish({latex: 'old request', valid: true, committed: true});
  await pending;
  assert.equal(f.shown[0]._reviewBlocked, true);
  assert.equal(f.fields.rows.value, '2');
  assert.equal(f.fields.columns.value, '3');
});
