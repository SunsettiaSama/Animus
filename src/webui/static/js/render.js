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

  // Activity strip (spinner + current label)
  const activity = document.createElement('div');
  activity.className = 'react-activity';
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
      activity.remove();
    },
    appendChunk(index, chunk) {
      const s = _ensureStep(index);
      s.streamed += chunk;
      s.rawEl.textContent = s.streamed;
      scrollBottom();
    },
    addStep(stepObj) {
      const s = _ensureStep(stepObj.index);
      s.hdr.querySelector('.step-streaming-label').remove();
      // Build structured view
      s.detail.innerHTML = '';
      const secs = document.createElement('div');
      secs.className = 'step-sections';

      const mkSec = (cls, label, content) => {
        const sec = document.createElement('div');
        sec.className = `step-sec ${cls}`;
        sec.innerHTML = `<div class="sec-lbl">${label}</div><div class="sec-content">${_esc(content)}</div>`;
        return sec;
      };
      if (stepObj.thought) secs.appendChild(mkSec('thought', 'Thought', stepObj.thought));
      if (stepObj.action)  secs.appendChild(mkSec('action-sec', 'Action', stepObj.action));
      if (stepObj.action_input) {
        const ai = typeof stepObj.action_input === 'string'
          ? stepObj.action_input
          : JSON.stringify(stepObj.action_input, null, 2);
        secs.appendChild(mkSec('action-sec', 'Input', ai));
      }
      if (stepObj.observation) secs.appendChild(mkSec('observation', 'Observation', stepObj.observation));
      s.detail.appendChild(secs);

      // Mark step done
      const doneEl = document.createElement('span');
      doneEl.className = 'step-done';
      doneEl.textContent = '✓';
      s.hdr.appendChild(doneEl);
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
