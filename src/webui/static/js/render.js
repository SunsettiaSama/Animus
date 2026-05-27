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

const _msgsEl = () => document.getElementById('msgs');
const _esc    = s => s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');

// ── Agent avatar (unified, configurable) ──────────────────────────────────────
let _agentAvatar = '⚡';
export function setAgentAvatar(v) { _agentAvatar = v || '⚡'; }
const _ts     = () => {
  const d = new Date();
  return `${d.getHours().toString().padStart(2,'0')}:${d.getMinutes().toString().padStart(2,'0')}`;
};

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

export function appendUserMsg(text) {
  const el = _msgsEl();
  if (!el) return;
  el.querySelector('.empty-state')?.remove();
  const div = document.createElement('div');
  div.className = 'message user';
  div.innerHTML = `
    <div class="msg-avatar">U</div>
    <div class="msg-body">
      <div class="msg-bubble">${_esc(text)}</div>
      <span class="msg-time">${_ts()}</span>
    </div>`;
  el.appendChild(div);
  scrollBottom();
  return div;
}

// ── Chat assistant message ────────────────────────────────────────────────────

/**
 * Creates an assistant bubble for streaming chat output.
 * Returns a controller object.
 */
export function appendAssistantMsg(id) {
  const el = _msgsEl();
  if (!el) return null;
  el.querySelector('.empty-state')?.remove();

  const div = document.createElement('div');
  div.className = 'message assistant';
  if (id) div.dataset.msgId = id;

  const bubble = document.createElement('div');
  bubble.className = 'msg-bubble streaming';

  const timeEl = document.createElement('span');
  timeEl.className = 'msg-time';
  timeEl.textContent = _ts();

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

// ── Speak stream (Soul tag-based streaming) ───────────────────────────────────

const _SPEAK_TAG = {
  thought: { tag: 'think', cls: 'speak-thought' },
  action:  { tag: 'action', cls: 'speak-action' },
  state:   { tag: 'state', cls: 'speak-state' },
  observe: { tag: 'observe', cls: 'speak-observe' },
  anchor:  { tag: 'anchor', cls: 'speak-anchor' },
  chunk:   { tag: '…', cls: 'speak-chunk' },
};

function _shortSpeakText(text, max = 28) {
  const s = String(text ?? '').trim().replace(/\s+/g, ' ');
  if (!s) return '';
  return s.length > max ? `${s.slice(0, max)}…` : s;
}

function _mkSpeakDetail(label, content, opts = {}) {
  const d = document.createElement('div');
  d.className = 'pill-detail hidden';
  const row = document.createElement('div');
  row.className = 'pd-row';
  const lbl = document.createElement('div');
  lbl.className = 'pd-lbl';
  lbl.textContent = label;
  const val = document.createElement('div');
  val.className = 'pd-val';
  const str = String(content ?? '').trim();
  if (str) {
    if (opts.markdown) renderMarkdown(val, str);
    else val.textContent = str;
  }
  row.append(lbl, val);
  d.appendChild(row);
  return d;
}

/**
 * Soul Speak 流式消息容器：meta pills（think/action/state/observe）+ 主 speak bubble。
 */
export function appendSpeakStream() {
  const el = _msgsEl();
  if (!el) return null;
  el.querySelector('.empty-state')?.remove();

  const div = document.createElement('div');
  div.className = 'message assistant speak-msg';

  const avatar = document.createElement('div');
  avatar.className = 'msg-avatar';
  avatar.textContent = _agentAvatar;

  const body = document.createElement('div');
  body.className = 'msg-body';

  const metaRow = document.createElement('div');
  metaRow.className = 'speak-meta strip-pills';

  const bubble = document.createElement('div');
  bubble.className = 'msg-bubble streaming hidden';

  const timeEl = document.createElement('span');
  timeEl.className = 'msg-time';
  timeEl.textContent = _ts();

  const ttsBtn = document.createElement('button');
  ttsBtn.className = 'msg-tts-btn hidden';
  ttsBtn.title = 'Play';
  ttsBtn.innerHTML = `<span class="sound-wave"><b></b><b></b><b></b><b></b><b></b></span>`;

  body.append(metaRow, bubble, timeEl, ttsBtn);
  div.append(avatar, body);
  el.appendChild(div);
  scrollBottom();

  let _speakText = '';
  let _rafPending = false;
  let _chunkPill = null;
  let _events = [];

  function _appendSpeak(chunk) {
    if (!chunk) return;
    bubble.classList.remove('hidden');
    _speakText += chunk;
    if (!_rafPending) {
      _rafPending = true;
      requestAnimationFrame(() => {
        bubble.textContent = _speakText;
        scrollBottom();
        _rafPending = false;
      });
    }
  }

  function _ensureChunkPill() {
    if (_chunkPill) return _chunkPill;
    const wrap = document.createElement('div');
    wrap.className = 'step-pill-wrap';
    const pill = document.createElement('button');
    pill.className = 'step-pill streaming speak-chunk';
    pill.innerHTML =
      `<span class="pill-step">think</span>` +
      `<span class="pill-sep">·</span>` +
      `<span class="pill-dots">···</span>`;
    wrap.appendChild(pill);
    metaRow.appendChild(wrap);
    _chunkPill = { wrap, pill };
    scrollBottom();
    return _chunkPill;
  }

  function _finalizeChunkPill(label, text) {
    if (!_chunkPill) return;
    const { wrap, pill } = _chunkPill;
    _chunkPill = null;
    const cfg = _SPEAK_TAG.thought;
    pill.className = `step-pill pill-done ${cfg.cls}`;
    const short = _shortSpeakText(text);
    pill.innerHTML =
      `<span class="pill-step">${cfg.tag}</span>` +
      `<span class="pill-sep">·</span>` +
      `<span class="pill-label">${short || label}</span>` +
      `<span class="pill-check">✓</span>`;
    if (text && text.trim()) {
      const detail = _mkSpeakDetail('THINK', text, { markdown: true });
      wrap.appendChild(detail);
      pill.addEventListener('click', () => {
        detail.classList.toggle('hidden');
        pill.classList.toggle('expanded');
      });
    }
    scrollBottom();
  }

  function _addTagPill(kind, text, meta = {}) {
    if (_chunkPill && kind === 'thought') {
      _finalizeChunkPill('think', text);
      _events.push({ kind, text, meta });
      return;
    }
    if (_chunkPill) {
      _chunkPill.wrap.remove();
      _chunkPill = null;
    }

    const cfg = _SPEAK_TAG[kind] ?? { tag: kind, cls: '' };
    const wrap = document.createElement('div');
    wrap.className = 'step-pill-wrap';
    const pill = document.createElement('button');
    pill.className = `step-pill pill-done ${cfg.cls}`;

    let label = cfg.tag;
    let detailText = text;
    if (kind === 'state') {
      label = meta.session_state || text || 'state';
      detailText = meta.session_state || text;
    } else if (kind === 'action') {
      label = _shortSpeakText(text) || 'action';
    } else if (kind === 'observe') {
      label = _shortSpeakText(text) || 'observe';
    } else if (kind === 'thought') {
      label = _shortSpeakText(text) || 'think';
    }

    pill.innerHTML =
      `<span class="pill-step">${cfg.tag}</span>` +
      `<span class="pill-sep">·</span>` +
      `<span class="pill-label">${_esc(label)}</span>` +
      `<span class="pill-check">✓</span>`;

    if (detailText && String(detailText).trim()) {
      const detail = _mkSpeakDetail(cfg.tag.toUpperCase(), detailText, {
        markdown: kind === 'thought' || kind === 'observe',
      });
      wrap.appendChild(detail);
      pill.addEventListener('click', () => {
        detail.classList.toggle('hidden');
        pill.classList.toggle('expanded');
      });
    }

    wrap.appendChild(pill);
    metaRow.appendChild(wrap);
    _events.push({ kind, text, meta });
    scrollBottom();
  }

  return {
    el,
    bubble,
    onEvent(kind, text, meta = {}) {
      switch (kind) {
        case 'chunk':
          _ensureChunkPill();
          break;
        case 'thought':
          _addTagPill('thought', text, meta);
          break;
        case 'action':
          _addTagPill('action', text, meta);
          break;
        case 'state':
          _addTagPill('state', text, meta);
          break;
        case 'observe':
          _addTagPill('observe', text, meta);
          break;
        case 'anchor':
          _addTagPill('anchor', text, meta);
          break;
        case 'speak':
        case 'segment':
          if (_chunkPill) {
            _chunkPill.wrap.remove();
            _chunkPill = null;
          }
          _appendSpeak(text);
          break;
        case 'finish':
          break;
        case 'error':
          _addTagPill('action', text || 'error', meta);
          break;
        default:
          break;
      }
    },
    finalize(answer, aborted = false) {
      if (_chunkPill) {
        _chunkPill.wrap.remove();
        _chunkPill = null;
      }
      bubble.classList.remove('streaming', 'hidden');
      const finalText = (answer || _speakText || '').trim();
      if (aborted) {
        bubble.innerHTML += '<br><span style="color:var(--text3);font-size:11px">⊘ aborted</span>';
      } else if (finalText) {
        _speakText = finalText;
        renderMarkdown(bubble, finalText);
        ttsBtn.classList.remove('hidden');
        ttsBtn.dataset.text = finalText;
      } else if (!_speakText) {
        bubble.classList.add('hidden');
      }
      if (metaRow.childElementCount === 0) metaRow.classList.add('hidden');
      scrollBottom();
    },
    get speakText() { return _speakText; },
    get events() { return _events; },
  };
}
