/**
 * screens/workspace.js — 单一 Speak 会话窗口（无历史/多会话）。
 */

import { S, setState, set }    from '../state.js';
import * as render              from '../render.js';
import * as streaming           from '../streaming.js';
import * as speakMod            from '../modules/speak.js';
import { getChannelId }         from '../channel.js';
import { goWorkspace }         from '../router.js';
import { showToast }           from '../shared/toast.js';

let _voiceMod     = null;
let _knowledgeMod = null;
let _speakSession = null;
let _messages     = [];

export function registerModules({ voiceMod, knowledgeMod }) {
  _voiceMod     = voiceMod;
  _knowledgeMod = knowledgeMod;
}

function _closeSpeakSession() {
  if (_speakSession) {
    _speakSession.close();
    _speakSession = null;
  }
  streaming.clearCurrent();
}

function _finishTurn(streamCtrl, payload) {
  const answer = payload.answer ?? streamCtrl?.speakText ?? '';
  const aborted = Boolean(payload.aborted);
  streamCtrl?.finalize(answer, aborted);

  if (!aborted && answer) {
    _messages.push({
      role: 'assistant',
      content: answer,
      speak_events: streamCtrl?.events ?? [],
    });
  }
  setState('idle');
  _syncSendButton();
}

function _bindTurnCallbacks(session, streamCtrl) {
  session.setTurnCallbacks({
    onEvent: (kind, text, meta) => streamCtrl?.onEvent(kind, text, meta),
    onUserAck: msg => {
      if (msg.interrupt) showToast('已插队，Agent 将转向新消息');
      else if (msg.queued) showToast('消息已排队');
    },
    onTurnFinish: payload => _finishTurn(streamCtrl, payload),
    onError: e => {
      showToast('Speak error: ' + e.message);
      streamCtrl?.finalize('', true);
      _closeSpeakSession();
      setState('idle');
      _syncSendButton();
    },
  });
}

export async function startNew() {
  streaming.abortCurrent();
  _closeSpeakSession();
  const channelId = getChannelId();
  await speakMod.resetSession(channelId).catch(() => {});
  _messages = [];
  render.clearMsgs();
  render.showEmptyState('speak');
  const tb = document.getElementById('tb-title');
  if (tb) tb.textContent = '对话';
  _updateStatusBadge();
  goWorkspace();
  import('/static/js/modules/plan.js').then(m => m.initSubPanel()).catch(() => {});
}

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

export async function handleSend() {
  const inputEl  = document.getElementById('msg-input');
  const question = inputEl?.value.trim() ?? '';

  if (S.lifecycle === 'streaming' || S.lifecycle === 'aborting') {
    if (!question) {
      streaming.abortCurrent();
      _closeSpeakSession();
      setState('idle');
      _syncSendButton();
      return;
    }
    const session = _speakSession || streaming.getCurrent();
    if (session?.sendUserMessage(question)) {
      if (inputEl) inputEl.value = '';
      goWorkspace();
      render.appendUserMsg(question);
      _messages.push({ role: 'user', content: question });
      showToast('已发送，Agent 回复中可继续输入');
      return;
    }
    streaming.abortCurrent();
    _closeSpeakSession();
    setState('idle');
    _syncSendButton();
    return;
  }

  if (!question) return;
  if (inputEl) inputEl.value = '';

  goWorkspace();
  import('/static/js/modules/plan.js').then(m => m.initSubPanel()).catch(() => {});
  render.appendUserMsg(question);
  _messages.push({ role: 'user', content: question });

  if (_speakSession?.isConnected()) {
    await _continueSpeakTurn(question);
    return;
  }
  await _runSpeak(question);
}

async function _continueSpeakTurn(question) {
  if (!_speakSession?.isConnected()) {
    await _runSpeak(question);
    return;
  }

  setState('streaming');
  const streamCtrl = render.appendSpeakStream();
  _bindTurnCallbacks(_speakSession, streamCtrl);
  await _speakSession.sendTurn(question);
}

async function _runSpeak(question) {
  if (!S.speakReady) {
    showToast('Soul Speak 未就绪');
    return;
  }

  _closeSpeakSession();

  const genId = crypto.randomUUID();
  const channelId = getChannelId();
  set('genId', genId);
  set('channelId', channelId);
  setState('streaming');

  const streamCtrl = render.appendSpeakStream();

  const session = new streaming.SpeakSession(genId, {
    sessionId: channelId,
    onEvent: (kind, text, meta) => streamCtrl?.onEvent(kind, text, meta),
    onUserAck: msg => {
      if (msg.interrupt) showToast('已插队，Agent 将转向新消息');
      else if (msg.queued) showToast('消息已排队');
    },
    onTurnFinish: payload => _finishTurn(streamCtrl, payload),
    onError: e => {
      showToast('Speak error: ' + e.message);
      streamCtrl?.finalize('', true);
      _closeSpeakSession();
      setState('idle');
      _syncSendButton();
    },
  });

  _speakSession = session;
  streaming.startSession(session);

  const result = await session.run(question);
  if (result?.type === 'session_end') {
    _speakSession = null;
  }
}

function _syncSendButton() {
  const sendBtn = document.getElementById('btn-send');
  const busy = S.lifecycle === 'streaming' || S.lifecycle === 'aborting';
  if (!sendBtn) return;
  sendBtn.textContent = '↑';
  sendBtn.title = busy
    ? '发送（Agent 回复中可继续输入）；空内容点击为中止'
    : '发送';
}

export function rebuildFromHistory(messages) {
  _messages = Array.isArray(messages) ? [...messages] : [];
  render.clearMsgs();
  _messages.forEach(m => {
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
  import('/static/js/modules/plan.js').then(m => m.initSubPanel()).catch(() => {});
}

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

export function openKBPanel() {
  const panel = document.getElementById('kb-panel');
  if (!panel) return;
  panel.classList.toggle('hidden');
  if (!panel.classList.contains('hidden') && _knowledgeMod) {
    _knowledgeMod.renderPanel(document.getElementById('kb-docs-list'));
  }
}

export function initLifecycleListeners() {
  window.addEventListener('react:state', () => {
    _syncSendButton();
    const inputEl = document.getElementById('msg-input');
    if (inputEl) inputEl.disabled = false;
  });
}
