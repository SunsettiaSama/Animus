/**
 * store/session_store.js — 会话与运行状态（取代旧 state.js 的全局 S 单例）。
 *
 * 职责：
 * - 生命周期 FSM（idle/initializing/streaming/aborting/error）；
 * - 会话身份三件套：convId（历史线程）/ sessionId（Speak 生命线 live:channel）/
 *   channelId（记忆渠道，等于账号 interactor_id）；
 * - readiness（llm/soul/speak/persona）与主动消息未读态；
 * - 通过 subscribe + bus 广播变更，不再使用 window CustomEvent。
 *
 * UI 只读 state() 返回的快照对象；写入只能用本模块导出的 action。
 */

import { bus, EVENTS } from './bus.js';

// ── 账号渠道（channelId ≡ 当前账号 interactor_id，localStorage 持久化） ──────

const LEGACY_CHANNEL_KEY = 'react_speak_channel_id';
const ACCOUNT_ID_KEY = 'react_account_id';

/** 当前账号的 interactor_id 即记忆渠道 ID。 */
export function getChannelId(currentInteractorId = '') {
  const iid = String(currentInteractorId ?? '').trim();
  if (iid) return iid;
  const legacy = String(localStorage.getItem(LEGACY_CHANNEL_KEY) || '').trim();
  if (legacy && localStorage.getItem(ACCOUNT_ID_KEY)) return legacy;
  return '';
}

export function speakLiveSessionId(channelId = '') {
  const ch = String(channelId ?? '').trim();
  return ch ? `live:${ch}` : 'live:anon';
}

export function isLiveSessionId(value) {
  return String(value ?? '').trim().startsWith('live:');
}

export function channelIdFromLiveSession(sessionId = '') {
  const sid = String(sessionId ?? '').trim();
  return isLiveSessionId(sid) ? sid.slice('live:'.length).trim() : '';
}

// ── 状态机 ───────────────────────────────────────────────────────────────────

/** @typedef {'idle'|'initializing'|'streaming'|'aborting'|'error'} LifecycleState */

const _VALID_TRANSITIONS = {
  idle:         ['initializing', 'streaming'],
  initializing: ['streaming', 'error', 'idle'],
  streaming:    ['aborting', 'idle', 'error'],
  aborting:     ['idle', 'error'],
  error:        ['idle'],
};

const _state = {
  // 生命周期
  lifecycle: 'idle',
  genId: '',

  // 会话身份
  convId: null,          // 历史线程 ID（/api/history 主键）
  convTitle: '新对话',
  sessionId: null,       // Speak 生命线（live:channelId）
  channelId: '',
  convCreatedAt: '',

  // readiness
  llmReady: false,
  soulReady: false,
  speakReady: false,

  // 主动消息
  proactiveUrge: false,
  proactiveUnread: false,

  // Worker 聚合
  activeWorkIds: [],
  workBusy: false,

  // 其他展示态
  personaName: null,
  llmModel: null,
};

const _subscribers = new Set();

/** 只读快照。调用方不得修改返回对象（浅冻结关键标量即可满足约定）。 */
export function state() {
  return { ..._state };
}

/**
 * 订阅字段变更。
 * @param {(snapshot:object, changed:object)=>void} fn
 * @returns {()=>void} 取消订阅
 */
export function subscribe(fn) {
  _subscribers.add(fn);
  return () => _subscribers.delete(fn);
}

function _apply(patch, { silent = false } = {}) {
  const changed = {};
  let touched = false;
  for (const [key, value] of Object.entries(patch)) {
    if (!(key in _state)) continue;
    if (_state[key] === value) continue;
    _state[key] = value;
    changed[key] = value;
    touched = true;
  }
  if (!touched) return;
  const snapshot = state();
  if (!silent) {
    for (const fn of [..._subscribers]) {
      try {
        fn(snapshot, changed);
      } catch (err) {
        console.warn('[session_store] subscriber error', err);
      }
    }
    bus.emit(EVENTS.sessionFields, changed);
  }
}

/** 批量更新字段（见 _state 注释的字段域）。silent 时不广播。 */
export function update(patch, opts) {
  _apply(patch, opts);
}

/**
 * 生命周期迁移（带 FSM 校验）。非法迁移仅告警并忽略。
 * @param {LifecycleState} next
 */
export function setLifecycle(next) {
  const from = _state.lifecycle;
  const allowed = _VALID_TRANSITIONS[from];
  if (!allowed || !allowed.includes(next)) {
    console.warn(`[session_store] Invalid transition ${from} → ${next}; skipped.`);
    return false;
  }
  _apply({ lifecycle: next });
  bus.emit(EVENTS.sessionLifecycle, { from, to: next });
  return true;
}

export function isBusy() {
  const lc = _state.lifecycle;
  return lc !== 'idle' && lc !== 'error';
}

// ── 会话身份动作 ─────────────────────────────────────────────────────────────

/** 生成一套新会话身份：新 convId + 复用 channel 的 live session。 */
export function newIds(currentInteractorId = '') {
  const channelId = getChannelId(currentInteractorId);
  return {
    convId: crypto.randomUUID(),
    sessionId: speakLiveSessionId(channelId),
    channelId,
  };
}

/** 当前线程无记录时补齐身份；返回是否新建。 */
export function ensureActiveConversation({ bypass = false } = {}) {
  if (_state.convId && _state.sessionId) return false;
  const ids = newIds();
  _apply({
    convId: ids.convId,
    sessionId: ids.sessionId,
    channelId: ids.channelId,
    convTitle: bypass ? '连续会话' : '新对话',
    convCreatedAt: new Date().toISOString(),
  });
  return true;
}
