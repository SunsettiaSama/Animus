/**
 * render.js — Message rendering and ReAct step display.
 *
 * Public API:
 *   appendUserMsg(text)
 *   appendAssistantMsg(id?)     → returns { el, bubble, append, finalize, showPrompt }
 *   appendReactMsg(id?)         → returns { el, appendChunk, addStep, finalize, showPrompt, showActivity }
 *   appendStepBubble(index)     → returns StepBubble controller
 *   renderMarkdown(el, text)
 *   scrollBottom()
 *   clearMsgs()
 *   showEmptyState(mode)
 */

import {
  META_ORDER,
  META_PHASE,
  META_RENDER_TIME_MS,
  META_SESSION_STATE,
  META_WAIT_MS,
  fieldLabel,
  resolveRenderField,
  resolveRenderOrder,
  sortEventsByOrder,
} from './speak_render_protocol.js';

const _msgsEl = () => document.getElementById('msgs');
const _esc    = s => s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');

// ── Agent avatar (unified, configurable) ──────────────────────────────────────
let _agentAvatar = '⚡';
export function setAgentAvatar(v) { _agentAvatar = v || '⚡'; }
const _ts     = (iso) => {
  const d = iso ? new Date(iso) : new Date();
  if (Number.isNaN(d.getTime())) {
    const now = new Date();
    return `${now.getHours().toString().padStart(2,'0')}:${now.getMinutes().toString().padStart(2,'0')}`;
  }
  return `${d.getHours().toString().padStart(2,'0')}:${d.getMinutes().toString().padStart(2,'0')}`;
};

function _fmtThreadStamp(iso) {
  if (!iso) return '';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return String(iso);
  const y = d.getFullYear();
  const mo = String(d.getMonth() + 1).padStart(2, '0');
  const da = String(d.getDate()).padStart(2, '0');
  const h = String(d.getHours()).padStart(2, '0');
  const mi = String(d.getMinutes()).padStart(2, '0');
  return `${y}-${mo}-${da} ${h}:${mi}`;
}

// ── Markdown ──────────────────────────────────────────────────────────────────

export function renderMarkdown(el, text) {
  if (typeof marked === 'undefined' || !text.trim()) return;
  el.innerHTML  = marked.parse(text);
  el.classList.add('md-rendered');
  el.style.whiteSpace = 'normal';
  el.querySelectorAll('pre code').forEach(b => {
    if (typeof hljs !== 'undefined') hljs.highlightElement(b);
  });
}

// ── Scroll ────────────────────────────────────────────────────────────────────

export function scrollBottom() {
  const el = _msgsEl();
  if (el) el.scrollTop = el.scrollHeight;
}

// ── Clear / empty state ───────────────────────────────────────────────────────

export function clearMsgs() {
  const el = _msgsEl();
  if (el) el.innerHTML = '';
}

export function showEmptyState(mode = 'chat') {
  const icon = mode === 'react' ? '⚡' : '💬';
  const text = mode === 'react'
    ? 'Ask me anything — I will reason step-by-step.'
    : mode === 'speak'
    ? 'Say something — Soul will respond in real time.'
    : 'Start a conversation.';
  const el = _msgsEl();
  if (!el) return;
  el.innerHTML = `<div class="empty-state"><span class="empty-icon">${icon}</span><span>${text}</span></div>`;
}

// ── User message ──────────────────────────────────────────────────────────────

export function appendUserMsg(text, meta = {}) {
  const el = _msgsEl();
  if (!el) return;
  el.querySelector('.empty-state')?.remove();
  const div = document.createElement('div');
  div.className = 'message user';
  if (meta.title_key) div.dataset.titleKey = meta.title_key;
  div.innerHTML = `
    <div class="msg-avatar">U</div>
    <div class="msg-body">
      <div class="msg-bubble">${_esc(text)}</div>
      <span class="msg-time">${_ts(meta.created_at)}</span>
    </div>`;
  el.appendChild(div);
  scrollBottom();
  return div;
}

/** 旧历史段分隔：title + created_at，同名 title 靠时间戳区分。 */
export function appendThreadMarker(title, createdAt, meta = {}) {
  const el = _msgsEl();
  if (!el) return null;
  el.querySelector('.empty-state')?.remove();
  const div = document.createElement('div');
  div.className = 'thread-marker';
  const key = meta.title_key || `${title}@@${createdAt || ''}`;
  div.dataset.titleKey = key;
  const stamp = _fmtThreadStamp(createdAt);
  div.innerHTML = `
    <div class="thread-marker-line"></div>
    <div class="thread-marker-body">
      <span class="thread-marker-title">${_esc(title || '对话')}</span>
      ${stamp ? `<span class="thread-marker-time">${_esc(stamp)}</span>` : ''}
    </div>
    <div class="thread-marker-line"></div>`;
  el.appendChild(div);
  scrollBottom();
  return div;
}

export function appendProactiveBanner(bannerText, meta = {}) {
  const el = _msgsEl();
  if (!el) return null;
  el.querySelector('.empty-state')?.remove();
  const div = document.createElement('div');
  div.className = 'proactive-session-banner';
  div.dataset.proactiveIntentId = meta.proactiveIntentId ?? '';
  div.innerHTML = `<span class="proactive-banner-text">${_esc(bannerText)}</span>`;
  el.appendChild(div);
  scrollBottom();
  return div;
}

// ── Chat assistant message ────────────────────────────────────────────────────

/**
 * Creates an assistant bubble for streaming chat output.
 * Returns a controller object.
 */
export function appendAssistantMsg(idOrOpts) {
  const opts = typeof idOrOpts === 'object' && idOrOpts !== null
    ? idOrOpts
    : { id: idOrOpts };
  const el = _msgsEl();
  if (!el) return null;
  el.querySelector('.empty-state')?.remove();

  const div = document.createElement('div');
  div.className = 'message assistant';
  if (opts.id) div.dataset.msgId = opts.id;

  const bubble = document.createElement('div');
  bubble.className = 'msg-bubble streaming';

  const createdAt = String(opts.created_at ?? '').trim();
  const timeEl = document.createElement('span');
  timeEl.className = 'msg-time';
  timeEl.textContent = _ts(createdAt || undefined);

  const ttsBtn = document.createElement('button');
  ttsBtn.className = 'msg-tts-btn hidden';
  ttsBtn.title = 'Play';
  ttsBtn.innerHTML = `<span class="sound-wave"><b></b><b></b><b></b><b></b><b></b></span>`;

  const body = document.createElement('div');
  body.className = 'msg-body';
  body.append(bubble, timeEl, ttsBtn);
  div.append(document.createElement('div'), body);
  div.firstElementChild.className = 'msg-avatar';
  div.firstElementChild.textContent = _agentAvatar;
  el.appendChild(div);
  scrollBottom();

  let _text = '';
  let _rafPending = false;
  return {
    el,
    bubble,
    append(chunk) {
      _text += chunk;
      if (!_rafPending) {
        _rafPending = true;
        requestAnimationFrame(() => {
          bubble.textContent = _text;
          scrollBottom();
          _rafPending = false;
        });
      }
    },
    finalize(aborted = false) {
      bubble.classList.remove('streaming');
      if (createdAt) timeEl.textContent = _ts(createdAt);
      if (aborted) {
        bubble.innerHTML += '<br><span style="color:var(--text3);font-size:11px">⊘ aborted</span>';
      } else {
        renderMarkdown(bubble, _text);
        ttsBtn.classList.remove('hidden');
        ttsBtn.dataset.text = _text;
      }
      scrollBottom();
    },
    showPrompt(messages) { _renderFullPrompt(div, messages); },
    get text() { return _text; },
  };
}

// ── ReAct message ─────────────────────────────────────────────────────────────

/**
 * Creates a ReAct message container supporting step cards, activity strip,
 * and a streaming final-answer bubble.
 */
export function appendReactMsg(id) {
  const el = _msgsEl();
  if (!el) return null;
  el.querySelector('.empty-state')?.remove();

  const div = document.createElement('div');
  div.className = 'message assistant react-msg';
  if (id) div.dataset.msgId = id;

  const body = document.createElement('div');
  body.className = 'msg-body';
  body.style.width = '100%';

  const avatar = document.createElement('div');
  avatar.className = 'msg-avatar';
  avatar.textContent = '⚡';
  div.append(avatar, body);
  el.appendChild(div);

  // Activity strip (spinner + current label) — hidden until showActivity() is called.
  const activity = document.createElement('div');
  activity.className = 'react-activity hidden';
  activity.innerHTML = `<div class="ra-spinner"></div><span class="ra-text">Thinking…</span>`;
  body.appendChild(activity);

  // Steps container
  const stepsWrap = document.createElement('div');
  stepsWrap.className = 'react-steps';
  body.appendChild(stepsWrap);

  // Final answer bubble
  const answerBubble = document.createElement('div');
  answerBubble.className = 'msg-bubble hidden';
  body.appendChild(answerBubble);

  const ttsBtn = document.createElement('button');
  ttsBtn.className = 'msg-tts-btn hidden';
  ttsBtn.title = 'Play';
  ttsBtn.innerHTML = `<span class="sound-wave"><b></b><b></b><b></b><b></b><b></b></span>`;
  body.appendChild(ttsBtn);

  const timeEl = document.createElement('span');
  timeEl.className = 'msg-time hidden';
  body.appendChild(timeEl);

  // Per-step state
  const _steps = {};   // index → { card, rawEl, sections, streamed, _rafPending }
  let   _stepI = -1;
  let   _ansText = '';
  let   _ansRafPending = false;
  let   _subBlock = null;   // current active sub-agent block element

  function _ensureStep(index) {
    if (_steps[index]) return _steps[index];
    const card = document.createElement('div');
    card.className = 'step-card';
    const hdr = document.createElement('div');
    hdr.className = 'step-hdr';
    hdr.innerHTML = `<span class="chevron">▶</span> <span>Step ${index + 1}</span>
      <span class="step-streaming-label" id="step-sl-${index}">streaming…</span>`;
    hdr.addEventListener('click', () => {
      detail.classList.toggle('open');
      hdr.classList.toggle('open');
    });
    const detail = document.createElement('div');
    detail.className = 'step-detail';
    const rawEl = document.createElement('div');
    rawEl.className = 'step-raw';
    detail.appendChild(rawEl);
    card.append(hdr, detail);
    stepsWrap.appendChild(card);
    const s = { card, hdr, detail, rawEl, streamed: '' };
    _steps[index] = s;
    return s;
  }

  return {
    el,
    showActivity(text = 'Thinking…') {
      activity.querySelector('.ra-text').textContent = text;
      activity.classList.remove('hidden');
      scrollBottom();
    },
    hideActivity() {
      activity.classList.add('hidden');
    },
    appendChunk(index, chunk) {
      const s = _ensureStep(index);
      if (!s.streamed) activity.classList.add('hidden');
      s.streamed += chunk;
      // Open the detail automatically on first chunk so the streaming text is visible.
      if (!s.detail.classList.contains('open')) {
        s.detail.classList.add('open');
        s.hdr.classList.add('open');
      }
      if (!s._rafPending) {
        s._rafPending = true;
        requestAnimationFrame(() => {
          // During streaming, show only the <T> thought content to avoid exposing
          // raw JSON inside <A> and raw output inside <O> before they are structured.
          const thoughtMatch = s.streamed.match(/<T>([\s\S]*?)(?:<\/T>|$)/i);
          s.rawEl.textContent = thoughtMatch ? thoughtMatch[1] : s.streamed.replace(/<[TAO]>[\s\S]*?<\/[TAO]>/gi, '').trim();
          scrollBottom();
          s._rafPending = false;
        });
      }
    },
    addStep(stepObj) {
      const s = _ensureStep(stepObj.index);
      s.hdr.querySelector('.step-streaming-label')?.remove();

      // Add a brief thought summary (≤50 chars) to the step header.
      if (stepObj.thought) {
        const raw = stepObj.thought.trim();
        const summary = raw.length > 50 ? raw.slice(0, 50).replace(/\s\S*$/, '') + '…' : raw;
        const summaryEl = document.createElement('span');
        summaryEl.className = 'step-summary';
        summaryEl.textContent = summary;
        s.hdr.appendChild(summaryEl);
      }
      // Build structured view
      s.detail.innerHTML = '';
      const secs = document.createElement('div');
      secs.className = 'step-sections';

      const mkSec = (cls, label, content, { markdown = false, code = false } = {}) => {
        const sec = document.createElement('div');
        sec.className = `step-sec ${cls}`;
        const lbl = document.createElement('div');
        lbl.className = 'sec-lbl';
        lbl.textContent = label;
        const cont = document.createElement('div');
        cont.className = 'sec-content';
        if (code) {
          const pre = document.createElement('pre');
          const codeEl = document.createElement('code');
          codeEl.className = 'language-json';
          codeEl.textContent = content;
          if (typeof hljs !== 'undefined') hljs.highlightElement(codeEl);
          pre.appendChild(codeEl);
          cont.appendChild(pre);
        } else if (markdown) {
          renderMarkdown(cont, content);
        } else {
          cont.textContent = content;
        }
        sec.append(lbl, cont);
        return sec;
      };
      if (stepObj.thought) secs.appendChild(mkSec('thought', 'Thought', stepObj.thought, { markdown: true }));

      // Render action(s): multi-call steps (calls array) get one card per call;
      // legacy single-call steps fall back to the original Action/Input display.
      if (Array.isArray(stepObj.calls) && stepObj.calls.length > 1) {
        const callsWrap = document.createElement('div');
        callsWrap.className = 'step-sec action-sec';
        const callsLbl = document.createElement('div');
        callsLbl.className = 'sec-lbl';
        callsLbl.textContent = `Actions (${stepObj.calls.length} parallel)`;
        callsWrap.appendChild(callsLbl);
        stepObj.calls.forEach((call, idx) => {
          const callEl = document.createElement('div');
          callEl.className = 'parallel-call';
          const argsStr = JSON.stringify(call.args ?? {}, null, 2);
          callEl.innerHTML = `<span class="call-idx">${idx + 1}.</span> <code>${_esc(call.action)}</code>`;
          const pre = document.createElement('pre');
          const codeEl = document.createElement('code');
          codeEl.className = 'language-json';
          codeEl.textContent = argsStr;
          if (typeof hljs !== 'undefined') hljs.highlightElement(codeEl);
          pre.appendChild(codeEl);
          callEl.appendChild(pre);
          callsWrap.appendChild(callEl);
        });
        secs.appendChild(callsWrap);
      } else {
        if (stepObj.action) secs.appendChild(mkSec('action-sec', 'Action', stepObj.action));
        if (stepObj.action_input) {
          const ai = typeof stepObj.action_input === 'string'
            ? stepObj.action_input
            : JSON.stringify(stepObj.action_input, null, 2);
          secs.appendChild(mkSec('action-sec', 'Input', ai, { code: true }));
        }
      }

      if (stepObj.observation) secs.appendChild(mkSec('observation', 'Observation', stepObj.observation, { markdown: true }));

      s.detail.appendChild(secs);

      // Raw model output — collapsed by default, shows full <T><A><O> XML.
      if (s.streamed) {
        const rawWrap = document.createElement('div');
        rawWrap.className = 'step-raw-wrap';
        const rawToggle = document.createElement('div');
        rawToggle.className = 'step-raw-toggle';
        rawToggle.innerHTML = '<span class="raw-chevron">▶</span> 原始输出';
        const rawPre = document.createElement('pre');
        rawPre.className = 'step-raw-pre';
        rawPre.textContent = s.streamed;
        rawWrap.append(rawToggle, rawPre);
        rawToggle.addEventListener('click', () => {
          const open = rawPre.classList.toggle('open');
          rawToggle.classList.toggle('open', open);
        });
        s.detail.appendChild(rawWrap);
      }

      const doneEl = document.createElement('span');
      doneEl.className = 'step-done';
      doneEl.textContent = '✓';
      s.hdr.appendChild(doneEl);
      s.detail.classList.remove('open');
      s.hdr.classList.remove('open');

      scrollBottom();
    },
    openSubAgent(action, instruction) {
      const lastStep = _steps[_stepI];
      const container = lastStep ? lastStep.detail : stepsWrap;
      const block = document.createElement('div');
      block.className = 'sub-agent-block';
      const hdr = document.createElement('div');
      hdr.className = 'sub-agent-hdr';
      hdr.innerHTML = `<span class="sub-chevron">▶</span> <span class="sub-label">Sub-agent: ${_esc(action)}</span>`;
      const body = document.createElement('div');
      body.className = 'sub-agent-body';
      const instrEl = document.createElement('div');
      instrEl.className = 'sub-instr';
      instrEl.textContent = instruction.slice(0, 120) + (instruction.length > 120 ? '…' : '');
      body.appendChild(instrEl);
      hdr.addEventListener('click', () => {
        body.classList.toggle('open');
        hdr.classList.toggle('open');
      });
      block.append(hdr, body);
      container.appendChild(block);
      _subBlock = { block, body, hdr };
      scrollBottom();
    },
    addSubChunk(index, chunk) {
      if (!_subBlock) return;
      let streamEl = _subBlock.body.querySelector('.sub-stream');
      if (!streamEl) {
        streamEl = document.createElement('div');
        streamEl.className = 'sub-stream';
        _subBlock.body.appendChild(streamEl);
      }
      streamEl.textContent = (streamEl.textContent || '') + chunk;
      scrollBottom();
    },
    addSubStep(stepObj) {
      if (!_subBlock) return;
      const row = document.createElement('div');
      row.className = 'sub-step-row' + (stepObj.is_error ? ' sub-step-error' : '');

      const mkPart = (label, val, { markdown = false } = {}) => {
        if (!val) return null;
        const v = typeof val === 'string' ? val : JSON.stringify(val, null, 2);
        const wrap = document.createElement('div');
        wrap.className = 'sub-sec';
        const lbl = document.createElement('span');
        lbl.className = 'sub-sec-lbl';
        lbl.textContent = label;
        const valEl = document.createElement('span');
        valEl.className = 'sub-sec-val';
        if (markdown) {
          renderMarkdown(valEl, v);
        } else {
          valEl.textContent = v;
        }
        wrap.append(lbl, valEl);
        return wrap;
      };

      [
        mkPart('Thought', stepObj.thought, { markdown: true }),
        mkPart('Action', stepObj.action),
        mkPart('Input', stepObj.action_input),
        mkPart('Observation', stepObj.observation, { markdown: true }),
      ].forEach(el => el && row.appendChild(el));

      _subBlock.body.querySelector('.sub-stream')?.remove();
      _subBlock.body.appendChild(row);
      scrollBottom();
    },
    closeSubAgent(answerOrError, isError = false) {
      if (!_subBlock) return;
      const badge = document.createElement('span');
      badge.className = 'sub-done-badge' + (isError ? ' sub-done-error' : '');
      badge.textContent = isError ? '✗ error' : '✓ done';
      _subBlock.hdr.appendChild(badge);
      if (answerOrError) {
        const summary = document.createElement('div');
        summary.className = isError ? 'sub-error-banner' : 'sub-answer';
        summary.textContent = answerOrError.slice(0, 300) + (answerOrError.length > 300 ? '…' : '');
        _subBlock.body.appendChild(summary);
      }
      _subBlock = null;
      scrollBottom();
    },
    close() {
      activity.remove();
      answerBubble.remove();
      scrollBottom();
    },
    appendAnswer(chunk) {
      _ansText += chunk;
      answerBubble.classList.remove('hidden');
      answerBubble.classList.add('streaming');
      if (!_ansRafPending) {
        _ansRafPending = true;
        requestAnimationFrame(() => {
          answerBubble.textContent = _ansText;
          scrollBottom();
          _ansRafPending = false;
        });
      }
    },
    finalize(answer, aborted = false) {
      activity.remove();
      answerBubble.classList.remove('streaming', 'hidden');
      timeEl.classList.remove('hidden');
      timeEl.textContent = _ts();

      if (aborted) {
        answerBubble.innerHTML = '<span style="color:var(--text3);font-size:12px">⊘ aborted</span>';
      } else {
        _ansText = answer || _ansText;
        renderMarkdown(answerBubble, _ansText);
        ttsBtn.classList.remove('hidden');
        ttsBtn.dataset.text = _ansText;
      }
      scrollBottom();
    },
    showPrompt(messages) { _renderFullPrompt(div, messages); },
  };
}

// ── Step bubble (one per TAO step) ────────────────────────────────────────────

/**
 * Creates a standalone streaming bubble for a single ReAct step.
 * Returns a StepBubble controller used by TurnBubbleManager.
 *
 * Lifecycle:
 *   loading    → spinner + "Step N…"
 *   streaming  → shows <T> thought text in real-time
 *   finalized  → structured step-card view (thought / action / observation)
 */
export function appendStepBubble(index) {
  const el = _msgsEl();
  if (!el) return null;
  el.querySelector('.empty-state')?.remove();

  const div = document.createElement('div');
  div.className = 'message assistant step-bubble';

  const avatar = document.createElement('div');
  avatar.className = 'msg-avatar';
  avatar.textContent = '⚡';

  // Header: hidden until finalize, then shows "Step N · action"
  const hdr = document.createElement('div');
  hdr.className = 'step-bubble-hdr hidden';

  const numBadge = document.createElement('span');
  numBadge.className = 'step-num';
  numBadge.textContent = `Step ${index + 1}`;

  const actionTag = document.createElement('span');
  actionTag.className = 'step-action-tag';

  const doneIcon = document.createElement('span');
  doneIcon.className = 'step-done';
  doneIcon.textContent = '✓';

  hdr.append(numBadge, actionTag, doneIcon);

  // Streaming view: raw thought text while chunks arrive
  const streamEl = document.createElement('div');
  streamEl.className = 'step-bubble-stream';
  streamEl.innerHTML = `<div class="sb-spinner"></div><span class="sb-text">Step ${index + 1}…</span>`;

  // Detail area: structured content after finalize
  const detailEl = document.createElement('div');
  detailEl.className = 'step-bubble-detail hidden';

  const timeEl = document.createElement('span');
  timeEl.className = 'msg-time hidden';

  const body = document.createElement('div');
  body.className = 'msg-body step-bubble-body';
  body.append(hdr, streamEl, detailEl, timeEl);

  div.append(avatar, body);
  el.appendChild(div);
  scrollBottom();

  let _streamed = '';
  let _rafPending = false;
  let _subBlock = null;

  // ── Sub-agent helpers (reuse appendReactMsg logic) ──────────────────────────
  function _openSubAgent(action, instruction) {
    const block = document.createElement('div');
    block.className = 'sub-agent-block';
    const sbHdr = document.createElement('div');
    sbHdr.className = 'sub-agent-hdr';
    sbHdr.innerHTML = `<span class="sub-chevron">▶</span> <span class="sub-label">Sub-agent: ${_esc(action)}</span>`;
    const sbBody = document.createElement('div');
    sbBody.className = 'sub-agent-body';
    const instrEl = document.createElement('div');
    instrEl.className = 'sub-instr';
    instrEl.textContent = instruction.slice(0, 120) + (instruction.length > 120 ? '…' : '');
    sbBody.appendChild(instrEl);
    sbHdr.addEventListener('click', () => {
      sbBody.classList.toggle('open');
      sbHdr.classList.toggle('open');
    });
    block.append(sbHdr, sbBody);
    detailEl.appendChild(block);
    _subBlock = { block, body: sbBody, hdr: sbHdr };
    scrollBottom();
  }

  function _addSubChunk(_idx, chunk) {
    if (!_subBlock) return;
    let streamDiv = _subBlock.body.querySelector('.sub-stream');
    if (!streamDiv) {
      streamDiv = document.createElement('div');
      streamDiv.className = 'sub-stream';
      _subBlock.body.appendChild(streamDiv);
    }
    streamDiv.textContent = (streamDiv.textContent || '') + chunk;
    scrollBottom();
  }

  function _addSubStep(stepObj) {
    if (!_subBlock) return;
    const row = document.createElement('div');
    row.className = 'sub-step-row' + (stepObj.is_error ? ' sub-step-error' : '');
    const mkPart = (label, val, { markdown = false } = {}) => {
      if (!val) return null;
      const v = typeof val === 'string' ? val : JSON.stringify(val, null, 2);
      const wrap = document.createElement('div');
      wrap.className = 'sub-sec';
      const lbl = document.createElement('span');
      lbl.className = 'sub-sec-lbl';
      lbl.textContent = label;
      const valEl = document.createElement('span');
      valEl.className = 'sub-sec-val';
      if (markdown) renderMarkdown(valEl, v); else valEl.textContent = v;
      wrap.append(lbl, valEl);
      return wrap;
    };
    [
      mkPart('Thought',     stepObj.thought,       { markdown: true }),
      mkPart('Action',      stepObj.action),
      mkPart('Input',       stepObj.action_input),
      mkPart('Observation', stepObj.observation,   { markdown: true }),
    ].forEach(e => e && row.appendChild(e));
    _subBlock.body.querySelector('.sub-stream')?.remove();
    _subBlock.body.appendChild(row);
    scrollBottom();
  }

  function _closeSubAgent(answerOrError, isError = false) {
    if (!_subBlock) return;
    const badge = document.createElement('span');
    badge.className = 'sub-done-badge' + (isError ? ' sub-done-error' : '');
    badge.textContent = isError ? '✗ error' : '✓ done';
    _subBlock.hdr.appendChild(badge);
    if (answerOrError) {
      const summary = document.createElement('div');
      summary.className = isError ? 'sub-error-banner' : 'sub-answer';
      summary.textContent = answerOrError.slice(0, 300) + (answerOrError.length > 300 ? '…' : '');
      _subBlock.body.appendChild(summary);
    }
    _subBlock = null;
    scrollBottom();
  }

  // ── Controller ──────────────────────────────────────────────────────────────
  return {
    streamChunk(chunk) {
      // Hide spinner on first chunk; switch to raw text display.
      const spinner = streamEl.querySelector('.sb-spinner');
      if (spinner) {
        streamEl.innerHTML = '';
        const textNode = document.createElement('div');
        textNode.className = 'sb-text';
        streamEl.appendChild(textNode);
      }
      _streamed += chunk;
      if (!_rafPending) {
        _rafPending = true;
        requestAnimationFrame(() => {
          // Only show <T> thought content during streaming to avoid JSON noise.
          const thoughtMatch = _streamed.match(/<T>([\s\S]*?)(?:<\/T>|$)/i);
          const display = thoughtMatch
            ? thoughtMatch[1]
            : _streamed.replace(/<[TAO]>[\s\S]*?<\/[TAO]>/gi, '').trim();
          const textEl = streamEl.querySelector('.sb-text');
          if (textEl) textEl.textContent = display;
          scrollBottom();
          _rafPending = false;
        });
      }
    },

    finalize(stepObj) {
      // Show structured header
      if (stepObj.action) {
        actionTag.textContent = stepObj.action;
        actionTag.classList.remove('hidden');
      }
      hdr.classList.remove('hidden');

      // Hide streaming view
      streamEl.classList.add('hidden');

      // Build structured sections (same logic as appendReactMsg.addStep)
      detailEl.innerHTML = '';
      const secs = document.createElement('div');
      secs.className = 'step-sections';

      const mkSec = (cls, label, content, { markdown = false, code = false } = {}) => {
        const sec = document.createElement('div');
        sec.className = `step-sec ${cls}`;
        const lbl = document.createElement('div');
        lbl.className = 'sec-lbl';
        lbl.textContent = label;
        const cont = document.createElement('div');
        cont.className = 'sec-content';
        if (code) {
          const pre = document.createElement('pre');
          const codeEl = document.createElement('code');
          codeEl.className = 'language-json';
          codeEl.textContent = content;
          if (typeof hljs !== 'undefined') hljs.highlightElement(codeEl);
          pre.appendChild(codeEl);
          cont.appendChild(pre);
        } else if (markdown) {
          renderMarkdown(cont, content);
        } else {
          cont.textContent = content;
        }
        sec.append(lbl, cont);
        return sec;
      };

      if (stepObj.thought) secs.appendChild(mkSec('thought', 'Thought', stepObj.thought, { markdown: true }));

      if (Array.isArray(stepObj.calls) && stepObj.calls.length > 1) {
        const callsWrap = document.createElement('div');
        callsWrap.className = 'step-sec action-sec';
        const callsLbl = document.createElement('div');
        callsLbl.className = 'sec-lbl';
        callsLbl.textContent = `Actions (${stepObj.calls.length} parallel)`;
        callsWrap.appendChild(callsLbl);
        stepObj.calls.forEach((call, idx) => {
          const callEl = document.createElement('div');
          callEl.className = 'parallel-call';
          const argsStr = JSON.stringify(call.args ?? {}, null, 2);
          callEl.innerHTML = `<span class="call-idx">${idx + 1}.</span> <code>${_esc(call.action)}</code>`;
          const pre = document.createElement('pre');
          const codeEl = document.createElement('code');
          codeEl.className = 'language-json';
          codeEl.textContent = argsStr;
          if (typeof hljs !== 'undefined') hljs.highlightElement(codeEl);
          pre.appendChild(codeEl);
          callEl.appendChild(pre);
          callsWrap.appendChild(callEl);
        });
        secs.appendChild(callsWrap);
      } else {
        if (stepObj.action) secs.appendChild(mkSec('action-sec', 'Action', stepObj.action));
        if (stepObj.action_input) {
          const ai = typeof stepObj.action_input === 'string'
            ? stepObj.action_input
            : JSON.stringify(stepObj.action_input, null, 2);
          secs.appendChild(mkSec('action-sec', 'Input', ai, { code: true }));
        }
      }

      if (stepObj.observation) secs.appendChild(mkSec('observation', 'Observation', stepObj.observation, { markdown: true }));

      detailEl.appendChild(secs);

      // Collapsible raw output
      if (_streamed) {
        const rawWrap = document.createElement('div');
        rawWrap.className = 'step-raw-wrap';
        const rawToggle = document.createElement('div');
        rawToggle.className = 'step-raw-toggle';
        rawToggle.innerHTML = '<span class="raw-chevron">▶</span> 原始输出';
        const rawPre = document.createElement('pre');
        rawPre.className = 'step-raw-pre';
        rawPre.textContent = _streamed;
        rawWrap.append(rawToggle, rawPre);
        rawToggle.addEventListener('click', () => {
          const open = rawPre.classList.toggle('open');
          rawToggle.classList.toggle('open', open);
        });
        detailEl.appendChild(rawWrap);
      }

      // Toggle expand/collapse on header click
      hdr.style.cursor = 'pointer';
      hdr.addEventListener('click', () => {
        detailEl.classList.toggle('hidden');
      });

      detailEl.classList.add('hidden');
      detailEl.classList.remove('hidden');  // show after finalize

      timeEl.textContent = _ts();
      timeEl.classList.remove('hidden');

      scrollBottom();
    },

    showActivity(text) {
      const textEl = streamEl.querySelector('.sb-text');
      if (textEl) textEl.textContent = text;
    },

    showPrompt(messages) { _renderFullPrompt(div, messages); },

    openSubAgent:  _openSubAgent,
    addSubChunk:   _addSubChunk,
    addSubStep:    _addSubStep,
    closeSubAgent: _closeSubAgent,

    addStepPause(output, reqId, onContinue, onStop) {
      const pauseEl = document.createElement('div');
      pauseEl.className = 'step-pause-block';
      if (output) {
        const outEl = document.createElement('div');
        outEl.className = 'pause-output';
        outEl.textContent = output;
        pauseEl.appendChild(outEl);
      }
      const btnRow = document.createElement('div');
      btnRow.className = 'pause-btn-row';
      const contBtn = document.createElement('button');
      contBtn.className = 'pause-btn-continue';
      contBtn.textContent = 'Continue';
      contBtn.onclick = () => { onContinue(reqId); pauseEl.remove(); };
      const stopBtn = document.createElement('button');
      stopBtn.className = 'pause-btn-stop';
      stopBtn.textContent = 'Stop';
      stopBtn.onclick = () => { onStop(reqId); pauseEl.remove(); };
      btnRow.append(contBtn, stopBtn);
      pauseEl.appendChild(btnRow);
      body.appendChild(pauseEl);
      scrollBottom();
    },

    remove() { div.remove(); },
  };
}

// ── Full prompt renderer (Issue 6) ────────────────────────────────────────────

function _renderFullPrompt(parentEl, messages) {
  // Issue 6: render exactly once — remove any existing prompt section first.
  parentEl.querySelector('.full-prompt-section')?.remove();

  const section = document.createElement('div');
  section.className = 'full-prompt-section';

  const toggle = document.createElement('button');
  toggle.className = 'full-prompt-toggle';
  toggle.innerHTML = '<span class="chevron">▶</span> Full prompt';

  const body = document.createElement('div');
  body.className = 'full-prompt-body hidden';

  messages.forEach(m => {
    const wrap = document.createElement('div');
    wrap.className = 'full-prompt-msg';
    const chars = (m.content || '').length;
    wrap.innerHTML = `<div class="fp-role ${m.role}">${m.role} <span class="fp-chars">${chars} chars</span></div>`;
    const pre = document.createElement('div');
    pre.className = 'fp-content';
    pre.textContent = m.content || '';
    wrap.appendChild(pre);
    body.appendChild(wrap);
  });

  toggle.addEventListener('click', () => {
    body.classList.toggle('hidden');
    toggle.classList.toggle('open');
  });

  section.append(toggle, body);
  const bodyEl = parentEl.querySelector('.msg-body, .strip-body');
  if (bodyEl) bodyEl.insertBefore(section, bodyEl.firstChild);
}

// ── Step strip (compact progress bar for tool calls) ─────────────────────────

/**
 * Creates a compact step-call strip above bot reply bubbles.
 * Steps without <O> output stack onto the same strip until one has output.
 *
 * Controller:
 *   setStreaming(index)    — show live "Step N · ···" pill
 *   addPill(stepObj)       — finalize a step into a clickable chip
 *   showPrompt(messages)   — wire Full Prompt toggle
 */
export function appendStepStrip() {
  const el = _msgsEl();
  if (!el) return null;
  el.querySelector('.empty-state')?.remove();

  const div = document.createElement('div');
  div.className = 'step-strip-row';

  const icon = document.createElement('div');
  icon.className = 'strip-icon';
  icon.textContent = _agentAvatar;

  const body = document.createElement('div');
  body.className = 'strip-body';

  const pillsEl = document.createElement('div');
  pillsEl.className = 'strip-pills';
  body.appendChild(pillsEl);

  div.append(icon, body);
  el.appendChild(div);
  scrollBottom();

  let _streamingWrap = null;

  function _mkDetail(stepObj) {
    const d = document.createElement('div');
    d.className = 'pill-detail hidden';

    const addRow = (label, content, opts = {}) => {
      const str = content && typeof content === 'object'
        ? JSON.stringify(content, null, 2)
        : String(content ?? '');
      if (!str.trim()) return;
      const row = document.createElement('div');
      row.className = 'pd-row';
      const lbl = document.createElement('div');
      lbl.className = 'pd-lbl';
      lbl.textContent = label;
      const val = document.createElement('div');
      val.className = 'pd-val';
      if (opts.code) {
        const pre = document.createElement('pre');
        pre.textContent = str;
        val.appendChild(pre);
      } else if (opts.markdown) {
        renderMarkdown(val, str);
      } else {
        val.textContent = str;
      }
      row.append(lbl, val);
      d.appendChild(row);
    };

    addRow('THOUGHT',     stepObj.thought,       { markdown: true });
    addRow('ACTION',      stepObj.action);
    addRow('INPUT',       stepObj.action_input,   { code: true });
    addRow('OBSERVATION', stepObj.observation,    { markdown: true });
    return d;
  }

  return {
    setStreaming(index) {
      if (_streamingWrap) {
        const pill = _streamingWrap.querySelector('.step-pill');
        if (pill) pill.querySelector('.pill-step').textContent = `Step ${index + 1}`;
        return;
      }
      const wrap = document.createElement('div');
      wrap.className = 'step-pill-wrap';
      const pill = document.createElement('button');
      pill.className = 'step-pill streaming';
      pill.innerHTML =
        `<span class="pill-step">Step ${index + 1}</span>` +
        `<span class="pill-sep">·</span>` +
        `<span class="pill-dots">···</span>`;
      wrap.appendChild(pill);
      pillsEl.appendChild(wrap);
      _streamingWrap = wrap;
      scrollBottom();
    },

    addPill(stepObj) {
      let wrap, pill;
      if (_streamingWrap) {
        wrap = _streamingWrap;
        pill = wrap.querySelector('.step-pill');
        _streamingWrap = null;
      } else {
        wrap = document.createElement('div');
        wrap.className = 'step-pill-wrap';
        pill = document.createElement('button');
        wrap.appendChild(pill);
        pillsEl.appendChild(wrap);
      }

      const isFinish = stepObj.action === 'finish';
      pill.className = `step-pill ${isFinish ? 'pill-finish' : 'pill-done'}`;
      const label = isFinish ? 'finish' : (_esc(stepObj.action) || '…');
      pill.innerHTML =
        `<span class="pill-step">Step ${stepObj.index + 1}</span>` +
        `<span class="pill-sep">·</span>` +
        `<span class="pill-label">${label}</span>` +
        `<span class="pill-check">✓</span>`;

      const detail = _mkDetail(stepObj);
      wrap.appendChild(detail);
      pill.addEventListener('click', () => {
        detail.classList.toggle('hidden');
        pill.classList.toggle('expanded');
      });
      scrollBottom();
    },

    showPrompt(messages) { _renderFullPrompt(div, messages); },

    dismissLoading() {
      if (_streamingWrap) {
        _streamingWrap.remove();
        _streamingWrap = null;
      }
    },
  };
}

// ── Speak stream：按协议字段分色分块渲染 ──────────────────────────────────────

const _SPEAK_FIELD_LABEL = Object.freeze({
  thought: 'think',
  speak: 'speak',
  body: 'body',
  wait: 'wait',
  silence: 'silence',
  typing: 'typing',
  finish: 'finish',
  observe: 'narrative',
  outline: 'outline',
  anchor: 'anchor',
  session: 'state',
});

/**
 * Soul Speak 流式消息：每个协议字段一块，带标签与独立配色。
 */
function _isHollowSpeakMsg(node) {
  return Boolean(
    node?.classList?.contains('speak-msg')
    && !node.querySelector('.speak-field, .speak-render-spinner, .speak-abort-note')
  );
}

export function appendSpeakStream(opts = {}) {
  const el = _msgsEl();
  if (!el) return null;
  el.querySelector('.empty-state')?.remove();
  while (_isHollowSpeakMsg(el.lastElementChild)) {
    el.lastElementChild.remove();
  }

  const div = document.createElement('div');
  div.className = 'message assistant speak-msg';

  const avatar = document.createElement('div');
  avatar.className = 'msg-avatar';
  avatar.textContent = _agentAvatar;

  const body = document.createElement('div');
  body.className = 'msg-body';

  const streamCol = document.createElement('div');
  streamCol.className = 'speak-stream';

  let _createdAt = String(opts.created_at ?? '').trim();
  const timeEl = document.createElement('span');
  timeEl.className = 'msg-time';
  timeEl.textContent = _ts(_createdAt || undefined);

  const ttsBtn = document.createElement('button');
  ttsBtn.className = 'msg-tts-btn hidden';
  ttsBtn.title = 'Play';
  ttsBtn.innerHTML = `<span class="sound-wave"><b></b><b></b><b></b><b></b><b></b></span>`;

  body.append(streamCol, timeEl, ttsBtn);
  div.append(avatar, body);
  el.appendChild(div);
  scrollBottom();

  let _speakParts = [];
  let _events = [];
  let _openBlock = null; // { wrap, content, field, kind, meta }
  let _thinkPending = null;
  let _finalized = false;
  let _renderSpinner = null;
  const _playQueue = [];
  let _acceptedLive = false;
  let _pumping = false;
  let _stopped = false;
  let _idleWaiters = [];

  function _showTypingIndicator() {
    setTitleBarTyping(true);
  }

  function _hideTypingIndicator() {
    setTitleBarTyping(false);
  }

  function _spinnerTarget(meta = {}) {
    const target = String(meta.render_target || meta.role_op || '').trim().toLowerCase();
    if (target === 'body' || target === 'action') return 'body';
    return 'speak';
  }

  function _showRenderSpinner(meta = {}) {
    const target = _spinnerTarget(meta);
    if (_renderSpinner) {
      const current = _renderSpinner.className.includes('spinner-body') ? 'body' : 'speak';
      if (current === target) return;
      _hideRenderSpinner();
    }
    const wrap = document.createElement('div');
    wrap.className = `speak-render-spinner speak-render-spinner-${target}`;
    wrap.innerHTML = '<span class="speak-render-spinner-icon"></span>';
    const order = resolveRenderOrder(meta?.[META_ORDER]);
    if (order != null) wrap.dataset.order = String(order);
    _insertFieldWrap(wrap, order);
    _renderSpinner = wrap;
    scrollBottom();
  }

  function _hideRenderSpinner() {
    _renderSpinner?.remove();
    _renderSpinner = null;
  }

  function _fieldKey(kind, meta = {}) {
    return resolveRenderField(kind, meta)
      || (kind === 'action' ? 'body' : null)
      || (kind === 'thought' ? 'thought' : null)
      || (kind === 'speak' || kind === 'segment' ? 'speak' : null)
      || (kind === 'observe' ? 'observe' : null)
      || (kind === 'outline' ? 'outline' : null)
      || (kind === 'anchor' ? 'anchor' : null)
      || 'speak';
  }

  function _closeOpenBlock() {
    if (!_openBlock) return;
    const { wrap, content, field, kind, meta } = _openBlock;
    wrap.classList.remove('streaming');
    const text = String(content.textContent || '').trim();
    if (!text) {
      wrap.remove();
    } else {
      if (field === 'speak') _speakParts.push(text);
      _events.push({
        kind: kind === 'segment' ? 'speak' : kind,
        text,
        meta: { ...meta, field },
      });
    }
    _openBlock = null;
  }

  function _insertFieldWrap(wrap, order) {
    if (order == null) {
      if (_renderSpinner && wrap !== _renderSpinner) {
        streamCol.insertBefore(wrap, _renderSpinner);
      } else {
        streamCol.appendChild(wrap);
      }
      return;
    }
    const kids = [...streamCol.children].filter(
      (el) => el.classList && (
        el.classList.contains('speak-field')
        || el.classList.contains('speak-render-spinner')
      ),
    );
    for (const kid of kids) {
      if (kid === wrap) continue;
      const ko = resolveRenderOrder(kid.dataset.order);
      if (ko != null && ko > order) {
        streamCol.insertBefore(wrap, kid);
        return;
      }
    }
    streamCol.appendChild(wrap);
  }

  function _ensureFieldBlock(field, kind, meta = {}) {
    if (_openBlock && _openBlock.field === field) {
      const openOrder = resolveRenderOrder(_openBlock.meta?.[META_ORDER]);
      const nextOrder = resolveRenderOrder(meta?.[META_ORDER]);
      // 同 field 但索引不同：拆成新块，避免交叉演出被合并
      if (openOrder == null || nextOrder == null || openOrder === nextOrder) {
        _openBlock.meta = { ...meta, field };
        return _openBlock;
      }
    }
    _closeOpenBlock();
    if (_thinkPending) {
      _thinkPending.wrap.remove();
      _thinkPending = null;
    }

    const wrap = document.createElement('div');
    wrap.className = `speak-field speak-field-${field} streaming`;
    wrap.dataset.field = field;
    const order = resolveRenderOrder(meta?.[META_ORDER]);
    if (order != null) wrap.dataset.order = String(order);
    const slot = String(meta?.slot ?? '').trim();
    if (slot) wrap.dataset.slot = slot;

    const label = document.createElement('span');
    label.className = 'speak-field-label';
    label.textContent = _SPEAK_FIELD_LABEL[field] || fieldLabel(field) || field;

    const content = document.createElement('div');
    content.className = 'speak-field-content';

    wrap.append(label, content);
    _insertFieldWrap(wrap, order);
    _openBlock = { wrap, content, field, kind, meta: { ...meta, field } };
    scrollBottom();
    return _openBlock;
  }

  function _appendFieldChunk(field, kind, chunk, meta = {}) {
    const piece = String(chunk ?? '');
    if (!piece) return;
    const block = _ensureFieldBlock(field, kind, meta);
    block.content.textContent += piece;
    scrollBottom();
  }

  function _lastCommittedText(field) {
    for (let i = _events.length - 1; i >= 0; i -= 1) {
      if (String(_events[i]?.meta?.field || '') === field) {
        return String(_events[i].text || '').trim();
      }
    }
    return '';
  }

  function _sameFieldTextOrder(field, text, meta, otherField, otherText, otherMeta) {
    if (field !== otherField) return false;
    if (String(text ?? '').trim() !== String(otherText ?? '').trim()) return false;
    const order = resolveRenderOrder(meta?.[META_ORDER]);
    const other = resolveRenderOrder(otherMeta?.[META_ORDER]);
    if (order != null && other != null) return order === other;
    return true;
  }

  function _isDuplicateContent(field, text, meta = {}) {
    const body = String(text ?? '').trim();
    if (!body || (field !== 'body' && field !== 'speak')) return false;
    for (const ev of _events) {
      if (_sameFieldTextOrder(field, body, meta, ev?.meta?.field, ev.text, ev.meta)) return true;
    }
    for (const item of _playQueue) {
      if (_sameFieldTextOrder(field, body, meta, item.field, item.text, item.meta)) return true;
    }
    if (_lastCommittedText(field) === body) return true;
    const wraps = streamCol.querySelectorAll(`.speak-field-${field} .speak-field-content`);
    const last = wraps.length ? String(wraps[wraps.length - 1].textContent || '').trim() : '';
    return last === body;
  }

  function _commitField(field, kind, text, meta = {}) {
    // wait / think 不对用户展示
    if (field === 'wait' || field === 'thought' || field === 'silence') return;
    const body = String(text ?? '').trim();
    if (!body && field !== 'silence' && field !== 'finish') return;
    if (_isDuplicateContent(field, body, meta)) return;
    _closeOpenBlock();
    if (_thinkPending) {
      _thinkPending.wrap.remove();
      _thinkPending = null;
    }

    const wrap = document.createElement('div');
    wrap.className = `speak-field speak-field-${field}`;
    wrap.dataset.field = field;
    const order = resolveRenderOrder(meta?.[META_ORDER]);
    if (order != null) wrap.dataset.order = String(order);
    const slot = String(meta?.slot ?? '').trim();
    if (slot) wrap.dataset.slot = slot;

    const label = document.createElement('span');
    label.className = 'speak-field-label';
    label.textContent = _SPEAK_FIELD_LABEL[field] || fieldLabel(field) || field;

    const content = document.createElement('div');
    content.className = 'speak-field-content';

    if (field === 'silence') {
      const seconds = meta.seconds ?? (meta.wait_ms != null ? Number(meta.wait_ms) / 1000 : null);
      content.textContent = seconds != null && !Number.isNaN(seconds)
        ? `${field} ${seconds}s`
        : (body || field);
    } else if (field === 'finish' || field === 'session') {
      content.textContent = body || String(meta[META_SESSION_STATE] || field);
    } else {
      content.textContent = body;
    }

    wrap.append(label, content);
    _insertFieldWrap(wrap, order);

    if (field === 'speak' && body) _speakParts.push(body);
    if (meta?.placeholder) wrap.classList.add('speak-outline-placeholder');
    _events.push({
      kind: kind === 'segment' ? 'speak' : kind,
      text: content.textContent,
      meta: { ...meta, field },
    });
    scrollBottom();
  }

  function _handleStreamChunk(kind, text, meta = {}) {
    const field = _fieldKey(kind, meta);
    const phase = String(meta[META_PHASE] ?? meta.phase ?? '').trim();
    const chunk = String(text ?? '');

    if (phase === 'delta') {
      _appendFieldChunk(field, kind, chunk, meta);
      return;
    }
    if (phase === 'end') {
      if (chunk) {
        if (_openBlock && _openBlock.field === field) {
          if (!_openBlock.content.textContent) _openBlock.content.textContent = chunk;
          else if (!_openBlock.content.textContent.endsWith(chunk)) {
            _openBlock.content.textContent += chunk;
          }
        } else {
          _appendFieldChunk(field, kind, chunk, meta);
        }
      }
      _closeOpenBlock();
      scrollBottom();
      return;
    }
    _commitField(field, kind, chunk, meta);
  }

  function _ensureThinkPending() {
    // think 隐藏：不创建占位卡片
    return null;
  }

  function _renderByField(kind, text, meta = {}) {
    const field = _fieldKey(kind, meta);
    if (!field || field === 'finish' || field === 'typing') {
      // finish 一律空文案；有正文也不渲染成可见字段
      return;
    }
    if (field === 'speak' || field === 'body' || field === 'outline') _hideRenderSpinner();
    _handleStreamChunk(kind, text, { ...meta, field });
  }

  function _replaceSlotContent(slot, text, meta = {}) {
    const key = String(slot || '').trim();
    const body = String(text ?? '').trim();
    if (!key || !body) return false;
    const wrap = streamCol.querySelector(`.speak-field[data-slot="${CSS.escape(key)}"]`)
      || document.querySelector(`.speak-field[data-slot="${CSS.escape(key)}"]`);
    if (!wrap) return false;
    const content = wrap.querySelector('.speak-field-content');
    if (!content) return false;
    content.textContent = body;
    wrap.classList.remove('streaming', 'speak-outline-placeholder');
    if (meta?.placeholder) wrap.classList.add('speak-outline-placeholder');
    else wrap.classList.remove('speak-outline-placeholder');
    const field = String(wrap.dataset.field || meta?.field || 'outline').trim() || 'outline';
    let patched = false;
    for (let i = _events.length - 1; i >= 0; i -= 1) {
      const ev = _events[i];
      if (String(ev?.meta?.slot || '').trim() !== key) continue;
      _events[i] = {
        ...ev,
        text: body,
        meta: { ...ev.meta, ...meta, field, slot: key, upgrade: true, replace: true },
      };
      patched = true;
      break;
    }
    if (!patched) {
      _events.push({
        kind: 'outline',
        text: body,
        meta: { ...meta, field, slot: key, upgrade: true, replace: true },
      });
    }
    if (typeof opts.onSlotReplace === 'function') {
      opts.onSlotReplace(key, body, { ...meta, field, slot: key });
    }
    scrollBottom();
    return true;
  }

  function _dispatchEvent(kind, text, meta = {}) {
    const isSlotUpgrade = (
      (kind === 'outline' || resolveRenderField(kind, meta) === 'outline')
      && Boolean(meta?.upgrade || meta?.replace)
      && String(meta?.slot || '').trim()
    );
    if (_finalized && !isSlotUpgrade) return;
    if (isSlotUpgrade && _replaceSlotContent(meta.slot, text, meta)) return;
    if (_finalized) return;
    const eventStamp = String(meta?.created_at ?? '').trim();
    if (eventStamp && !_createdAt) api.setCreatedAt(eventStamp);
    const field = resolveRenderField(kind, meta);
    switch (kind) {
      case 'agent_typing':
        if (Number(meta.render_time_ms) > 0 || Number(meta.wait_ms) > 0) _showRenderSpinner(meta);
        else if (meta.active === false || meta.active === 'false') _hideTypingIndicator();
        else _showTypingIndicator();
        break;
      case 'tag':
        if (meta.tag === 'think' || field === 'thought') {
          // think 隐藏
          break;
        } else if (meta.tag === 'speak' || field === 'speak') {
          _ensureFieldBlock('speak', 'speak', meta);
        } else if (meta.tag === 'action' || field === 'body') {
          _ensureFieldBlock('body', 'action', meta);
        }
        break;
      case 'chunk':
        // 旧 chunk=think 流；隐藏后不再建占位
        break;
      case 'thought':
        break;
      case 'action':
      case 'state':
      case 'observe':
      case 'outline':
      case 'anchor':
      case 'speak':
      case 'segment':
      case 'finish':
        _renderByField(kind, text, meta);
        break;
      case 'error':
        _commitField('body', 'action', text || 'error', { field: 'body' });
        break;
      default:
        if (field) _renderByField(kind, text, meta);
        break;
    }
  }

  function _packetWaitMs(meta = {}) {
    const renderMs = Number(meta[META_RENDER_TIME_MS] ?? meta.render_time_ms);
    const waitMs = Number(meta[META_WAIT_MS] ?? meta.wait_ms);
    const a = Number.isFinite(renderMs) && renderMs > 0 ? renderMs : 0;
    const b = Number.isFinite(waitMs) && waitMs > 0 ? waitMs : 0;
    return Math.max(a, b);
  }

  function _notifyIdle() {
    if (_pumping || _playQueue.length) return;
    const waiters = _idleWaiters;
    _idleWaiters = [];
    for (const resolve of waiters) resolve();
  }

  function _waitUntilIdle() {
    if (!_pumping && !_playQueue.length) return Promise.resolve();
    return new Promise((resolve) => {
      _idleWaiters.push(resolve);
    });
  }

  async function _playPacket(pkt) {
    if (_stopped) return;
    const field = pkt.field;
    if (field === 'thought' || field === 'finish') return;

    if (field === 'typing') {
      _showRenderSpinner(pkt.meta);
      return;
    }

    if (_isDuplicateContent(field, pkt.text, pkt.meta)) return;
    _hideRenderSpinner();
    _dispatchEvent(pkt.kind, pkt.text, pkt.meta);
  }

  async function _pumpQueue() {
    if (_pumping || _stopped) return;
    _pumping = true;
    while (_playQueue.length && !_stopped) {
      const pkt = _playQueue.shift();
      await _playPacket(pkt);
    }
    _pumping = false;
    if (_playQueue.length && !_stopped) {
      _pumpQueue();
      return;
    }
    _notifyIdle();
  }

  function _enqueuePacket(kind, text, meta = {}) {
    if (kind === 'tag' || kind === 'chunk') return;
    if (kind === 'error') {
      _acceptedLive = true;
      _playQueue.push({ kind, text, meta, field: 'body', waitMs: 0 });
      _pumpQueue();
      return;
    }
    const field = resolveRenderField(kind, meta) || _fieldKey(kind, meta);
    if (!field || field === 'thought' || field === 'finish' || field === 'silence' || field === 'wait') return;
    const body = String(text ?? '').trim();
    if ((field === 'speak' || field === 'body' || field === 'observe' || field === 'outline') && !body) return;
    if ((field === 'speak' || field === 'body') && _isDuplicateContent(field, body, meta)) return;
    _acceptedLive = true;
    _playQueue.push({
      kind,
      text,
      meta,
      field,
      waitMs: (field === 'body' || field === 'speak' || field === 'outline' || field === 'observe')
        ? _packetWaitMs(meta)
        : 0,
    });
    _pumpQueue();
  }

  const api = {
    el,
    get _finalized() { return _finalized; },
    setCreatedAt(iso) {
      const stamp = String(iso ?? '').trim();
      if (!stamp) return;
      _createdAt = stamp;
      timeEl.textContent = _ts(stamp);
    },
    get createdAt() { return _createdAt; },
    get hasLiveInput() {
      return _acceptedLive || _events.length > 0 || _playQueue.length > 0;
    },
    onEvent(kind, text, meta = {}) {
      const isSlotUpgrade = (
        kind === 'outline'
        && Boolean(meta?.upgrade || meta?.replace)
        && String(meta?.slot || '').trim()
      );
      if (_stopped && !isSlotUpgrade) return;
      if (_finalized && !isSlotUpgrade) return;
      const eventStamp = String(meta?.created_at ?? '').trim();
      if (eventStamp && !_createdAt) api.setCreatedAt(eventStamp);
      _enqueuePacket(kind, text, meta);
    },
    async finalize(answer, aborted = false, replayEvents = null) {
      _hideTypingIndicator();
      if (aborted) {
        _stopped = true;
        _playQueue.length = 0;
      }

      if (
        !_acceptedLive
        && !_events.length
        && !_playQueue.length
        && Array.isArray(replayEvents)
        && replayEvents.length
      ) {
        for (const ev of sortEventsByOrder(replayEvents)) {
          api.onEvent(ev.kind, ev.text ?? '', ev.meta ?? {});
        }
      }

      await _waitUntilIdle();
      _hideRenderSpinner();

      if (_thinkPending) {
        _thinkPending.wrap.remove();
        _thinkPending = null;
      }
      _closeOpenBlock();

      const finalText = (_speakParts.join('') || String(answer ?? '')).trim();
      // 已有分字段事件时绝不再整段 dump answer
      if (!_events.length && finalText && !aborted) {
        _commitField('speak', 'speak', finalText, { field: 'speak' });
      }

      if (_createdAt) timeEl.textContent = _ts(_createdAt);

      if (aborted) {
        const note = document.createElement('div');
        note.className = 'speak-abort-note';
        note.textContent = '⊘ aborted';
        streamCol.appendChild(note);
      } else if (finalText) {
        ttsBtn.classList.remove('hidden');
        ttsBtn.dataset.text = finalText;
      }
      _finalized = true;
      if (_isHollowSpeakMsg(div)) {
        div.remove();
        return;
      }
      scrollBottom();
    },
    discardAgentTurn() {
      _stopped = true;
      _finalized = true;
      _playQueue.length = 0;
      _notifyIdle();
      _hideTypingIndicator();
      _hideRenderSpinner();
      div.remove();
      _openBlock = null;
      _thinkPending = null;
      _speakParts = [];
      _events = [];
    },
    get speakText() { return _speakParts.join(''); },
    get events() { return _events; },
    replaceSlot(slot, text, meta = {}) {
      return _replaceSlotContent(slot, text, meta);
    },
  };
  return api;
}

/** 就地替换已渲染的 outline 占位（可跨回合、已 finalize）。 */
export function replaceOutlineSlot(slot, text, meta = {}) {
  const key = String(slot || '').trim();
  const body = String(text ?? '').trim();
  if (!key || !body) return false;
  const wrap = document.querySelector(`.speak-field[data-slot="${CSS.escape(key)}"]`);
  if (!wrap) return false;
  const content = wrap.querySelector('.speak-field-content');
  if (!content) return false;
  content.textContent = body;
  wrap.classList.remove('streaming', 'speak-outline-placeholder');
  if (meta?.placeholder) wrap.classList.add('speak-outline-placeholder');
  return true;
}

/** 顶栏「对方正在输入」状态。 */
export function setTitleBarTyping(active) {
  const tb = document.getElementById('tb-title');
  const spin = document.getElementById('tb-typing');
  if (!tb) return;
  if (active) {
    if (!tb.dataset.savedTitle) {
      tb.dataset.savedTitle = tb.textContent.trim() || '对话';
    }
    tb.textContent = '对方正在输入…';
    tb.classList.add('tb-typing');
    if (spin) {
      spin.classList.remove('hidden');
      spin.setAttribute('aria-hidden', 'false');
    }
    return;
  }
  tb.classList.remove('tb-typing');
  if (spin) {
    spin.classList.add('hidden');
    spin.setAttribute('aria-hidden', 'true');
  }
  const saved = tb.dataset.savedTitle;
  if (saved) {
    tb.textContent = saved;
    delete tb.dataset.savedTitle;
  }
}

export function showSpeakTurnTyping() {
  setTitleBarTyping(true);
}
