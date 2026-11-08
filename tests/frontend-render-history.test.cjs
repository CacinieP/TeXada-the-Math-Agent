'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const root = path.resolve(__dirname, '..');
const source = fs.readFileSync(path.join(root, 'tauri-shell/src/main.js'), 'utf8');
const vendor = fs.readFileSync(path.join(root, 'tauri-shell/src/vendor/katex/katex.min.js'), 'utf8');
const macros = source.slice(source.indexOf('  const KATEX_MACROS ='), source.indexOf('  const MATRIX_TYPES ='));
const renderer = source.slice(source.indexOf('  function renderKatexPreview('), source.indexOf('  function highlightLatex('));
const view = source.slice(source.indexOf('  function viewHistoryResult('), source.indexOf('  function renderHistory('));
const delimiters = source.slice(source.indexOf('  function markdownFormula('), source.indexOf('  async function insertAtCursor('));

class Element {
  constructor() { this.dataset = {}; this.hidden = false; this.disabled = false; this._html = ''; this._text = ''; this.focusCount = 0; this.isConnected = true; }
  set innerHTML(value) { this._html = value; this._text = ''; }
  get innerHTML() { return this._html; }
  set textContent(value) { this._text = String(value); this._html = ''; }
  get textContent() { return this._text; }
  querySelector(selector) {
    if (selector === '.katex-error') return this._html.includes('class="katex-error"') ? {} : null;
    if (selector === '.katex') return this._html.includes('class="katex"') ? {} : null;
    return this.nodes?.[selector] || null;
  }
  focus() { this.focusCount += 1; }
  scrollIntoView() { this.scrolled = true; }
}

function fixture() {
  const panel = new Element();
  panel.nodes = Object.fromEntries([
    'type', 'valid', 'time', 'input', 'source', 'math', 'error', 'close', 'reuse', 'copy-latex', 'copy-markdown',
  ].map(key => [`[data-history-preview-${key}]`, new Element()]));
  panel.hidden = true;
  const trigger = new Element();
  const copied = [], reused = [], tabs = [], renderOptions = [];
  const context = {
    console: {warn() {}, log() {}}, window: {}, document: {activeElement: trigger},
    els: {historyPreview: panel}, t: key => key, historyTypeLabel: type => `history.type.${type}`,
    formatHistoryTime: value => String(value || ''), copyToClipboard: async text => copied.push(text),
    reuseHistoryInput: item => reused.push(item), switchTab: tab => tabs.push(tab),
    renderMode: 'latex', lastResult: {latex: 'live draft'},
    restoreMatrixHistory() { throw new Error('View must not restore the form'); },
    showMatrixResult() { throw new Error('View must stay in history'); },
    setIntent() { throw new Error('View must not change editor state'); },
  };
  vm.createContext(context);
  vm.runInContext(vendor, context);
  context.window.katex = {
    render(latex, target, options) {
      renderOptions.push(options);
      target.innerHTML = context.katex.renderToString(latex, options);
    },
  };
  vm.runInContext(macros + renderer + delimiters + view, context);
  return {context, panel, trigger, copied, reused, tabs, renderOptions};
}

for (const [name, expression] of Object.entries({
  pmatrix: String.raw`\begin{pmatrix}a_1&b_1&0\\c_1&a_2&b_2\\0&c_2&a_3\end{pmatrix}`,
  bmatrix: String.raw`\begin{bmatrix}1&0\\0&1\end{bmatrix}`,
  vmatrix: String.raw`\begin{vmatrix}0&0\\0&0\end{vmatrix}`,
  matrix: String.raw`\begin{matrix}a_{0,0}&a_{0,1}\\a_{1,0}&a_{1,1}\end{matrix}`,
  symbolic: String.raw`\begin{pmatrix}a_1&\cdots&0\\\vdots&\ddots&\vdots\\0&\cdots&a_n\end{pmatrix}_{n\times n}`,
  aligned: String.raw`\begin{aligned}x&=1\\y&=2\end{aligned}`,
  cases: String.raw`f(x)=\begin{cases}x&x>0\\0&x\leq0\end{cases}`,
  placeholder: String.raw`\frac{\placeholder}{2}`,
})) {
  test(`production render helper renders ${name} without backend HTML`, () => {
    const f = fixture(), target = new Element();
    f.context.renderKatexPreview(target, expression);
    assert.match(target.innerHTML, /class="katex"/);
    assert.doesNotMatch(target.innerHTML, /class="katex-error"/);
    assert.equal(target.textContent, '');
  });
}

test('each render gets mutable isolated macros without changing the frozen template', () => {
  const f = fixture();
  f.context.renderKatexPreview(new Element(), String.raw`\gdef\localonly{x}\localonly`);
  const second = new Element();
  f.context.renderKatexPreview(second, String.raw`\localonly`);
  assert.notEqual(f.renderOptions[0].macros, f.renderOptions[1].macros);
  assert.equal(Object.isFrozen(f.renderOptions[0].macros), false);
  assert.equal(vm.runInContext('Object.isFrozen(KATEX_MACROS)', f.context), true);
  assert.equal(vm.runInContext('Object.hasOwn(KATEX_MACROS, "\\\\localonly")', f.context), false);
  assert.equal(second.dataset.renderState, 'source');
});

test('renderer exposes source-only failure and preserves safe text and existing HTML fallback', () => {
  const f = fixture();
  const bad = new Element();
  f.context.renderKatexPreview(bad, String.raw`\frac{x}{`);
  assert.equal(bad.dataset.renderState, 'source');
  assert.equal(bad.textContent, String.raw`\frac{x}{`);
  f.context.window.katex = null;
  const fallback = new Element();
  f.context.renderKatexPreview(fallback, 'x', '<span class="katex">x</span>');
  assert.equal(fallback.dataset.renderState, 'fallback');
  const raw = new Element();
  f.context.renderKatexPreview(raw, '<img src=x onerror=alert(1)>');
  assert.equal(raw.innerHTML, '');
  assert.equal(raw.textContent, '<img src=x onerror=alert(1)>');
});

for (const type of ['matrix', 'nl', 'ocr', 'completion']) {
  test(`viewing ${type} history stays in history without changing the editor or render mode`, () => {
    const f = fixture();
    const item = Object.freeze({type, input: '矩阵预设 {"rows":2,"columns":2}',
      latex: String.raw`\begin{pmatrix}1&0\\0&1\end{pmatrix}`, valid: true, renderMode: 'latex'});
    const last = f.context.lastResult;
    f.context.viewHistoryResult(item);
    assert.equal(f.panel.hidden, false);
    assert.deepEqual(f.tabs, []);
    assert.deepEqual(f.reused, []);
    assert.equal(f.context.renderMode, 'latex');
    assert.equal(f.context.lastResult, last);
    assert.match(f.panel.nodes['[data-history-preview-math]'].innerHTML, /class="katex"/);
    assert.equal(f.panel.nodes['[data-history-preview-source]'].textContent, item.latex);
    assert.equal(f.panel.nodes['[data-history-preview-error]'].hidden, true);
    assert.equal(f.panel.nodes['[data-history-preview-reuse]'].hidden, type === 'ocr');
  });
}

test('copy and reuse are explicit, exact and independent of historical rendering', async () => {
  const f = fixture();
  const item = {type: 'matrix', input: '矩阵预设 {"rows":2}', latex: String.raw`\begin{pmatrix}1\end{pmatrix}`, valid: true};
  f.context.viewHistoryResult(item);
  await f.panel.nodes['[data-history-preview-copy-latex]'].onclick();
  await f.panel.nodes['[data-history-preview-copy-markdown]'].onclick();
  assert.deepEqual(f.copied, [item.latex, `$$${item.latex}$$`]);
  assert.equal(f.reused.length, 0);
  f.panel.nodes['[data-history-preview-reuse]'].onclick();
  assert.equal(f.reused.length, 1);
  assert.equal(f.reused[0].input, item.input);
  f.panel.nodes['[data-history-preview-close]'].onclick();
  assert.equal(f.panel.hidden, true);
  assert.equal(f.trigger.focusCount, 1);
});

test('legacy or unreadable matrix parameters do not prevent inspecting the saved formula', () => {
  const f = fixture();
  f.context.viewHistoryResult({type: 'nl', input: '矩阵预设 {broken', latex: '$$x_1$$', valid: true});
  assert.match(f.panel.nodes['[data-history-preview-math]'].innerHTML, /class="katex"/);
  assert.equal(f.panel.nodes['[data-history-preview-source]'].textContent, '$$x_1$$');
  assert.deepEqual(f.tabs, []);
});

test('bad saved TeX shows a visible warning, not an empty preview or a false fresh verdict', () => {
  const f = fixture();
  const item = {type: 'matrix', input: '<img src=x onerror=evil()>', latex: String.raw`\frac{x}{`, valid: false};
  f.context.viewHistoryResult(item);
  assert.equal(f.panel.nodes['[data-history-preview-error]'].hidden, false);
  assert.equal(f.panel.nodes['[data-history-preview-input]'].textContent, item.input);
  assert.equal(f.panel.nodes['[data-history-preview-input]'].innerHTML, '');
  assert.equal(f.panel.nodes['[data-history-preview-valid]'].textContent, 'result.invalid');
  assert.deepEqual(f.reused, []);
});
