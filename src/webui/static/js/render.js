/**
 * render.js — Message rendering and ReAct step display.
 *
 * Public API:
 *   appendUserMsg(text)
 *   appendAssistantMsg(id?)  → returns { el, bubble, append, finalize, showPrompt }
 *   appendReactMsg(id?)      → returns { el, appendChunk, addStep, finalize, showPrompt, showActivity }
 *   renderMarkdown(el, text)
 *   scrollBottom()
 *   clearMsgs()
 *   showEmptyState(mode)
 */

const _msgsEl = () => document.getElementById('msgs');
const _esc    = s => s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
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
  div.firstElementChild.textContent = '🤖';
  el.appendChild(div);
  scrollBottom();

  let _text = '';
  return {
    el,
    bubble,
    append(chunk) {
      _text += chunk;
      bubble.textContent = _text;
      scrollBottom();
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
  const _steps = {};   // index → { card, rawEl, sections, streamed }
  let   _stepI = -1;
  let   _ansText = '';
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
      // Hide the activity spinner on the very first chunk — step card takes over.
      if (!s.streamed) activity.classList.add('hidden');
      s.streamed += chunk;
      // During streaming, show only the <T> thought content to avoid exposing
      // raw JSON inside <A> and raw output inside <O> before they are structured.
      const thoughtMatch = s.streamed.match(/<T>([\s\S]*?)(?:<\/T>|$)/i);
      s.rawEl.textContent = thoughtMatch ? thoughtMatch[1] : s.streamed.replace(/<[TAO]>[\s\S]*?<\/[TAO]>/gi, '').trim();
      // Open the detail automatically on first chunk so the streaming text is visible.
      if (!s.detail.classList.contains('open')) {
        s.detail.classList.add('open');
        s.hdr.classList.add('open');
      }
      scrollBottom();
    },
    addStep(stepObj) {
      const s = _ensureStep(stepObj.index);
      s.hdr.querySelector('.step-streaming-label').remove();

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

      // Mark step done and ensure detail stays open.
      const doneEl = document.createElement('span');
      doneEl.className = 'step-done';
      doneEl.textContent = '✓';
      s.hdr.appendChild(doneEl);
      s.detail.classList.add('open');
      s.hdr.classList.add('open');

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
    appendAnswer(chunk) {
      _ansText += chunk;
      answerBubble.classList.remove('hidden');
      answerBubble.classList.add('streaming');
      answerBubble.textContent = _ansText;
      scrollBottom();
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
  parentEl.querySelector('.msg-body').insertBefore(section, parentEl.querySelector('.msg-body').firstChild);
}
