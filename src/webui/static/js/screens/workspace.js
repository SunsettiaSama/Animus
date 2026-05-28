/**
 * screens/workspace.js — Chat workspace screen logic.
 *
 * Main conversation uses Soul Speak streaming (/ws/speak/run).
 * ReAct/Tao WS is no longer used for workspace chat.
 */

import { S, setState, set }    from '../state.js';
import * as render              from '../render.js';
import * as historyMod          from '../history.js';
import * as streaming           from '../streaming.js';
import * as speakMod            from '../modules/speak.js';
import { goWorkspace }         from '../router.js';
import { showToast }           from '../shared/toast.js';

let _voiceMod     = null;
let _knowledgeMod = null;

export function registerModules({ voiceMod, knowledgeMod }) {
  _voiceMod     = voiceMod;
  _knowledgeMod = knowledgeMod;
}

// ── New conversation ──────────────────────────────────────────────────────────

export async function startNew() {
  streaming.abortCurrent();
  await speakMod.resetSession().catch(() => {});
  set('convId', null);
  set('convTitle', 'New Conversation');
  set('convMode', 'speak');
  historyMod.clearMessages();
  render.clearMsgs();
  render.showEmptyState('speak');
  const tb = document.getElementById('tb-title');
  if (tb) tb.textContent = 'New Conversation';
  _updateStatusBadge();
  goWorkspace();
  historyMod.renderSidebar();
  import('/static/js/modules/plan.js').then(m => m.initSubPanel()).catch(() => {});
}

// ── Topbar badge ──────────────────────────────────────────────────────────────

export function updateReactBadge() { _updateStatusBadge(); }

function _updateStatusBadge() {
  const el = document.getElementById('tb-react-status');
  if (!el) return;
  if (S.speakReady) {
    el.textContent = '💬 Speak Ready';
    el.style.color = 'var(--accent)';
  } else if (S.soulReady) {
    el.textContent = '✨ Soul Running';
    el.style.color = 'var(--accent)';
  } else {
    el.textContent = '💬 Not ready';
    el.style.color = 'var(--text3)';
  }
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
  await _runSpeak(question);
}

// ── Soul Speak streaming ──────────────────────────────────────────────────────

async function _runSpeak(question) {
  if (!S.speakReady) {
    showToast('Soul Speak 未就绪');
    return;
  }

  const genId = crypto.randomUUID();
  set('genId', genId);
  setState('streaming');

  const streamCtrl = render.appendSpeakStream();

  const session = new streaming.SpeakSession(question, genId, {
    onEvent: (kind, text, meta) => streamCtrl?.onEvent(kind, text, meta),
    onFinish: payload => {
      const answer = payload.answer ?? streamCtrl?.speakText ?? '';
      const aborted = Boolean(payload.aborted);
      streamCtrl?.finalize(answer, aborted);

      if (!aborted && answer) {
        historyMod.pushMessage({
          role: 'assistant',
          content: answer,
          speak_events: streamCtrl?.events ?? [],
        });
        historyMod.saveConversation();
        _updateTitle(answer);
      }
      streaming.clearCurrent();
      setState('idle');
    },
    onError: e => {
      showToast('Speak error: ' + e.message);
      streamCtrl?.finalize('', true);
      streaming.clearCurrent();
      setState('idle');
    },
  });

  streaming.startSession(session);
  session.run().catch(e => {
    showToast('Connection error: ' + e.message);
    streamCtrl?.finalize('', true);
    streaming.clearCurrent();
    setState('idle');
  });
}

// ── History rebuild ───────────────────────────────────────────────────────────

export function rebuildFromHistory(messages) {
  render.clearMsgs();
  messages.forEach(m => {
    if (m.role === 'user') {
      render.appendUserMsg(m.content);
    } else if (m.role === 'assistant') {
      if (m.speak_events?.length) {
        const ctrl = render.appendSpeakStream();
        m.speak_events.forEach(ev => {
          ctrl.onEvent(ev.kind, ev.text ?? '', ev.meta ?? {});
        });
        ctrl.finalize(m.content, false);
      } else {
        const ctrl = render.appendAssistantMsg();
        ctrl.append(m.content);
        ctrl.finalize();
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
