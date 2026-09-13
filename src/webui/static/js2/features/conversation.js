/**
 * features/conversation.js — 会话编排核心（发送管线 / turn 生命周期 / 路由决策 /
 * 主动消息开窗 / 历史切换）。
 *
 * 分层契约：
 * - 本模块持有 AgentChannel 实例与 turn 状态机；帧构造/解析在 protocol 层；
 * - 视图（ui/screens/workspace.js）通过 registerChatView(view) 注册视图契约，
 *   本模块只调用契约方法，不直接操作 DOM；
 * - 持久化经 store 层完成；通知经 bus 发射。
 *
 * 视图契约 view = {
 *   onTurnStart({event, meta})                 turn 开始：确保流式 ctrl、打字态
 *   onSpeakEvent({kind,text,renderMeta,deliveryId})  流式事件路由（含 holder 换控）
 *   async onFinalizeTurn(payload, turnMeta)     → {events, speakText, createdAt}
 *   onDiscardTurn()                             丢弃当前 agent 气泡（不持久化）
 *   onRouteDecision(msg)                        渲染首轮路由卡（纠错按钮回调本模块）
 *   onTyping(active)                            顶栏打字态
 *   onLifecycle(busy)                           发送按钮等 busy 视觉
 *   onClearMessages()                           清空消息区 + 空态
 *   onRebuild(messages, workItems)              按历史重建消息区
 *   onCloseMonitor() / onPersistWork()          work 面板与持久化钩子
 * }
 */

import { AgentChannel } from '../transport/agent_channel.js';
import * as frames from '../protocol/frames.js';
import { bus, EVENTS } from '../store/bus.js';
import * as sessionStore from '../store/session_store.js';
import * as chatStore from '../store/chat_store.js';
import * as workStore from '../store/work_store.js';
import * as historyStore from '../store/history_store.js';
import { http } from '../transport/http.js';
import { API } from '../protocol/http_api.js';

let _view = null;
let _channel = null;
let _connectPromise = null;
/** 关闭会话时递增；进行中的 connect 据此丢弃。 */
let _connectEpoch = 0;

export function registerChatView(view) {
  _view = view;
}

function _toast(text) {
  bus.emit(EVENTS.toastShow, String(text ?? ''));
}

function _navigateWorkspace() {
  bus.emit(EVENTS.navigateRequest, { screen: 's-workspace' });
}

function _v() {
  return _view || {};
}

function _call(name, ...args) {
  const fn = _view?.[name];
  return typeof fn === 'function' ? fn(...args) : undefined;
}

async function _callAsync(name, ...args) {
  const fn = _view?.[name];
  return typeof fn === 'function' ? await fn(...args) : undefined;
}

// ── Work 事件处理 ────────────────────────────────────────────────────────────

function _onWorkEvent(ev) {
  workStore.ingest(ev);
  if (ev.type === 'work_declined' && ev.reason) _toast(ev.reason);
  if (ev.type === 'work_failed' && (ev.reason || ev.message)) {
    _toast(ev.reason || ev.message);
  }
  if (['work_started', 'work_progress', 'work_finished', 'work_failed', 'work_aborted', 'work_declined'].includes(ev.type)) {
    historyStore.saveConversation().catch(() => {});
  }
  if (ev.type === 'work_confirmation_required' || ev.type === 'work_started') {
    if (sessionStore.isBusy()) sessionStore.setLifecycle('idle');
    _call('onTyping', false);
  }
  _call('onLifecycle', sessionStore.isBusy());
}

// ── 连接管理 ─────────────────────────────────────────────────────────────────

function _closeChannel() {
  _connectEpoch += 1;
  if (_channel) {
    _channel.close();
    _channel = null;
  }
}

function _getDraft() {
  return document.getElementById('msg-input')?.value ?? '';
}

function _makeChannel(genId) {
  const st = sessionStore.state();
  const channel = new AgentChannel(genId, {
    sessionId: st.sessionId,
    channelId: st.channelId,
    getDraft: _getDraft,
    typingIdleMs: 3000,
  });
  channel.setHandlers({
    onSessionReady: () => {
      bus.emit(EVENTS.speakReady, { sessionId: channel.sessionId });
    },
    onTurnStart: ({ event, meta }) => {
      _call('onTurnStart', { event, meta });
      if (!sessionStore.isBusy()) sessionStore.setLifecycle('streaming');
      _call('onLifecycle', true);
    },
    onSpeakEvent: ev => {
      _call('onSpeakEvent', ev);
    },
    onTurnFinish: payload => {
      _finishTurn(payload).catch(err => {
        console.warn('[conversation] finish turn failed', err);
      });
    },
    onRouteDecision: msg => {
      bus.emit(EVENTS.routeDecision, msg);
      _call('onRouteDecision', msg);
    },
    onRoutePierceOk: msg => {
      const route = String(msg?.route || '').trim();
      if (route) _toast(`路由已纠正为 ${route}`);
    },
    onWorkEvent: _onWorkEvent,
    onAborted: () => {
      _call('onTyping', false);
    },
    onError: err => {
      _toast('Speak error: ' + err.message);
      _call('onDiscardTurn');
      _call('onTyping', false);
      _closeChannel();
      sessionStore.setLifecycle('idle');
      _call('onLifecycle', false);
    },
  });
  return channel;
}

/** 建连（epoch 防抢）。视图/应用在 speakReady 后调用。 */
export async function connect() {
  const st = sessionStore.state();
  if (!st.speakReady || !st.sessionId) return null;
  const epoch = _connectEpoch;

  if (_connectPromise) {
    const existing = await _connectPromise.catch(() => null);
    if (epoch !== _connectEpoch) return null;
    if (existing?.sessionId === st.sessionId && existing.isConnected()) return existing;
  }
  if (_connectPromise) return _connectPromise;
  if (epoch !== _connectEpoch) return null;

  _connectPromise = (async () => {
    if (epoch !== _connectEpoch) return null;

    if (_channel?.sessionId === st.sessionId) {
      if (_channel.isConnected()) return _channel;
      await _channel.connect();
      if (epoch !== _connectEpoch || _channel?.sessionId !== st.sessionId) return null;
      return _channel;
    }

    // 换 session 时只拆旧连接，不抬升 epoch（否则会把自己刚开的连接判废）
    if (_channel) {
      _channel.close();
      _channel = null;
    }

    const genId = crypto.randomUUID();
    sessionStore.update({ genId });
    const channel = _makeChannel(genId);
    _channel = channel;
    await channel.connect();

    if (epoch !== _connectEpoch || _channel !== channel
        || sessionStore.state().sessionId !== channel.sessionId) {
      channel.close();
      if (_channel === channel) _channel = null;
      return null;
    }
    return channel;
  })().finally(() => {
    _connectPromise = null;
  });

  return _connectPromise;
}

// ── Turn 完成：持久化与 ack ──────────────────────────────────────────────────

async function _finishTurn(payload) {
  const turnMeta = _lastTurnMeta;
  _lastTurnMeta = {};

  if (payload.hide_agent || payload.silence_policy === 'hidden') {
    _call('onDiscardTurn');
    _call('onTyping', false);
    sessionStore.setLifecycle('idle');
    _call('onLifecycle', false);
    return;
  }

  const readout = await _callAsync('onFinalizeTurn', payload, turnMeta);
  const events = readout?.events ?? [];
  const answer = payload.answer ?? readout?.speakText ?? '';
  const createdAt = String(
    payload.created_at
    || turnMeta.created_at
    || readout?.createdAt
    || '',
  ).trim();

  const aborted = Boolean(payload.aborted);
  if (payload.queued) _toast('消息已排队');
  else if (payload.interrupt) _toast('已插队，Agent 将转向新消息');

  const hasOutline = events.some(
    (ev) => ev?.kind === 'outline' || ev?.meta?.field === 'outline',
  );
  if (!aborted && (answer || hasOutline)) {
    const metadata = { ...turnMeta, ...payload };
    const proactiveId = String(metadata.proactive_intent_id ?? '').trim();
    const duplicate = proactiveId && chatStore.getMessages().some(
      message => message.proactive_intent_id === proactiveId,
    );
    if (!duplicate) {
      chatStore.pushMessage({
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
    await historyStore.saveConversation({
      agentInitiated: Boolean(metadata.agent_initiated),
      proactiveUnread: Boolean(metadata.agent_initiated),
    });
    _call('onTyping', false);
  }
  sessionStore.setLifecycle('idle');
  _call('onLifecycle', false);

  // 持久化完成后 ack，hub 才会投递下一条主动消息
  const deliveryId = String(payload.delivery_id ?? turnMeta.delivery_id ?? '').trim();
  if (deliveryId && _channel) _channel.acknowledgeProactive(deliveryId);
}

let _lastTurnMeta = {};

/** 供视图在 turn_start/speak_event 时补充 proactive 元数据。 */
export function accumulateTurnMeta(meta) {
  if (meta?.agent_initiated || meta?.proactive_intent_id) {
    _lastTurnMeta = { ..._lastTurnMeta, ...meta };
  }
}

export function seedTurnMeta(meta = {}) {
  _lastTurnMeta = { ...meta };
}

// ── 发送管线 ─────────────────────────────────────────────────────────────────

/**
 * 发送一条用户消息（应用层负责读取输入框并清空）。
 * @returns {Promise<void>}
 */
export async function send(question) {
  const text = String(question ?? '').trim();
  const st = sessionStore.state();

  if (st.lifecycle === 'streaming' || st.lifecycle === 'aborting') {
    if (!text) {
      abortStream();
      return;
    }
    if (_channel?.sendTurn === undefined || !_channel.isConnected()) {
      abortStream();
      return;
    }
    // 回复进行中：继续输入走队列/打断语义（服务端决定）。
    const ok = _channel.sendFrame(frames.userMessage(text, _channelEnvelope()));
    if (ok) {
      const createdAt = new Date().toISOString();
      _call('onUserMessageSent', text, createdAt);
      chatStore.pushMessage({ role: 'user', content: text, created_at: createdAt });
      _toast('已发送，Agent 回复中可继续输入');
    }
    return;
  }

  if (!text) return;
  if (st.proactiveUrge || st.proactiveUnread) {
    sessionStore.update({ proactiveUrge: false, proactiveUnread: false });
    bus.emit(EVENTS.proactiveUnread, { unread: false, urge: false });
  }

  sessionStore.ensureActiveConversation();
  _navigateWorkspace();
  bus.emit(EVENTS.planInitSubpanel, {});
  const createdAt = new Date().toISOString();
  _call('onUserMessageSent', text, createdAt);
  chatStore.pushMessage({ role: 'user', content: text, created_at: createdAt });
  await historyStore.saveConversation({ clearProactiveUnread: true }).catch(() => {});

  if (_channel?.isConnected()) {
    await _continueTurn(text);
    return;
  }
  await _runTurn(text);
}

function _channelEnvelope() {
  return {
    genId: _channel?.genId ?? '',
    sessionId: _channel?.sessionId ?? '',
  };
}

async function _continueTurn(question) {
  if (!_channel?.isConnected()) {
    await _runTurn(question);
    return;
  }
  sessionStore.setLifecycle('streaming');
  const result = await _channel.sendTurn(question);
  await _handleTurnResult(result);
}

async function _runTurn(question) {
  if (!sessionStore.state().speakReady) {
    _toast('Soul Speak 未就绪');
    return;
  }
  const channel = await connect();
  if (!channel) return;
  sessionStore.setLifecycle('streaming');
  const result = await channel.sendTurn(question);
  await _handleTurnResult(result);
  if (result?.type === 'session_end') {
    _channel = null;
  }
}

async function _handleTurnResult(result) {
  if (result?.type === 'disconnected') {
    _call('onDiscardTurn');
    _call('onTyping', false);
    if (sessionStore.isBusy()) sessionStore.setLifecycle('idle');
    _call('onLifecycle', false);
    return;
  }
  if (result?.type === 'work_pending') {
    // 保持 WS 打开等待确认 / 后续 speak fallback；不落 assistant 消息。
    _call('onDiscardTurn');
    _call('onTyping', false);
    sessionStore.setLifecycle('idle');
    _call('onLifecycle', false);
  }
}

/** 中止当前流（空内容点击发送或显式中止）。 */
export function abortStream() {
  if (_channel) _channel.abort();
  _closeChannel();
  sessionStore.setLifecycle('idle');
  _call('onLifecycle', false);
}

/** 只中止当前流式 UI；不拆 Speak WS——同一 channel 生命线应连续。 */
export function prepareConversationSwitch() {
  if (_channel) _channel.abort();
}

// ── 路由击穿 ─────────────────────────────────────────────────────────────────

/** 路由卡「分错了」按钮调用。 */
export function sendRoutePierce(trueRoute, sampleId = '') {
  if (!_channel?.isConnected()) {
    _toast('会话未连接，无法提交纠错');
    return false;
  }
  const extra = trueRoute === 'work' ? { work_id: String(sampleId ?? '') } : {};
  return _channel.sendFrame(frames.routePierce(trueRoute, _channelEnvelope(), extra));
}

/** Worker 确认域出站帧（确认卡按钮调用）。 */
export function sendWorkFrame(payload) {
  if (!_channel?.isConnected()) {
    _toast('会话未连接，无法发送任务指令');
    return false;
  }
  return _channel.sendWorkFrame(payload);
}

// ── 会话切换 / 新对话 ────────────────────────────────────────────────────────

export async function startNew() {
  abortStream();
  workStore.clear();
  _call('onCloseMonitor');
  sessionStore.update({ proactiveUrge: false, proactiveUnread: false });
  bus.emit(EVENTS.proactiveUnread, { unread: false, urge: false });
  const interactorId = _currentInteractorId();
  await historyStore.beginNewConversation({ interactorId });
  _call('onClearMessages');
  _navigateWorkspace();
  bus.emit(EVENTS.planInitSubpanel, {});
  await connect();
}

export async function openConversation(convId) {
  const id = String(convId || '').trim();
  const st = sessionStore.state();
  if (!id) {
    const liveId = sessionStore.speakLiveSessionId(st.channelId || _currentInteractorId());
    sessionStore.update({ sessionId: liveId });
    sessionStore.ensureActiveConversation();
    _navigateWorkspace();
    await connect();
    return;
  }
  prepareConversationSwitch();
  if (_connectPromise) await _connectPromise.catch(() => null);
  await historyStore.loadConversation(id, { onBeforeSwitch: prepareConversationSwitch });
  const now = sessionStore.state();
  const liveId = sessionStore.speakLiveSessionId(now.channelId || _currentInteractorId());
  sessionStore.update({ sessionId: liveId });
  if (!now.sessionId && !liveId) return;
  _navigateWorkspace();
  _call('onRebuild', chatStore.getMessages(), workStore.summariesForHistory());
  bus.emit(EVENTS.planInitSubpanel, {});
  await connect();
  // 将该页历史注入 speak 生命线临时记忆（最多两代），供 composer→编剧/导演调度
  const msgs = chatStore.getMessages();
  await http.post(API.speak.pageEnter, {
    session_id: liveId,
    page_key: id || 'page',
    messages: msgs.map(m => ({ role: m.role, content: m.content })),
  }).catch(err => {
    console.warn('[speak] page_enter skipped', err?.message ?? String(err));
  });
}

// ── 主动消息开窗 ─────────────────────────────────────────────────────────────

export async function openProactiveSession(payload) {
  const channelId = String(payload?.channel_id ?? '').trim()
    || sessionStore.channelIdFromLiveSession(payload?.session_id)
    || _currentInteractorId();
  const liveId = sessionStore.speakLiveSessionId(channelId);
  await historyStore.refreshList();
  _toast('Agent 发来一条通信');
  const shouldOpen = payload?.create_window !== false && Boolean(liveId);
  if (!shouldOpen) return;
  sessionStore.update({ channelId, sessionId: liveId });
  if (_channel?.sessionId === liveId && _channel.isConnected()) {
    _navigateWorkspace();
    return;
  }
  const existing = await historyStore.findConversationForChannel(channelId);
  if (existing?.id && !sessionStore.isLiveSessionId(existing.id)) {
    await openConversation(existing.id);
    return;
  }
  sessionStore.ensureActiveConversation();
  _navigateWorkspace();
  await connect();
}

/** SSE create_ui_request：前端自动判断能否创建/切换界面并回执。 */
export async function handleCreateUiRequest(payload) {
  const channelId = String(payload?.channel_id ?? '').trim() || _currentInteractorId();
  const deliveryId = String(payload?.delivery_id ?? '').trim();
  const liveId = sessionStore.speakLiveSessionId(channelId);
  if (!deliveryId) return { ok: false, accepted: false };
  sessionStore.update({ channelId, sessionId: liveId });
  sessionStore.ensureActiveConversation();
  _navigateWorkspace();
  if (_channel?.sessionId === liveId) {
    if (!_channel.isConnected()) {
      await _channel.connect().catch(() => null);
    }
  } else {
    if (_channel && _channel.sessionId !== liveId) {
      _closeChannel();
    }
    if (_connectPromise) await _connectPromise.catch(() => null);
    await connect().catch(() => null);
  }
  const connected = Boolean(_channel?.sessionId === liveId && _channel.isConnected());
  const accepted = connected || Boolean(sessionStore.state().speakReady && liveId);
  await http.post(API.speak.createUi, {
    delivery_id: deliveryId,
    accepted,
    channel_id: channelId,
    session_id: liveId,
  });
  if (accepted) _toast('Agent 发来一条通信');
  return { ok: true, accepted };
}

// ── 当前 interactor（由 app 装配时注入，避免 features 依赖账号 UI） ─────────

let _interactorIdProvider = () => '';

export function setInteractorIdProvider(fn) {
  if (typeof fn === 'function') _interactorIdProvider = fn;
}

function _currentInteractorId() {
  return String(_interactorIdProvider() ?? '').trim();
}
