/**
 * screens/workspace.js — Speak 工作区 + 前端 history 多会话。
 *
 * history：展示与持久化消息列表（convId）
 * sessionId：Speak 生命线（live:channelId），切页不重建内在态
 * channelId：记忆渠道（多线程共享）
 */

import { S, setState, set }    from '../state.js';
import * as speakMod            from '../modules/speak.js';
import * as render              from '../render.js';
import * as streaming           from '../streaming.js';
import * as history             from '../history.js';
import { channelIdFromLiveSession, getChannelId, isLiveSessionId, speakLiveSessionId } from '../channel.js';
import { getSpeakDeliveryMode } from '../speak_delivery.js';
import { getSpeakResponder }     from '../speak_responder.js';
import { sortEventsByOrder }   from '../speak_render_protocol.js';
import { goWorkspace }         from '../router.js';
import { showToast }           from '../shared/toast.js';
import * as workUi              from '../work/ui.js';
import * as workStore           from '../work/store.js';

let _voiceMod     = null;
let _knowledgeMod = null;
let _speakSession = null;
let _connectPromise = null;
/** 关闭会话时递增；进行中的 connect 据此丢弃，避免 startNew 抢到旧 Promise 后连不上。 */
let _connectEpoch = 0;

export function registerModules({ voiceMod, knowledgeMod }) {
  _voiceMod     = voiceMod;
  _knowledgeMod = knowledgeMod;
}

function _closeSpeakSession() {
  _connectEpoch += 1;
  if (_speakSession) {
    _speakSession.close();
    _speakSession = null;
  }
  streaming.clearCurrent();
}

function _speakStreamOpts() {
  return {
    deliveryMode: getSpeakDeliveryMode(),
    pipeline: getSpeakResponder(),
    onSlotReplace: (slot, text, meta) => _patchHistoryOutlineSlot(slot, text, meta),
  };
}

function _msgDraft() {
  return document.getElementById('msg-input')?.value ?? '';
}

function _sendWorkFrame(payload) {
  const session = _speakSession || streaming.getCurrent();
  if (session?.sendWorkFrame?.(payload)) return true;
  showToast('会话未连接，无法发送任务指令');
  return false;
}

let _fallbackStreamCtrl = null;
let _lastSpeakCtrl = null;

function _isOutlineUpgrade(kind, meta = {}) {
  return (
    kind === 'outline'
    && Boolean(meta?.upgrade || meta?.replace)
    && String(meta?.slot || '').trim()
  );
}

function _routeSpeakEvent(kind, text, meta, holder) {
  const upgrade = _isOutlineUpgrade(kind, meta);
  let ctrl = holder.ctrl;
  if (ctrl && !ctrl._finalized) {
    if (S.lifecycle === 'idle') setState('streaming');
    ctrl.onEvent(kind, text, meta);
    return;
  }
  if (upgrade && _lastSpeakCtrl) {
    _lastSpeakCtrl.onEvent(kind, text, meta);
    return;
  }
  if (upgrade && render.replaceOutlineSlot(String(meta.slot || '').trim(), text, meta)) {
    _patchHistoryOutlineSlot(meta.slot, text, meta);
    return;
  }
  ctrl = _ensureFallbackStreamCtrl();
  holder.ctrl = ctrl;
  _lastSpeakCtrl = ctrl;
  if (S.lifecycle === 'idle') setState('streaming');
  ctrl.onEvent(kind, text, meta);
}

function _patchHistoryOutlineSlot(slot, text, meta = {}) {
  const key = String(slot || '').trim();
  const body = String(text ?? '').trim();
  if (!key || !body) return;
  const msgs = history.getMessages();
  for (let i = msgs.length - 1; i >= 0; i -= 1) {
    const msg = msgs[i];
    if (msg?.role !== 'assistant') continue;
    const events = Array.isArray(msg.speak_events) ? [...msg.speak_events] : [];
    let hit = false;
    for (let j = events.length - 1; j >= 0; j -= 1) {
      const ev = events[j];
      if (String(ev?.meta?.slot || '').trim() !== key) continue;
      events[j] = {
        ...ev,
        text: body,
        meta: { ...ev.meta, ...meta, slot: key, upgrade: true, replace: true, placeholder: false },
      };
      hit = true;
      break;
    }
    if (!hit) continue;
    msgs[i] = { ...msg, speak_events: events, content: msg.content || body };
    history.setMessages(msgs);
    history.saveConversation().catch(() => {});
    return;
  }
}

function _ensureFallbackStreamCtrl() {
  if (_fallbackStreamCtrl) return _fallbackStreamCtrl;
  _fallbackStreamCtrl = render.appendSpeakStream(_speakStreamOpts());
  return _fallbackStreamCtrl;
}

function _onWorkEvent(msg) {
  workUi.handleWorkEvent(msg);
  if (msg.type === 'work_declined' && msg.reason) {
    showToast(msg.reason);
  }
  if (msg.type === 'work_failed' && (msg.reason || msg.message)) {
    showToast(msg.reason || msg.message);
  }
  if (['work_started', 'work_progress', 'work_finished', 'work_failed', 'work_aborted', 'work_declined'].includes(msg.type)) {
    history.saveConversation().catch(() => {});
  }
  if (msg.type === 'work_confirmation_required' || msg.type === 'work_started') {
    if (S.lifecycle === 'streaming' || S.lifecycle === 'aborting') {
      setState('idle');
    }
    render.setTitleBarTyping(false);
  }
  _syncSendButton();
}

function _speakSessionOpts(genId, streamCtrl) {
  // Mutable holder so fallback Speak after work confirm can swap the stream ctrl.
  const holder = { ctrl: streamCtrl, meta: {}, session: null };
  const liveId = speakLiveSessionId(S.channelId || getChannelId());
  if (S.sessionId !== liveId) set('sessionId', liveId);
  return {
    sessionId: liveId,
    channelId: S.channelId || getChannelId(),
    deliveryMode: getSpeakDeliveryMode(),
    pipeline: getSpeakResponder(),
    typingIdleMs: 3000,
    getDraft: _msgDraft,
    onEvent: (kind, text, meta) => {
      if (meta?.agent_initiated || meta?.proactive_intent_id) {
        holder.meta = { ...holder.meta, ...meta };
      }
      _routeSpeakEvent(kind, text, meta, holder);
    },
    onWorkEvent: _onWorkEvent,
    onTurnStart: payload => {
      holder.meta = { ...payload };
      if (!holder.ctrl || holder.ctrl._finalized) {
        holder.ctrl = _ensureFallbackStreamCtrl();
      }
      _lastSpeakCtrl = holder.ctrl || _lastSpeakCtrl;
      const stamp = String(payload?.created_at ?? '').trim();
      if (stamp) holder.ctrl?.setCreatedAt?.(stamp);
      if (S.lifecycle === 'idle') setState('streaming');
    },
    onUserAck: msg => {
      if (msg.interrupt) showToast('已插队，Agent 将转向新消息');
      else if (msg.queued) showToast('消息已排队');
    },
    onTurnFinish: payload => {
      const ctrl = holder.ctrl || _fallbackStreamCtrl;
      _lastSpeakCtrl = ctrl || _lastSpeakCtrl;
      const metadata = { ...holder.meta, ...payload };
      _finishTurn(ctrl, payload, metadata).then(() => {
        holder.session?.acknowledgeProactive(metadata.delivery_id);
      });
      holder.ctrl = null;
      holder.meta = {};
      _fallbackStreamCtrl = null;
    },
    onError: e => {
      showToast('Speak error: ' + e.message);
      const ctrl = holder.ctrl || _fallbackStreamCtrl;
      ctrl?.finalize?.('', true);
      render.setTitleBarTyping(false);
      _closeSpeakSession();
      setState('idle');
      _syncSendButton();
    },
    _holder: holder,
  };
}

async function _finishTurn(streamCtrl, payload, turnMeta = {}) {
  const aborted = Boolean(payload.aborted);
  if (payload.hide_agent || payload.silence_policy === 'hidden') {
    streamCtrl?.discardAgentTurn?.();
    render.setTitleBarTyping(false);
    setState('idle');
    _syncSendButton();
    return;
  }
  const answer = payload.answer ?? streamCtrl?.speakText ?? '';
  const createdAt = String(
    payload.created_at
    || turnMeta.created_at
    || streamCtrl?.createdAt
    || ''
  ).trim();
  if (createdAt) streamCtrl?.setCreatedAt?.(createdAt);
  const replay = streamCtrl?.hasLiveInput ? null : (payload.speak_events ?? null);
  await streamCtrl?.finalize(answer, aborted, replay);

  const events = streamCtrl?.events ?? [];
  const hasOutline = events.some(
    (ev) => ev?.kind === 'outline' || ev?.meta?.field === 'outline',
  );
  if (!aborted && (answer || hasOutline)) {
    const metadata = { ...turnMeta, ...payload };
    const proactiveId = String(metadata.proactive_intent_id ?? '').trim();
    const duplicate = proactiveId && history.getMessages().some(
      message => message.proactive_intent_id === proactiveId,
    );
    if (!duplicate) {
      history.pushMessage({
        role: 'assistant',
        content: answer || String(events.find((ev) => ev?.kind === 'outline')?.text || ''),
        speak_events: events,
        created_at: createdAt || metadata.created_at,
        agent_initiated: Boolean(metadata.agent_initiated),
        proactive_intent_id: proactiveId,
        proactive: metadata.proactive ?? (
          metadata.agent_initiated
            ? {
                source: metadata.source ?? '',
                wait_reply: metadata.wait_reply,
                agent_display_name: metadata.agent_display_name ?? '',
              }
            : undefined
        ),
      });
    }
    await history.saveConversation({
      agentInitiated: Boolean(metadata.agent_initiated),
      proactiveUnread: Boolean(metadata.agent_initiated),
    });
    render.setTitleBarTyping(false);
    const tb = document.getElementById('tb-title');
    if (tb && S.convTitle) tb.textContent = S.convTitle;
  }
  setState('idle');
  _syncSendButton();
}

function _bindTurnCallbacks(session, streamCtrl) {
  let activeCtrl = streamCtrl;
  let turnMeta = {};
  session.setDeliveryMode(getSpeakDeliveryMode());
  session.setPipeline(getSpeakResponder());
  session.setTurnCallbacks({
    onEvent: (kind, text, meta) => {
      if (meta?.agent_initiated || meta?.proactive_intent_id) {
        turnMeta = { ...turnMeta, ...meta };
      }
      const holder = { ctrl: activeCtrl };
      _routeSpeakEvent(kind, text, meta, holder);
      activeCtrl = holder.ctrl || activeCtrl;
    },
    onWorkEvent: _onWorkEvent,
    onTurnStart: payload => {
      turnMeta = { ...payload };
      if (!activeCtrl || activeCtrl._finalized) {
        activeCtrl = _ensureFallbackStreamCtrl();
      }
      _lastSpeakCtrl = activeCtrl || _lastSpeakCtrl;
      const stamp = String(payload?.created_at ?? '').trim();
      if (stamp) activeCtrl?.setCreatedAt?.(stamp);
      if (S.lifecycle === 'idle') setState('streaming');
    },
    onUserAck: msg => {
      if (msg.interrupt) showToast('已插队，Agent 将转向新消息');
      else if (msg.queued) showToast('消息已排队');
    },
    onTurnFinish: payload => {
      _lastSpeakCtrl = activeCtrl || _lastSpeakCtrl;
      const metadata = { ...turnMeta, ...payload };
      _finishTurn(activeCtrl, payload, metadata).then(() => {
        session.acknowledgeProactive(metadata.delivery_id);
      });
      activeCtrl = null;
      turnMeta = {};
      _fallbackStreamCtrl = null;
    },
    onError: e => {
      showToast('Speak error: ' + e.message);
      (activeCtrl || streamCtrl)?.finalize?.('', true);
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

export async function connectSpeakSession() {
  if (!S.speakReady || !S.sessionId) return null;
  const epoch = _connectEpoch;

  // 等旧 connect 落定；若期间被 close/startNew 抬升 epoch，则放弃，由调用方重试。
  if (_connectPromise) {
    const existing = await _connectPromise.catch(() => null);
    if (epoch !== _connectEpoch) return null;
    if (existing?.sessionId === S.sessionId && existing.isConnected()) return existing;
  }
  if (_connectPromise) return _connectPromise;
  if (epoch !== _connectEpoch) return null;

  _connectPromise = (async () => {
    if (epoch !== _connectEpoch) return null;

    if (_speakSession?.sessionId === S.sessionId) {
      if (_speakSession.isConnected()) return _speakSession;
      await _speakSession.connect();
      if (epoch !== _connectEpoch || _speakSession?.sessionId !== S.sessionId) return null;
      return _speakSession;
    }

    // 换 session 时只拆旧连接，不抬升 epoch（否则会把自己刚开的连接判废）
    if (_speakSession) {
      _speakSession.close();
      _speakSession = null;
      streaming.clearCurrent();
    }

    const genId = crypto.randomUUID();
    set('genId', genId);
    const opts = _speakSessionOpts(genId, null);
    const session = new streaming.SpeakSession(genId, opts);
    opts._holder.session = session;
    _speakSession = session;
    streaming.startSession(session);
    await session.connect();

    if (epoch !== _connectEpoch || _speakSession !== session || S.sessionId !== session.sessionId) {
      session.close();
      if (_speakSession === session) _speakSession = null;
      return null;
    }
    return session;
  })().finally(() => {
    _connectPromise = null;
  });

  return _connectPromise;
}

export async function openProactiveSession(payload) {
  const channelId = String(payload?.channel_id ?? '').trim()
    || channelIdFromLiveSession(payload?.session_id)
    || getChannelId();
  const liveId = speakLiveSessionId(channelId);
  await history.noteProactiveConversation(payload);
  showToast('Agent 发来一条通信');
  const shouldOpen = payload?.create_window !== false && Boolean(liveId);
  if (!shouldOpen) return;
  if (channelId) set('channelId', channelId);
  set('sessionId', liveId);
  if (_speakSession?.sessionId === liveId && _speakSession?.isConnected?.()) {
    goWorkspace();
    return;
  }
  const existing = await history.findConversationForChannel(channelId);
  if (existing?.id && !isLiveSessionId(existing.id)) {
    await openConversation(existing.id);
    return;
  }
  history.ensureActiveConversation();
  goWorkspace();
  _syncProactiveUrgeDot();
  await connectSpeakSession();
}

/** SSE create_ui_request：前端自动判断能否创建/切换界面并回执。 */
export async function handleCreateUiRequest(payload) {
  const channelId = String(payload?.channel_id ?? '').trim() || getChannelId();
  const deliveryId = String(payload?.delivery_id ?? '').trim();
  const liveId = speakLiveSessionId(channelId);
  if (!deliveryId) return { ok: false, accepted: false };
  if (channelId) set('channelId', channelId);
  set('sessionId', liveId);
  history.ensureActiveConversation();
  goWorkspace();
  if (_speakSession?.sessionId === liveId) {
    if (!_speakSession.isConnected()) {
      await _speakSession.connect().catch(() => null);
    }
  } else {
    if (_speakSession && _speakSession.sessionId !== liveId) {
      _closeSpeakSession();
    }
    if (_connectPromise) await _connectPromise.catch(() => null);
    await connectSpeakSession().catch(() => null);
  }
  const connected = Boolean(_speakSession?.sessionId === liveId && _speakSession?.isConnected?.());
  const accepted = connected || Boolean(S.speakReady && liveId);
  const { http, PATHS } = await import('../api.js');
  await http.post(PATHS.speak.createUi, {
    delivery_id: deliveryId,
    accepted,
    channel_id: channelId,
    session_id: liveId,
  });
  if (accepted) showToast('Agent 发来一条通信');
  return { ok: true, accepted };
}

export async function startNew() {
  if (history.HISTORY_BYPASS) {
    // 连续会话旁路：拼入旧历史（带 created_at 区分同名 title）。
    // 仍强制重连 Speak，让后端重新 arm_enter_greeting；否则问候失败后点「新对话」无任何刷新。
    await history.beginNewConversation({ resetBackend: false });
    set('proactiveUrge', false);
    set('proactiveUnread', false);
    _syncProactiveUrgeDot();
    goWorkspace();
    import('/static/js/modules/plan.js').then(m => m.initSubPanel()).catch(() => {});
    const tb = document.getElementById('tb-title');
    if (tb) tb.textContent = S.convTitle || '连续会话';
    _closeSpeakSession();
    if (_connectPromise) await _connectPromise.catch(() => null);
    await connectSpeakSession();
    return;
  }
  streaming.abortCurrent();
  _closeSpeakSession();
  if (_connectPromise) await _connectPromise.catch(() => null);
  workStore.clear();
  workUi.closeMonitor();
  set('proactiveUrge', false);
  set('proactiveUnread', false);
  _syncProactiveUrgeDot();
  await history.beginNewConversation();
  render.clearMsgs();
  render.showEmptyState('speak');
  goWorkspace();
  import('/static/js/modules/plan.js').then(m => m.initSubPanel()).catch(() => {});
  await connectSpeakSession();
}

export function updateReactBadge() { _updateStatusBadge(); }

function _updateStatusBadge() {
  const el = document.getElementById('tb-react-status');
  if (!el) return;
  if (S.speakReady) {
    el.textContent = 'Speak Ready';
    el.style.color = 'var(--accent)';
  } else if (S.soulReady) {
    el.textContent = 'Soul Running';
    el.style.color = 'var(--accent)';
  } else {
    el.textContent = 'Speak Not ready';
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
      const createdAt = new Date().toISOString();
      render.appendUserMsg(question, { created_at: createdAt });
      history.pushMessage({ role: 'user', content: question, created_at: createdAt });
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
  const createdAt = new Date().toISOString();
  render.appendUserMsg(question, { created_at: createdAt });
  history.pushMessage({ role: 'user', content: question, created_at: createdAt });
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
  _bindTurnCallbacks(_speakSession, null);
  const result = await _speakSession.sendTurn(question);
  _handleDisconnectedTurn(_lastSpeakCtrl, result);
}

function _handleDisconnectedTurn(streamCtrl, result) {
  if (result?.type !== 'disconnected') return;
  streamCtrl?.finalize('', true);
  render.setTitleBarTyping(false);
  if (S.lifecycle === 'streaming' || S.lifecycle === 'aborting') setState('idle');
  _syncSendButton();
}

async function _runSpeak(question) {
  if (!S.speakReady) {
    showToast('Soul Speak 未就绪');
    return;
  }

  const session = await connectSpeakSession();
  if (!session) return;
  setState('streaming');
  _bindTurnCallbacks(session, null);
  const result = await session.sendTurn(question);
  _handleDisconnectedTurn(_lastSpeakCtrl, result);
  if (result?.type === 'session_end') {
    _speakSession = null;
  }
  if (result?.type === 'work_pending') {
    // Keep SpeakSession open for confirmation / later Speak fallback.
    _lastSpeakCtrl?.discardAgentTurn?.();
    render.setTitleBarTyping(false);
    setState('idle');
    _syncSendButton();
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

export function rebuildFromHistory(messages, workItems) {
  history.setMessages(messages);
  render.clearMsgs();
  _syncProactiveUrgeDot();
  const msgs = history.getMessages();
  if (!msgs.length && !(workItems || []).length) {
    render.showEmptyState('speak');
  }
  // 不再渲染空悬 proactive banner；旧历史用 thread_marker + created_at 区分同名 title
  msgs.forEach(m => {
    if (m.role === 'thread_marker') {
      render.appendThreadMarker(m.title || m.content || '对话', m.created_at, {
        title_key: m.title_key,
      });
      return;
    }
    if (m.role === 'user') {
      render.appendUserMsg(m.content, {
        created_at: m.created_at,
        title_key: m.title_key,
      });
    } else if (m.role === 'assistant') {
      if (m.speak_events?.length) {
        const ctrl = render.appendSpeakStream({
          deliveryMode: 'stream',
          created_at: m.created_at,
          instant: true,
        });
        for (const ev of sortEventsByOrder(m.speak_events)) {
          ctrl.onEvent(ev.kind, ev.text ?? '', ev.meta ?? {});
        }
        void ctrl.finalize(m.content, false);
      } else {
        const ctrl = render.appendAssistantMsg({ created_at: m.created_at });
        ctrl.append(m.content);
        ctrl.finalize();
      }
    }
  });
  workUi.rebuildWorkCards(workItems ?? workStore.summariesForHistory());
  render.scrollBottom();
  goWorkspace();
  import('/static/js/modules/plan.js').then(m => m.initSubPanel()).catch(() => {});
}

export function prepareConversationSwitch() {
  // 只中止当前流式 UI；不拆 Speak WS——同一 channel 生命线应连续
  streaming.abortCurrent();
}

export async function openConversation(convId) {
  const id = String(convId || '').trim();
  if (!id) {
    const liveId = speakLiveSessionId(S.channelId || getChannelId());
    set('sessionId', liveId);
    history.ensureActiveConversation();
    goWorkspace();
    _syncProactiveUrgeDot();
    await connectSpeakSession();
    return;
  }
  prepareConversationSwitch();
  if (_connectPromise) await _connectPromise.catch(() => null);
  await history.loadConversation(id);
  const liveId = speakLiveSessionId(S.channelId || getChannelId());
  set('sessionId', liveId);
  if (!S.sessionId) return;
  goWorkspace();
  _syncProactiveUrgeDot();
  await connectSpeakSession();
  // 将该页历史注入 speak 生命线临时记忆（最多两代），供 composer→编剧/导演调度
  const msgs = history.getMessages?.() ?? [];
  await speakMod.enterPageContext({
    sessionId: liveId,
    pageKey: String(convId || '').trim() || 'page',
    messages: msgs.map(m => ({
      role: m.role,
      content: m.content,
    })),
  }).catch(err => {
    console.warn('[speak] page_enter skipped', err?.message ?? String(err));
  });
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
  window.addEventListener('speak:responder', e => {
    if (_speakSession?.isConnected?.()) {
      _speakSession.setPipeline(e.detail);
    }
  });
}

export function initSidebar() {
  workUi.configure({
    sendWorkFrame: _sendWorkFrame,
    onHistoryPersist: () => history.saveConversation().catch(() => {}),
  });
  workUi.bindMonitorPanel();

  const sortEl = document.getElementById('sidebar-sort-mode');
  if (sortEl) {
    sortEl.value = history.getHistorySortMode();
    sortEl.addEventListener('change', () => {
      history.setHistorySortMode(sortEl.value);
      history.renderSidebar().catch(() => {});
      history.renderRecentLanding(document.getElementById('landing-recent')).catch(() => {});
    });
  }

  document.getElementById('btn-new-chat')?.addEventListener('click', () => {
    startNew().catch(err => showToast('新对话失败: ' + (err?.message ?? err)));
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
    if (
      e.detail?.key === 'speakReady'
      && S.sessionId
      && S.speakReady
      && !_speakSession?.isConnected?.()
    ) {
      connectSpeakSession().catch(err => showToast('Speak connect error: ' + err.message));
    }
  });
  _syncTraceButton();
  _syncProactiveUrgeDot();
}
