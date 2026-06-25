/**
 * screens/workspace.js — Speak 工作区 + 前端 history 多会话（类微信/FB）。
 *
 * history：展示与持久化消息列表
 * sessionId：后端 Speak 上下文（与 convId 一一对应，存于历史 JSON）
 * channelId：记忆渠道（localStorage，多线程共享）
 */

import { S, setState, set }    from '../state.js';
import * as speakMod            from '../modules/speak.js';
import * as render              from '../render.js';
import * as streaming           from '../streaming.js';
import * as history             from '../history.js';
import { getChannelId }         from '../channel.js';
import { getSpeakDeliveryMode, isSimulatedDelivery } from '../speak_delivery.js';
import { getSpeakPipeline }     from '../speak_pipeline.js';
import { goWorkspace }         from '../router.js';
import { showToast }           from '../shared/toast.js';

let _voiceMod     = null;
let _knowledgeMod = null;
let _speakSession = null;

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

function _speakStreamOpts() {
  return { deliveryMode: getSpeakDeliveryMode(), pipeline: getSpeakPipeline() };
}

function _msgDraft() {
  return document.getElementById('msg-input')?.value ?? '';
}

function _speakSessionOpts(genId, streamCtrl) {
  return {
    sessionId: S.sessionId || S.convId || getChannelId(),
    channelId: S.channelId || getChannelId(),
    deliveryMode: getSpeakDeliveryMode(),
    pipeline: getSpeakPipeline(),
    typingIdleMs: 3000,
    getDraft: _msgDraft,
    onEvent: (kind, text, meta) => streamCtrl?.onEvent(kind, text, meta),
    onTurnStart: () => {
      if (isSimulatedDelivery()) render.showSpeakTurnTyping();
    },
    onUserAck: msg => {
      if (msg.interrupt) showToast('已插队，Agent 将转向新消息');
      else if (msg.queued) showToast('消息已排队');
    },
    onTurnFinish: payload => _finishTurn(streamCtrl, payload),
    onError: e => {
      showToast('Speak error: ' + e.message);
      streamCtrl?.finalize('', true);
      render.setTitleBarTyping(false);
      _closeSpeakSession();
      setState('idle');
      _syncSendButton();
    },
  };
}

async function _finishTurn(streamCtrl, payload) {
  const aborted = Boolean(payload.aborted);
  if (payload.hide_agent || payload.silence_policy === 'hidden') {
    streamCtrl?.discardAgentTurn?.();
    render.setTitleBarTyping(false);
    setState('idle');
    _syncSendButton();
    return;
  }
  const answer = payload.answer ?? streamCtrl?.speakText ?? '';
  await streamCtrl?.finalize(answer, aborted);

  if (!aborted && answer) {
    history.pushMessage({
      role: 'assistant',
      content: answer,
      speak_events: streamCtrl?.events ?? [],
    });
    history.saveConversation().catch(() => {});
    render.setTitleBarTyping(false);
    const tb = document.getElementById('tb-title');
    if (tb && S.convTitle) tb.textContent = S.convTitle;
  }
  setState('idle');
  _syncSendButton();
}

function _bindTurnCallbacks(session, streamCtrl) {
  session.setDeliveryMode(getSpeakDeliveryMode());
  session.setPipeline(getSpeakPipeline());
  session.setTurnCallbacks({
    onEvent: (kind, text, meta) => streamCtrl?.onEvent(kind, text, meta),
    onTurnStart: () => {
      if (isSimulatedDelivery()) render.showSpeakTurnTyping();
    },
    onUserAck: msg => {
      if (msg.interrupt) showToast('已插队，Agent 将转向新消息');
      else if (msg.queued) showToast('消息已排队');
    },
    onTurnFinish: payload => _finishTurn(streamCtrl, payload),
    onError: e => {
      showToast('Speak error: ' + e.message);
      streamCtrl?.finalize('', true);
      render.setTitleBarTyping(false);
      _closeSpeakSession();
      setState('idle');
      _syncSendButton();
    },
  });
}

function _syncProactiveUrgeDot() {
  const dot = document.getElementById('tb-proactive-dot');
  if (!dot) return;
  const active = Boolean(S.proactiveUrge || S.proactiveUnread);
  dot.classList.toggle('active', active);
}

export function setSidebarCollapsed(collapsed) {
  const sidebar = document.getElementById('sidebar');
  const toggleBtn = document.getElementById('btn-sidebar-toggle');
  if (!sidebar) return;
  sidebar.classList.toggle('collapsed', collapsed);
  if (toggleBtn) {
    toggleBtn.textContent = collapsed ? '▶' : '◀';
    toggleBtn.title = collapsed ? '展开侧栏' : '收起侧栏';
  }
}

export function toggleSidebar(forceOpen) {
  const sidebar = document.getElementById('sidebar');
  if (!sidebar) return;
  if (forceOpen === true) {
    setSidebarCollapsed(false);
    return;
  }
  setSidebarCollapsed(!sidebar.classList.contains('collapsed'));
}

export async function openProactiveSession(payload) {
  const message = String(payload?.message ?? '').trim();
  const sessionId = String(payload?.session_id ?? '').trim();
  if (!message || !sessionId) return;

  prepareConversationSwitch();
  const ids = history.newIds();
  const banner = String(payload?.banner ?? '').trim()
    || `【${payload?.agent_display_name ?? 'Agent'}发来一条通信】°`;
  const title = banner.replace(/°$/, '').trim() || 'Agent 主动通信';

  set('convId', ids.convId);
  set('sessionId', sessionId);
  set('channelId', String(payload?.channel_id ?? ids.channelId));
  set('convTitle', title);
  set('proactiveUrge', true);
  set('proactiveUnread', true);
  set('_createdAt', new Date().toISOString());
  history.clearMessages();

  goWorkspace();
  toggleSidebar(true);
  render.clearMsgs();
  render.appendProactiveBanner(banner, {
    agentDisplayName: payload?.agent_display_name ?? '',
    proactiveIntentId: payload?.proactive_intent_id ?? '',
  });
  const ctrl = render.appendAssistantMsg();
  ctrl.append(message);
  ctrl.finalize();
  history.pushMessage({
    role: 'assistant',
    content: message,
    agent_initiated: true,
    proactive_intent_id: payload?.proactive_intent_id ?? '',
  });
  await history.saveConversation({ agentInitiated: true, proactiveUnread: true });
  await history.renderSidebar();
  await history.renderRecentLanding(document.getElementById('landing-recent'));
  const tb = document.getElementById('tb-title');
  if (tb) tb.textContent = title;
  _syncProactiveUrgeDot();
  _closeSpeakSession();
  showToast('Agent 发来一条通信');
}

export async function startNew() {
  streaming.abortCurrent();
  _closeSpeakSession();
  set('proactiveUrge', false);
  set('proactiveUnread', false);
  _syncProactiveUrgeDot();
  await history.beginNewConversation({ resetBackend: true });
  render.clearMsgs();
  render.showEmptyState('speak');
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
      history.pushMessage({ role: 'user', content: question });
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

  if (S.proactiveUrge || S.proactiveUnread) {
    set('proactiveUrge', false);
    set('proactiveUnread', false);
    _syncProactiveUrgeDot();
  }

  history.ensureActiveConversation();
  _syncTraceButton().catch(() => {});
  goWorkspace();
  import('/static/js/modules/plan.js').then(m => m.initSubPanel()).catch(() => {});
  render.appendUserMsg(question);
  history.pushMessage({ role: 'user', content: question });
  await history.saveConversation({ clearProactiveUnread: true }).catch(() => {});

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
  const streamCtrl = render.appendSpeakStream(_speakStreamOpts());
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
  set('genId', genId);
  setState('streaming');

  const streamCtrl = render.appendSpeakStream(_speakStreamOpts());
  const session = new streaming.SpeakSession(genId, _speakSessionOpts(genId, streamCtrl));

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
  history.setMessages(messages);
  render.clearMsgs();
  _syncProactiveUrgeDot();
  const msgs = history.getMessages();
  if (!msgs.length) {
    render.showEmptyState('speak');
  }
  if (S.proactiveUrge) {
    const title = (S.convTitle || '').replace(/°$/, '').trim();
    render.appendProactiveBanner(title.includes('发来') ? `${title}°` : `【${title}】°`);
  }
  msgs.forEach(m => {
    if (m.role === 'user') {
      render.appendUserMsg(m.content);
    } else if (m.role === 'assistant') {
      if (m.speak_events?.length) {
        const ctrl = render.appendSpeakStream({ deliveryMode: 'stream' });
        m.speak_events.forEach(ev => {
          ctrl.onEvent(ev.kind, ev.text ?? '', ev.meta ?? {});
        });
        void ctrl.finalize(m.content, false);
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

export function prepareConversationSwitch() {
  streaming.abortCurrent();
  _closeSpeakSession();
}

export async function openConversation(convId) {
  prepareConversationSwitch();
  await history.loadConversation(convId);
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

let _traceEnabled = false;

async function _syncTraceButton() {
  const btn = document.getElementById('btn-speak-trace');
  const sid = S.sessionId;
  if (!btn || !sid) {
    if (btn) btn.classList.remove('active');
    return;
  }
  const data = await speakMod.getSessionTrace(sid).catch(() => ({ enabled: false }));
  _traceEnabled = Boolean(data.enabled);
  btn.classList.toggle('active', _traceEnabled);
  btn.title = _traceEnabled
    ? '已开启：下一轮起主进程打印提示词（点按关闭）'
    : '主进程打印本 session 提示词与记忆缓存（点按开启）';
}

export function initSpeakDeliverySync() {
  window.addEventListener('speak:delivery_mode', e => {
    if (_speakSession?.isConnected?.()) {
      _speakSession.setDeliveryMode(e.detail);
    }
  });
  window.addEventListener('speak:pipeline', e => {
    if (_speakSession?.isConnected?.()) {
      _speakSession.setPipeline(e.detail);
    }
  });
}

export function initSidebar() {
  document.getElementById('btn-new-chat')?.addEventListener('click', () => {
    startNew();
  });
  document.getElementById('btn-sidebar-open')?.addEventListener('click', () => {
    toggleSidebar(true);
  });
  document.getElementById('btn-sidebar-toggle')?.addEventListener('click', () => {
    toggleSidebar();
  });
  document.getElementById('btn-speak-trace')?.addEventListener('click', async () => {
    const sid = S.sessionId;
    if (!sid) {
      showToast('请先发送一条消息以建立 session');
      return;
    }
    const next = !_traceEnabled;
    await speakMod.setSessionTrace(sid, next);
    _traceEnabled = next;
    await _syncTraceButton();
    showToast(next ? '已开启 Speak 提示词追踪（见运行 Soul 的终端）' : '已关闭 Speak 提示词追踪');
    if (next) {
      const dbg = await speakMod.fetchSessionDebug(sid).catch(() => null);
      if (dbg) {
        console.info('[speak debug] 本地缓存', dbg.cache);
        console.info('[speak debug] 说明', dbg.module_trace_hint);
      }
    }
  });
  window.addEventListener('react:update', e => {
    if (e.detail?.key === 'sessionId') _syncTraceButton();
  });
  _syncTraceButton();
  _syncProactiveUrgeDot();
}
