/**
 * screens/workspace.js — Chat workspace screen logic.
 *
 * Responsibilities:
 *   - Send / abort handling.
 *   - ReAct streaming session lifecycle.
 *   - Mic recording.
 *   - TTS delegation.
 *   - New conversation.
 *   - History rebuild from saved messages.
 *   - Title update after first assistant reply.
 *   - Knowledge-base panel toggle.
 */

import { S, setState, set }    from '../state.js';
import { PATHS }               from '../api.js';
import * as render              from '../render.js';
import * as historyMod          from '../history.js';
import * as streaming           from '../streaming.js';
import { goWorkspace }         from '../router.js';
import { bus }                 from '../eventBus.js';
import { showToast }           from '../shared/toast.js';

let _voiceMod     = null;
let _knowledgeMod = null;

/** Inject module references needed by workspace (set from app.js). */
export function registerModules({ voiceMod, knowledgeMod }) {
  _voiceMod     = voiceMod;
  _knowledgeMod = knowledgeMod;
}

// ── New conversation ──────────────────────────────────────────────────────────

export function startNew() {
  streaming.abortCurrent();
  set('convId', null);
  set('convTitle', 'New Conversation');
  historyMod.clearMessages();
  render.clearMsgs();
  render.showEmptyState();
  const tb = document.getElementById('tb-title');
  if (tb) tb.textContent = 'New Conversation';
  _updateReactBadge();
  goWorkspace();
  historyMod.renderSidebar();
  import('/static/js/modules/plan.js').then(m => m.initSubPanel()).catch(() => {});
}

// ── Topbar badge ──────────────────────────────────────────────────────────────

export function updateReactBadge() { _updateReactBadge(); }

function _updateReactBadge() {
  const el = document.getElementById('tb-react-status');
  if (!el) return;
  el.textContent = S.reactReady ? '⚡ Ready' : '⚡ Not ready';
  el.style.color = S.reactReady ? 'var(--accent)' : 'var(--text3)';
}

// ── Send / abort ──────────────────────────────────────────────────────────────

export async function handleSend() {
  if (S.lifecycle === 'streaming' || S.lifecycle === 'aborting') {
    streaming.abortCurrent();
    setState('aborting');
    return;
  }
  const inputEl  = document.getElementById('msg-input');
  const question = inputEl?.value.trim();
  if (!question) return;
  if (inputEl) inputEl.value = '';

  goWorkspace();
  historyMod.renderSidebar();
  import('/static/js/modules/plan.js').then(m => m.initSubPanel()).catch(() => {});
  render.appendUserMsg(question);
  historyMod.pushMessage({ role: 'user', content: question });
  await _runReact(question);
}

// ── ReAct streaming ───────────────────────────────────────────────────────────

async function _runReact(question) {
  if (!S.reactReady) { showToast('ReAct not initialized'); return; }

  const genId = crypto.randomUUID();
  set('genId', genId);
  setState('streaming');

  const ctrl         = render.appendReactMsg();
  let   _stepI       = -1;
  const _stepHistory = [];

  const session = new streaming.ReactSession(question, genId, {
    onPromptPreview: msgs  => ctrl.showPrompt(msgs),
    onStepStart:     i     => { _stepI = i; ctrl.showActivity(`Step ${i + 1}…`); },
    onChunk:         (i, chunk) => ctrl.appendChunk(i, chunk),
    onStep:          step  => { ctrl.addStep(step); _stepHistory.push(step); },
    onRetry:         (i, reason) => showToast(`Retry ${i}: ${reason}`),
    onApprovalRequest: (reqId, tool, args) => _promptApproval(session, reqId, tool, args),
    onSubStart:  (action, instr) => ctrl.openSubAgent(action, instr),
    onSubChunk:  (i, chunk)      => ctrl.addSubChunk(i, chunk),
    onSubStep:   step            => ctrl.addSubStep(step),
    onSubFinish: answer          => ctrl.closeSubAgent(answer, false),
    onSubError:  error           => ctrl.closeSubAgent(error, true),
    onMaxSteps: n => showToast(`⚠ 已达最大步数限制（${n} 步）`),
    onFinish:   (answer, aborted) => {
      ctrl.finalize(answer, aborted);
      if (!aborted && answer) {
        historyMod.pushMessage({ role: 'assistant', content: answer, steps: _stepHistory });
        historyMod.saveConversation();
        _updateTitle(answer);
      }
      streaming.clearCurrent();
      setState('idle');
    },
    onError: e => {
      showToast('ReAct error: ' + e.message);
      ctrl.finalize('', true);
      streaming.clearCurrent();
      setState('idle');
    },
  });
  streaming.startSession(session);
  session.run().catch(e => {
    showToast('Connection error: ' + e.message);
    streaming.clearCurrent();
    setState('idle');
  });
}

function _promptApproval(session, reqId, tool, args) {
  const ok = confirm(`Allow tool "${tool}"?\n\n${JSON.stringify(args, null, 2)}`);
  session.respond(reqId, ok);
}

// ── History rebuild ───────────────────────────────────────────────────────────

export function rebuildFromHistory(messages) {
  render.clearMsgs();
  messages.forEach(m => {
    if (m.role === 'user') {
      render.appendUserMsg(m.content);
    } else if (m.role === 'assistant') {
      if (m.steps?.length) {
        const ctrl = render.appendReactMsg();
        m.steps.forEach(step => ctrl.addStep(step));
        ctrl.finalize(m.content, false);
      } else {
        const ctrl = render.appendAssistantMsg();
        ctrl.append(m.content);
        ctrl.finalize(false);
      }
    }
  });
  render.scrollBottom();
  goWorkspace();
  historyMod.renderSidebar();
  import('/static/js/modules/plan.js').then(m => m.initSubPanel()).catch(() => {});
}

// ── Title update ──────────────────────────────────────────────────────────────

function _updateTitle(answerOrQuestion) {
  if (S.convTitle && S.convTitle !== 'New Conversation') return;
  const msgs  = historyMod.getMessages();
  const first = msgs.find(m => m.role === 'user');
  if (!first) return;
  const title = first.content.slice(0, 48) + (first.content.length > 48 ? '…' : '');
  set('convTitle', title);
  const tb = document.getElementById('tb-title');
  if (tb) tb.textContent = title;
}

// ── Mic recording ─────────────────────────────────────────────────────────────

export async function handleMicClick() {
  if (!_voiceMod) return;
  const btn = document.getElementById('btn-mic');
  if (_voiceMod.isRecording()) {
    btn?.classList.remove('recording');
    const text = await _voiceMod.stopRecordingAndTranscribe();
    if (text) {
      const inp = document.getElementById('msg-input');
      if (inp) inp.value = (inp.value + ' ' + text).trim();
    }
  } else {
    await _voiceMod.startRecording().catch(e => showToast('Mic error: ' + e.message));
    btn?.classList.add('recording');
  }
}

// ── TTS delegation ────────────────────────────────────────────────────────────

/** Call once from app.js to attach the global TTS click handler. */
export function initTTSHandler() {
  document.addEventListener('click', async e => {
    const btn = e.target.closest('.msg-tts-btn');
    if (!btn || !_voiceMod) return;
    const text = btn.dataset.text;
    if (!text) return;
    if (_voiceMod.isSpeaking()) {
      _voiceMod.stopSpeaking();
      btn.classList.remove('playing');
      return;
    }
    btn.classList.add('playing');
    await _voiceMod.speak(text);
    btn.classList.remove('playing');
  });
}

// ── Knowledge-base panel ──────────────────────────────────────────────────────

export function openKBPanel() {
  const panel = document.getElementById('kb-panel');
  if (!panel) return;
  panel.classList.toggle('hidden');
  if (!panel.classList.contains('hidden') && _knowledgeMod) {
    _knowledgeMod.renderPanel(document.getElementById('kb-docs-list'));
  }
}

// ── Lifecycle listeners ───────────────────────────────────────────────────────

/** Wire react:state window events → send button UI. */
export function initLifecycleListeners() {
  window.addEventListener('react:state', e => {
    const { to } = e.detail;
    const sendBtn = document.getElementById('btn-send');
    const inputEl = document.getElementById('msg-input');
    const busy    = to === 'streaming' || to === 'aborting' || to === 'initializing';
    if (sendBtn) { sendBtn.textContent = busy ? '⊘' : '↑'; sendBtn.title = busy ? 'Abort' : 'Send'; }
    if (inputEl)   inputEl.disabled = busy;
  });
}
