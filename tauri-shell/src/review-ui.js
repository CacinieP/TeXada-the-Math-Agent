// Revision-bound human adoption. All source/evidence strings stay text nodes.
(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  if (root) root.TeXadaReview = api;
})(typeof window === 'undefined' ? null : window, function () {
  'use strict';

  const COPY = {
    zh: {
      title: '人工审阅', pending: '待审阅 · 尚未采用', accepted: '已明确采用', rejected: '已拒绝',
      source: '原始输入', image: '原图', noImage: '本次输入没有可用原图', imageFailed: '原图无法加载，请勿视为视觉核验',
      parent: '修改前 LaTeX', candidate: '候选 LaTeX', preview: '候选渲染', reasons: '需要审阅的原因',
      diff: '角色修改与原文位置', noDiff: '没有可定位的角色差异', positionMissing: '可靠原文位置不可用',
      checks: '独立检查结果', compile: '编译', cas: 'CAS 过渡证据', human: '人工决定', intent: '意图核验', render: '渲染',
      notChecked: '未检查', accept: '采用候选', reject: '拒绝候选', refresh: '刷新状态', busy: '正在提交…',
      conflict: '输入或版本已变化，或已有相反决定。刷新后重新核对。',
      expired: '审阅已过期。请重新生成候选；本次候选不能采用。', failed: '提交失败，可刷新状态后重试。',
      edited: '原始输入已编辑。请重新生成候选；旧审阅不能用于当前输入。',
      disclaimer: '人工采用仅记录你的决定；编译、CAS 与意图检查各自独立，不代表语义或视觉准确性。',
      binding: '绑定版本',
      nlReview: '请对照原始描述核对公式；编译通过不代表转写准确。',
    },
    en: {
      title: 'Human review', pending: 'Pending review · not adopted', accepted: 'Explicitly adopted', rejected: 'Rejected',
      source: 'Original input', image: 'Source image', noImage: 'No source image is available for this input',
      imageFailed: 'Source image failed to load; visual verification is unavailable', parent: 'Previous LaTeX',
      candidate: 'Candidate LaTeX', preview: 'Candidate render', reasons: 'Review reasons',
      diff: 'Role changes and source positions', noDiff: 'No locatable role differences', positionMissing: 'Reliable source position unavailable',
      checks: 'Independent checks', compile: 'Compile', cas: 'CAS transition evidence', human: 'Human decision', intent: 'Intent check', render: 'Render',
      notChecked: 'Not checked', accept: 'Adopt candidate', reject: 'Reject candidate', refresh: 'Refresh status', busy: 'Submitting…',
      conflict: 'Input or revision changed, or an opposite decision exists. Refresh and review again.',
      expired: 'Review expired. Generate a new candidate; this candidate cannot be adopted.', failed: 'Request failed. Refresh status before retrying.',
      edited: 'Original input was edited. Generate a new candidate; the old review cannot apply to the current input.',
      disclaimer: 'Adoption records your decision. Compile, CAS and intent checks are independent; none proves semantic or visual accuracy.',
      binding: 'Bound revision',
      nlReview: 'Compare the formula with the original description; compilation does not establish transcription accuracy.',
    },
  };

  function validId(id) {
    return typeof id === 'string' && /^[A-Za-z0-9_-]{16,128}$/.test(id);
  }

  function sourceImageUrl(review, apiBase) {
    if (!validId(review?.id)) return null;
    const path = `/api/reviews/${review.id}/source`;
    return review.source_image_url === path ? `${String(apiBase).replace(/\/$/, '')}${path}` : null;
  }

  function decisionPayload(review, decision) {
    if (!validId(review?.id) || !['accept', 'reject'].includes(decision)) throw new Error('Invalid review decision');
    for (const key of ['input_hash', 'candidate_hash']) {
      if (typeof review[key] !== 'string' || !review[key]) throw new Error('Missing review binding');
    }
    if (!Number.isInteger(review.current_revision) || review.current_revision < 1) throw new Error('Missing current revision');
    if (review.parent_revision !== null && (!Number.isInteger(review.parent_revision) || review.parent_revision < 1)) throw new Error('Missing parent revision');
    return {
      decision, input_hash: review.input_hash, parent_revision: review.parent_revision,
      candidate_hash: review.candidate_hash, current_revision: review.current_revision,
    };
  }

  function canAdopt(result) {
    if (!result || result.committed === false || result._reviewBlocked === true) return false;
    if (!result.review) return true;
    return result.review.status === 'accepted' && result.review.committed === true;
  }

  function httpStatus(error) {
    if (Number(error?.status)) return Number(error.status);
    const match = /\b(409|410)\b/.exec(String(error?.message || error));
    return match ? Number(match[1]) : null;
  }

  function sourcePosition(entry, review) {
    const p = entry?.position;
    const latex = typeof entry?.parent_latex === 'string' ? entry.parent_latex : review?.parent_latex;
    if (p?.status !== 'available' || p.source !== 'parent_latex' || p.offset_units !== 'utf16'
        || typeof latex !== 'string' || !Number.isInteger(p.start) || !Number.isInteger(p.end)
        || p.start < 0 || p.end <= p.start || p.end > latex.length) return null;
    // A UTF-16 boundary cannot split a surrogate pair.
    const splitsPair = index => index > 0 && index < latex.length
      && /[\uD800-\uDBFF]/.test(latex[index - 1]) && /[\uDC00-\uDFFF]/.test(latex[index]);
    if (splitsPair(p.start) || splitsPair(p.end)) return null;
    return { before: latex.slice(0, p.start), selected: latex.slice(p.start, p.end), after: latex.slice(p.end), start: p.start, end: p.end };
  }

  function bindInputInvalidation(input, getPanel) {
    let revision = 0;
    input.addEventListener('input', () => { revision += 1; getPanel()?.invalidate(); });
    return () => revision;
  }

  function createPanel({ document, host, review, apiBase, request, language = () => 'zh', renderLatex, onChange = () => {}, sourceEdited = false, initialBlocked = false }) {
    let current = review;
    let busy = false;
    let blocked = initialBlocked || sourceEdited;
    let expired = false;
    let inputChanged = sourceEdited;
    let message = '';
    let epoch = 0;
    let destroyed = false;
    const refs = {};
    const words = () => COPY[language() === 'en' ? 'en' : 'zh'];
    const text = (tag, value, className = '') => {
      const el = document.createElement(tag);
      el.textContent = value === null || value === undefined ? '' : String(value);
      if (className) el.className = className;
      return el;
    };
    const display = value => typeof value === 'string' ? value : JSON.stringify(value ?? null, null, 2);
    function section(parent, label, value) {
      const box = text('section', '', 'review-section');
      box.append(text('h4', label), text('pre', value, 'review-source'));
      parent.append(box);
      return box;
    }
    function draw() {
      if (destroyed) return;
      const w = words();
      host.replaceChildren();
      host.className = 'human-review';
      host.setAttribute('aria-label', w.title);
      host.append(text('h3', w.title), text('p', w[current.status] || w.pending, `review-status review-${current.status}`));
      host.append(text('p', w.disclaimer, 'review-disclaimer'));
      const binding = text('details', '', 'review-binding');
      binding.append(text('summary', w.binding), text('pre', display({ input_hash: current.input_hash, parent_revision: current.parent_revision, candidate_hash: current.candidate_hash, current_revision: current.current_revision, expires_at: current.expires_at })));
      host.append(binding);

      const grid = text('div', '', 'review-comparison');
      section(grid, w.source, current.source_text);
      const imageSection = text('section', '', 'review-section');
      imageSection.append(text('h4', w.image));
      const imageUrl = sourceImageUrl(current, apiBase);
      const imageMessage = text('p', imageUrl ? '' : w.noImage, 'review-image-message');
      if (imageUrl) {
        const image = document.createElement('img');
        image.className = 'review-source-image';
        image.alt = w.image;
        image.src = imageUrl;
        image.addEventListener('error', () => { image.hidden = true; imageMessage.textContent = words().imageFailed; });
        imageSection.append(image);
      }
      imageSection.append(imageMessage);
      grid.append(imageSection);
      section(grid, w.parent, current.parent_latex);
      section(grid, w.candidate, current.latex);
      const preview = text('section', '', 'review-section');
      const previewBody = text('div', current.latex, 'render-preview review-candidate-render');
      preview.append(text('h4', w.preview), previewBody);
      grid.append(preview);
      if (renderLatex) renderLatex(previewBody, current.latex);
      host.append(grid);

      const reasons = text('ul', '', 'review-reasons');
      for (const reason of current.reasons || []) reasons.append(text('li', reason === 'nl_semantics_requires_review' ? w.nlReview : reason));
      host.append(text('h4', w.reasons), reasons, text('h4', w.diff));
      const entries = Array.isArray(current.role_diff) ? current.role_diff : [];
      if (!entries.length) host.append(text('p', w.noDiff));
      for (const entry of entries) {
        const item = text('article', '', 'review-diff');
        item.append(text('p', `${entry.path || ''} · ${entry.role || ''} · ${entry.operation || ''}`));
        item.append(text('pre', display({ before: entry.before ?? null, after: entry.after ?? null }), 'review-source'));
        const position = sourcePosition(entry, current);
        if (position) {
          item.append(text('p', `UTF-16 [${position.start}, ${position.end}) · ${entry.parent_revision || current.parent_revision || ''}`));
          const source = text('pre', '', 'review-source');
          source.append(text('span', position.before), text('mark', position.selected), text('span', position.after));
          item.append(source);
        } else {
          item.append(text('p', w.positionMissing, 'review-position-missing'));
          if (typeof entry.parent_latex === 'string') item.append(text('pre', entry.parent_latex, 'review-source'));
        }
        host.append(item);
      }
      const checks = text('div', '', 'review-checks');
      const values = current.checks || {};
      for (const key of ['compile', 'render', 'intent', 'cas', 'human']) {
        section(checks, w[key], key === 'cas' && !values.cas?.length ? w.notChecked : display(values[key] || { status: 'not_checked' }));
      }
      host.append(text('h4', w.checks), checks);
      refs.message = text('p', message, 'review-decision-message');
      refs.message.setAttribute('role', 'status');
      refs.message.setAttribute('aria-live', 'polite');
      const actions = text('div', '', 'review-actions');
      for (const action of ['accept', 'reject', 'refresh']) {
        const button = text('button', w[action], `action-btn ${action === 'accept' ? 'primary' : ''}`);
        button.type = 'button';
        button.dataset.reviewAction = action;
        button.disabled = busy || expired || (action !== 'refresh' && (blocked || current.status !== 'pending'));
        button.addEventListener('click', () => action === 'refresh' ? refresh() : decide(action));
        refs[action] = button;
        actions.append(button);
      }
      host.append(refs.message, actions);
    }
    async function perform(action) {
      if (destroyed || busy || expired || (action !== 'refresh' && (blocked || current.status !== 'pending'))) return;
      const startEpoch = ++epoch;
      busy = true;
      message = words().busy;
      draw();
      try {
        const path = `/api/reviews/${encodeURIComponent(current.id)}`;
        const next = await request(action === 'refresh' ? path : `${path}/decision`, action === 'refresh' ? {} : { method: 'POST', body: decisionPayload(current, action) });
        if (destroyed || epoch !== startEpoch) return;
        // Even refresh must stay on the same candidate and original-input binding.
        if (next.id !== current.id || next.input_hash !== current.input_hash || next.parent_revision !== current.parent_revision
            || next.candidate_hash !== current.candidate_hash || next.current_revision !== current.current_revision) {
          blocked = true;
          message = words().conflict;
          onChange(current, { blocked: true, inputChanged });
          return;
        }
        current = next;
        blocked = inputChanged;
        message = inputChanged ? words().edited : '';
        onChange(current, { blocked, inputChanged });
      } catch (error) {
        if (destroyed || epoch !== startEpoch) return;
        const status = httpStatus(error);
        // An ambiguous network failure also requires a read before another write.
        blocked = true;
        expired = status === 410;
        message = status === 409 ? words().conflict : expired ? words().expired : words().failed;
        onChange(current, { blocked: true, inputChanged });
      } finally {
        if (!destroyed && epoch === startEpoch) { busy = false; draw(); }
      }
    }
    const decide = decision => perform(decision);
    const refresh = () => perform('refresh');
    message = sourceEdited ? words().edited : initialBlocked ? words().failed : '';
    draw();
    return {
      decide, refresh, redraw: draw, refs, get review() { return current; },
      invalidate() {
        if (destroyed) return;
        // Editing during an in-flight decision also invalidates its UI response.
        epoch++;
        busy = false;
        inputChanged = true;
        blocked = true;
        message = words().edited;
        onChange(current, { blocked: true, inputChanged });
        draw();
      },
      destroy() { destroyed = true; epoch++; host.replaceChildren(); },
    };
  }

  return { canAdopt, sourceImageUrl, decisionPayload, sourcePosition, httpStatus, bindInputInvalidation, createPanel };
});
