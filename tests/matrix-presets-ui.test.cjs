'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

const source = fs.readFileSync(path.join(__dirname, '../tauri-shell/src/main.js'), 'utf8');
const typeCode = source.slice(source.indexOf('  const MATRIX_TYPES ='), source.indexOf('  const I18N ='));
const matrixCode = source.slice(source.indexOf('  // ── Parameterized matrix presets'), source.indexOf('  // ── Shorthand ──'));
const traceCode = source.slice(source.indexOf('  function agentTraceView('), source.indexOf('  function inlineAgentTrace('));

function fixture() {
  const values = {
    kind: 'tridiagonal', rows: '10', columns: '10', element: 'a', diagonal: 'a_i',
    upper: 'b_i', lower: 'c_i', bracket: 'pmatrix', display: 'expanded', index_start: '1',
  };
  const fields = Object.fromEntries(Object.entries(values).map(([name, value]) => [name, {value}]));
  fields.rows.focus = function () { this.focused = true; };
  fields.kind.focus = function () { this.focused = true; };
  fields.display.expandedOption = {disabled: false};
  fields.display.querySelector = () => fields.display.expandedOption;
  const groups = ['columns', 'element', 'diagonal', 'upper', 'lower'].map(name => ({
    dataset: {matrixParameter: name}, hidden: ['columns', 'element'].includes(name),
    querySelector: () => fields[name],
  }));
  const handlers = {};
  const els = {
    matrixForm: {
      details: {open: false},
      elements: {namedItem: name => fields[name]}, valid: true, attributes: {},
      reportValidity() { return this.valid; },
      querySelectorAll: selector => selector === '[data-matrix-parameter]' ? groups : [],
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
  vm.runInContext(typeCode + matrixCode, context);
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

const parameterFields = {
  general: ['columns', 'element'],
  tridiagonal: ['diagonal', 'upper', 'lower'],
  identity: [],
  zero: ['columns'],
  diagonal: ['diagonal'],
  upper_triangular: ['element'],
  lower_triangular: ['element'],
};

for (const [kind, visibleFields] of Object.entries(parameterFields)) {
  test(`${kind} sends only its relevant parameters and preserves hidden drafts`, async () => {
    const f = fixture();
    f.fields.kind.value = kind;
    f.fields.rows.value = '2'; f.fields.columns.value = '4';
    f.fields.element.value = '\\beta'; f.fields.diagonal.value = '2.5';
    for (const origin of [0, 1]) {
      f.fields.index_start.value = String(origin);
      f.context.updateMatrixFields();
      assert.deepEqual(f.groups.filter(group => !group.hidden).map(group => group.dataset.matrixParameter),
        ['columns', 'element', 'diagonal', 'upper', 'lower'].filter(name => visibleFields.includes(name)));
      for (const group of f.groups) {
        assert.equal(group.querySelector('input').disabled, group.hidden);
      }
      const expected = {
        kind, rows: 2, columns: visibleFields.includes('columns') ? 4 : 2,
        bracket: 'pmatrix', display: 'expanded', index_start: origin,
      };
      for (const name of visibleFields.filter(name => name !== 'columns')) {
        expected[name] = f.fields[name].value;
      }
      await f.context.submitMatrixForm({preventDefault() {}});
      assert.deepEqual(JSON.parse(JSON.stringify(f.sent.at(-1).options.body.spec)), expected);
    }
    f.fields.kind.value = 'general';
    f.context.updateMatrixFields();
    assert.equal(f.fields.columns.value, '4');
    assert.equal(f.fields.element.value, '\\beta');
    assert.equal(f.fields.diagonal.value, '2.5');
  });
}

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

test('all square kinds ignore a hidden symbolic column and zero matrices keep rectangular columns', () => {
  const f = fixture();
  f.fields.columns.value = 'n';
  for (const kind of ['identity', 'diagonal', 'upper_triangular', 'lower_triangular']) {
    f.fields.kind.value = kind;
    f.fields.rows.value = '3';
    f.context.updateMatrixFields();
    assert.equal(f.fields.display.expandedOption.disabled, false);
    assert.equal(f.context.matrixSpecFromForm().columns, 3);
    f.fields.rows.value = 'm';
    f.context.updateMatrixFields();
    assert.equal(f.fields.display.expandedOption.disabled, true);
    assert.equal(f.fields.display.value, 'compact');
    assert.equal(f.context.matrixSpecFromForm().columns, 'm');
  }
  f.fields.kind.value = 'zero';
  f.fields.rows.value = '2';
  f.context.updateMatrixFields();
  assert.equal(f.fields.display.expandedOption.disabled, true);
  assert.equal(f.context.matrixSpecFromForm().columns, 'n');
  assert.equal(f.fields.element.disabled, true);
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
  for (const spec of [{rows: false}, {rows: 21}, {kind: 'unknown'}, {kind: ['identity']}, {kind: null}, {kind: 0}, {rows: 'n', columns: 'm', kind: 'tridiagonal'}, {display: 'unrecognized'}, {extra: '<img>'}]) {
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

for (const kind of ['identity', 'zero', 'diagonal', 'upper_triangular', 'lower_triangular']) {
  test(`${kind} history restores and regenerates with its shape and parameters`, async () => {
    const f = fixture();
    loadHistoryActions(f.context);
    const spec = {
      kind, rows: 'm', columns: kind === 'zero' ? 'n' : 'm',
      bracket: 'bmatrix', display: 'compact', index_start: 0,
    };
    if (kind === 'diagonal') spec.diagonal = 'x_i';
    if (kind.endsWith('_triangular')) spec.element = 'y';
    f.context.reuseHistoryInput({type: 'matrix', input: '矩阵预设 ' + JSON.stringify(spec)});
    assert.equal(f.fields.kind.value, kind);
    assert.equal(f.fields.display.value, 'compact');
    await f.context.submitMatrixForm({preventDefault() {}});
    assert.deepEqual(JSON.parse(JSON.stringify(f.sent[0].options.body.spec)), spec);
    if (kind !== 'zero') {
      assert.equal(f.context.matrixHistorySpec({input: '矩阵预设 ' + JSON.stringify({...spec, columns: 'n'})}), null);
    }
  });
}

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

function searchFixture() {
  const f = fixture();
  const results = {
    hidden: true,
    buttons: [],
    querySelectorAll() { return this.buttons; },
    get innerHTML() { return this.html || ''; },
    set innerHTML(value) {
      this.html = value;
      this.buttons = [...value.matchAll(/data-matrix-kind="([^"]+)"/g)].map(match => ({
        dataset: {matrixKind: match[1]},
        addEventListener(name, handler) { this[name] = handler; },
      }));
    },
  };
  f.els.matrixSearchResults = results;
  f.els.shorthandSearch = {value: ''};
  f.els.shorthandGrid = {innerHTML: '', querySelectorAll() { return []; }};
  f.context.allShorthands = [{key: 'pyth', value: 'a^2+b^2=c^2'}];
  f.context.bindFormulaInsertHandlers = () => {};
  f.context.escapeHtml = text => String(text).replaceAll('&', '&amp;').replaceAll('<', '&lt;');
  vm.runInContext(source.slice(source.indexOf('  const I18N ='), source.indexOf('  const els =')), f.context);
  vm.runInContext(source.slice(source.indexOf('  function renderShorthands('), source.indexOf('  async function addShorthandFromForm(')), f.context);
  return {...f, results};
}

test('matrix search supports every type in Chinese, English and kind names', () => {
  const f = searchFixture();
  const queries = {
    general: '通用', tridiagonal: '三对角', identity: 'IDENTITY', zero: '零矩阵',
    diagonal: '对角矩阵', upper_triangular: 'upper triangular', lower_triangular: '下三角',
  };
  for (const [kind, query] of Object.entries(queries)) {
    f.els.shorthandSearch.value = ' ' + query + ' ';
    f.context.renderShorthands();
    assert.equal(f.results.hidden, false);
    assert.ok(f.results.buttons.some(button => button.dataset.matrixKind === kind));
    assert.match(f.results.innerHTML, /type="button"/);
    assert.equal(f.els.shorthandGrid.innerHTML, '');
  }
});

test('search selection opens the same form, preserves drafts and invalidates the old result', () => {
  const f = searchFixture();
  f.fields.rows.value = '7'; f.fields.columns.value = '9'; f.fields.diagonal.value = '5';
  f.els.matrixForm.details.open = false;
  const prior = {latex: 'previous', valid: true, committed: true};
  f.els.matrixResult._texadaResult = prior;
  f.els.shorthandSearch.value = 'identity';
  f.context.renderShorthands();
  f.results.buttons[0].click();
  assert.equal(f.fields.kind.value, 'identity');
  assert.equal(f.fields.kind.focused, true);
  assert.equal(f.els.matrixForm.details.open, true);
  assert.equal(f.fields.rows.value, '7'); assert.equal(f.fields.columns.value, '9');
  assert.equal(f.fields.diagonal.value, '5');
  assert.equal(prior._reviewBlocked, true);
  assert.equal(f.sent.length, 0);
});

test('matrix-only results, no matches and clearing search preserve static preset behavior', () => {
  const f = searchFixture();
  f.els.shorthandSearch.value = 'zero';
  f.context.renderShorthands();
  assert.equal(f.els.shorthandGrid.innerHTML, '');
  f.els.shorthandSearch.value = 'no matching entry';
  f.context.renderShorthands();
  assert.equal(f.results.hidden, true);
  assert.match(f.els.shorthandGrid.innerHTML, /shorthand.noMatch/);
  f.els.shorthandSearch.value = 'pyth';
  f.context.renderShorthands();
  assert.equal(f.results.hidden, true);
  assert.match(f.els.shorthandGrid.innerHTML, /a\^2\+b\^2=c\^2/);
  f.els.shorthandSearch.value = '';
  f.context.renderShorthands();
  assert.equal(f.results.hidden, true);
  assert.equal(f.results.innerHTML, '');
  assert.match(f.els.shorthandGrid.innerHTML, /pyth/);
});

test('selecting a type through search while generating rejects the older response', async () => {
  const f = searchFixture();
  let finish;
  f.context.apiJson = async () => new Promise(resolve => { finish = resolve; });
  const pending = f.context.submitMatrixForm({preventDefault() {}});
  f.els.shorthandSearch.value = 'diagonal matrix';
  f.context.renderShorthands();
  f.results.buttons.find(button => button.dataset.matrixKind === 'diagonal').click();
  finish({latex: 'old request', valid: true, committed: true});
  await pending;
  assert.equal(f.shown[0]._reviewBlocked, true);
  assert.equal(f.fields.kind.value, 'diagonal');
});
