'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { createPanel, decisionPayload, canAdopt, sourceImageUrl, sourcePosition, bindInputInvalidation } = require('../tauri-shell/src/review-ui.js');

class Element {
  constructor(tag) { this.tagName = tag; this.children = []; this.attributes = {}; this.dataset = {}; this.listeners = {}; this._text = ''; }
  set textContent(value) { this._text = String(value); this.children = []; }
  get textContent() { return this._text + this.children.map(child => child.textContent).join(''); }
  set innerHTML(_) { throw new Error('Untrusted HTML sink used'); }
  append(...children) { this.children.push(...children); }
  replaceChildren(...children) { this._text = ''; this.children = children; }
  setAttribute(name, value) { this.attributes[name] = value; }
  addEventListener(event, callback) { this.listeners[event] = callback; }
}
const document = { createElement: tag => new Element(tag) };
const id = '0123456789abcdef0123456789abcdef';
function dto(extra = {}) {
  return {
    id, status: 'pending', input_hash: 'original-hash', parent_revision: 1, candidate_hash: 'candidate-hash',
    current_revision: 2, committed: false, expires_at: '2099-01-01T00:00:00Z', latex: '\\frac{x}{2}',
    parent_latex: '\\frac{x}{3}', source_text: '<img src=x onerror=evil()>', source_image_url: null,
    reasons: ['<script>evil()</script>'], role_diff: [],
    checks: { compile: { status: 'valid' }, cas: [{ verdict: 'equivalent', basis: '<img>' }], human: { status: 'pending' }, intent: { status: 'not_checked' } },
    ...extra,
  };
}
function makePanel(review = dto(), options = {}) {
  const host = new Element('section');
  const panel = createPanel({ document, host, review, apiBase: 'http://127.0.0.1:18732/prefix/', request: async () => review, ...options });
  return { host, panel };
}
function descendants(node, tag) {
  return node.children.flatMap(child => [...(child.tagName === tag ? [child] : []), ...descendants(child, tag)]);
}

test('original input, reasons and check evidence are text nodes, with explicit missing image', () => {
  const { host, panel } = makePanel();
  assert.ok(host.textContent.includes('<img src=x onerror=evil()>'));
  assert.ok(host.textContent.includes('<script>evil()</script>'));
  assert.ok(host.textContent.includes('本次输入没有可用原图'));
  assert.equal(descendants(host, 'img').length, 0);
  assert.equal(panel.refs.accept.disabled, false);
  assert.equal(canAdopt({ committed: false, review: panel.review }), false);
});

test('only the exact controlled source route uses the configured API prefix', () => {
  assert.equal(sourceImageUrl(dto({ source_image_url: `/api/reviews/${id}/source` }), 'http://127.0.0.1:18732/prefix/'), `http://127.0.0.1:18732/prefix/api/reviews/${id}/source`);
  for (const source_image_url of ['https://evil.test/x', 'data:image/png;base64,a', '/api/reviews/other/source', `/api/reviews/${id}/source?url=https://evil.test`]) {
    assert.equal(sourceImageUrl(dto({ source_image_url }), 'http://localhost'), null);
  }
  const { host } = makePanel(dto({ source_image_url: `/api/reviews/${id}/source` }));
  const image = descendants(host, 'img')[0];
  image.listeners.error();
  assert.equal(image.hidden, true);
  assert.ok(host.textContent.includes('原图无法加载'));
});

test('decision sends the exact original hash and numeric revision binding', async () => {
  const review = dto();
  let actual;
  let changed;
  const { panel } = makePanel(review, { request: async (path, options) => { actual = { path, options }; return dto({ status: 'accepted', committed: true }); }, onChange: (value, state) => { changed = { value, state }; } });
  await panel.decide('accept');
  assert.equal(actual.path, `/api/reviews/${id}/decision`);
  assert.deepEqual(actual.options, { method: 'POST', body: { decision: 'accept', input_hash: 'original-hash', parent_revision: 1, candidate_hash: 'candidate-hash', current_revision: 2 } });
  assert.equal(panel.refs.accept.disabled, true);
  assert.equal(panel.refs.reject.disabled, true);
  assert.equal(changed.state.blocked, false);
  assert.equal(canAdopt({ committed: true, review: changed.value }), true);
  assert.throws(() => decisionPayload(dto({ current_revision: '2' }), 'accept'));
});

test('reject stays uncommitted and disables both decision buttons', async () => {
  const { panel } = makePanel(dto(), { request: async () => dto({ status: 'rejected', committed: false }) });
  await panel.decide('reject');
  assert.equal(panel.review.status, 'rejected');
  assert.equal(panel.refs.accept.disabled, true);
  assert.equal(panel.refs.reject.disabled, true);
  assert.equal(canAdopt({ review: panel.review }), false);
});

test('409 blocks decisions until a successful bound refresh, for browser and Tauri errors', async () => {
  for (const error of [Object.assign(new Error('changed'), { status: 409 }), new Error('API error 409 Conflict: changed')]) {
    let requests = 0;
    const { panel, host } = makePanel(dto(), { request: async () => { if (++requests === 1) throw error; return dto(); } });
    await panel.decide('accept');
    assert.equal(panel.refs.accept.disabled, true);
    assert.equal(panel.refs.refresh.disabled, false);
    assert.ok(host.textContent.includes('刷新后重新核对'));
    await panel.decide('accept');
    assert.equal(requests, 1);
    await panel.refresh();
    assert.equal(requests, 2);
    assert.equal(panel.refs.accept.disabled, false);
  }
});

test('410 expiration permanently disables this review and adoption', async () => {
  let blocked;
  const { panel, host } = makePanel(dto(), { request: async () => { throw Object.assign(new Error('expired'), { status: 410 }); }, onChange: (_, state) => { blocked = state.blocked; } });
  await panel.decide('accept');
  assert.equal(blocked, true);
  assert.equal(panel.refs.accept.disabled, true);
  assert.equal(panel.refs.refresh.disabled, true);
  assert.ok(host.textContent.includes('请重新生成候选'));
  assert.equal(canAdopt({ committed: true, review: dto({ status: 'accepted', committed: true }), _reviewBlocked: blocked }), false);
});

test('ambiguous network failures require reading status before another decision', async () => {
  const { panel } = makePanel(dto(), { request: async () => { throw new Error('connection closed'); } });
  await panel.decide('reject');
  assert.equal(panel.refs.accept.disabled, true);
  assert.equal(panel.refs.reject.disabled, true);
  assert.equal(panel.refs.refresh.disabled, false);
});

test('a response for another hash/revision cannot unlock adoption', async () => {
  for (const extra of [{ input_hash: 'other' }, { parent_revision: 9 }, { candidate_hash: 'other' }, { current_revision: 3 }, { id: 'fedcba9876543210fedcba9876543210' }]) {
    const { panel } = makePanel(dto(), { request: async () => dto({ status: 'accepted', committed: true, ...extra }) });
    await panel.decide('accept');
    assert.equal(panel.review.status, 'pending');
    assert.equal(panel.refs.accept.disabled, true);
  }
});

test('concurrent decisions are serialized, destroyed panels ignore late responses', async () => {
  let complete;
  let changes = 0;
  let requests = 0;
  const { panel } = makePanel(dto(), { request: () => { requests++; return new Promise(resolve => { complete = resolve; }); }, onChange: () => { changes++; } });
  const decision = panel.decide('accept');
  assert.equal(panel.refs.accept.disabled, true);
  await panel.decide('reject');
  assert.equal(requests, 1);
  panel.destroy();
  complete(dto({ status: 'accepted', committed: true }));
  await decision;
  assert.equal(changes, 0);
});

test('role locations use their own parent UTF-16 text and never approximate missing offsets', () => {
  const entry = { parent_latex: '😀x+1', parent_revision: 1, path: '<svg>', role: 'numerator', operation: 'replace', before: '<img>', after: 'y', position: { status: 'available', source: 'parent_latex', offset_units: 'utf16', start: 2, end: 3 } };
  assert.deepEqual(sourcePosition(entry, dto()), { before: '😀', selected: 'x', after: '+1', start: 2, end: 3 });
  const { host } = makePanel(dto({ role_diff: [entry] }));
  assert.equal(descendants(host, 'mark')[0].textContent, 'x');
  assert.ok(host.textContent.includes('<svg>'));
  assert.ok(host.textContent.includes('😀x+1'));
  for (const position of [{ status: 'unavailable' }, { ...entry.position, start: 1 }, { ...entry.position, end: 99 }, { ...entry.position, offset_units: 'bytes' }]) {
    assert.equal(sourcePosition({ ...entry, position }, dto()), null);
  }
});

test('labels can be redrawn in English without altering bound state', () => {
  let language = 'zh';
  const { panel, host } = makePanel(dto(), { language: () => language });
  language = 'en';
  panel.redraw();
  assert.ok(host.textContent.includes('Human review'));
  assert.ok(host.textContent.includes('No source image'));
  assert.equal(panel.review.current_revision, 2);
});

test('editing the input prevents old-binding POSTs, and diagnostic refresh cannot unlock it', async () => {
  const input = new Element('textarea');
  const writes = [];
  let blocked;
  const { panel, host } = makePanel(dto(), {
    request: async (path, options) => { if (options.method === 'POST') writes.push(path); return dto(); },
    onChange: (_, state) => { blocked = state.blocked; },
  });
  bindInputInvalidation(input, () => panel);
  input.listeners.input();
  assert.equal(blocked, true);
  assert.equal(panel.refs.accept.disabled, true);
  assert.equal(panel.refs.reject.disabled, true);
  assert.ok(host.textContent.includes('原始输入已编辑'));
  await panel.decide('accept');
  await panel.decide('reject');
  await panel.refresh();
  await panel.decide('accept');
  assert.deepEqual(writes, []);
  assert.equal(panel.refs.accept.disabled, true);
});

test('editing during a decision ignores its late accepted response', async () => {
  let complete;
  const changes = [];
  const { panel } = makePanel(dto(), {
    request: () => new Promise(resolve => { complete = resolve; }),
    onChange: (review, state) => { changes.push([review.status, state.blocked]); },
  });
  const request = panel.decide('accept');
  panel.invalidate();
  complete(dto({ status: 'accepted', committed: true }));
  await request;
  assert.deepEqual(changes, [['pending', true]]);
  assert.equal(panel.refs.accept.disabled, true);
  assert.equal(panel.review.status, 'pending');
});

test('recreating a panel preserves a source-edit lock instead of reauthorizing old input', async () => {
  let requests = 0;
  const { panel, host } = makePanel(dto(), {
    sourceEdited: true, initialBlocked: true,
    request: async () => { requests++; return dto(); },
  });
  assert.ok(host.textContent.includes('原始输入已编辑'));
  await panel.decide('accept');
  await panel.refresh();
  await panel.decide('accept');
  assert.equal(requests, 1);
  assert.equal(panel.refs.accept.disabled, true);
});

test('source revision detects edits before a review panel exists, including edit and revert', () => {
  const input = new Element('textarea');
  let panel = null;
  const revision = bindInputInvalidation(input, () => panel);
  const atRequest = revision();
  input.listeners.input();
  input.listeners.input();
  assert.notEqual(revision(), atRequest);
  const mounted = makePanel(dto(), { sourceEdited: revision() !== atRequest });
  panel = mounted.panel;
  assert.equal(panel.refs.accept.disabled, true);
  assert.equal(panel.refs.reject.disabled, true);
});

test('default NL review explains transcription fidelity in both languages', () => {
  for (const [lang, expected] of [['zh', '请对照原始描述核对公式'], ['en', 'Compare the formula']]) {
    const { host } = makePanel(dto({ reasons: ['nl_semantics_requires_review'] }), { language: () => lang });
    assert.ok(host.textContent.includes(expected));
    assert.ok(!host.textContent.includes('nl_semantics_requires_review'));
  }
});
