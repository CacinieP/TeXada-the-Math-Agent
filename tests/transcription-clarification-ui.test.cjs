'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

const source = fs.readFileSync(path.join(__dirname, '../tauri-shell/src/main.js'), 'utf8');
const resultCode = source.slice(source.indexOf('  function showResult('), source.indexOf('  function agentTraceView('));
const errorCode = source.slice(source.indexOf('  function showError('), source.indexOf('  // ── Clipboard ──'));
const traceCode = source.slice(source.indexOf('  function agentTraceView('), source.indexOf('  function inlineAgentTrace('));

test('incomplete source displays escaped clarification with an accessible alert', () => {
  const els = {nlResult: {style: {}, dataset: {}, innerHTML: '<button>copy</button>'}};
  const states = [];
  const context = {
    els, clearReview() {}, t: key => key,
    setIntent: (...args) => states.push(args),
    escapeHtml: value => String(value).replaceAll('&', '&amp;').replaceAll('<', '&lt;'),
  };
  vm.createContext(context);
  vm.runInContext(resultCode + errorCode, context);
  context.showResult({
    stop_reason: 'source_clarification_required', latex: '', committed: false,
    agent_trace: [{observations: [{tool: 'source_clarification', output: {
      clarification: '请补充 omega_ 的下标 <img src=x>',
    }}]}],
  });
  assert.match(els.nlResult.innerHTML, /请补充 omega_ 的下标/);
  assert.match(els.nlResult.innerHTML, /&lt;img/);
  assert.match(els.nlResult.innerHTML, /role="alert" aria-live="assertive"/);
  assert.doesNotMatch(els.nlResult.innerHTML, /<button>|<img/);
  assert.equal(els.nlResult.dataset.originalHtml, '<button>copy</button>');
  assert.deepEqual(states, [['⚠️', 'result.clarificationRequired']]);
});

test('trace displays the current revision source verdict separately from syntax', () => {
  const context = {
    t: (key, values = {}) => key + (values.verdict ? ' ' + values.verdict : ''),
    escapeHtml: text => String(text),
  };
  vm.createContext(context);
  vm.runInContext(traceCode, context);
  const checked = context.agentTraceView({revision: 2, agent_trace: [{step: 1,
    transcription_constraints: [{revision: 1, verdict: 'MATCH'}, {revision: 2, verdict: 'DIFFERENT'}],
  }]});
  assert.match(checked.rows, /result\.transcriptionConstraints matrix\.DIFFERENT/);
  assert.doesNotMatch(checked.rows, /matrix\.MATCH/);
  for (const evidence of [
    {transcription_constraints: [{revision: 1, verdict: 'MATCH'}]},
    {transcription_recognition: [{verdict: 'NOT_CHECKED'}]},
  ]) {
    const unchecked = context.agentTraceView({revision: 2, agent_trace: [{step: 1, ...evidence}]});
    assert.match(unchecked.rows, /result\.transcriptionConstraints matrix\.NOT_CHECKED/);
  }
});
