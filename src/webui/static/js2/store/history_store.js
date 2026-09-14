/**
 * store/history_store.js — 对话历史数据层（自旧 history.js 剥离全部 DOM 渲染）。
 *
 * convId：历史线程 ID（列表、持久化主键）
 * sessionId：Speak 生命线（live:channelId），多对话页共享
 * channelId：记忆渠道（认人绑定），多线程共享
 *
 * 渲染（侧栏、Landing 最近列表）由 ui 层订阅 historyChanged 完成。
 */

import { API } from '../protocol/http_api.js';
import { http } from '../transport/http.js';
import { bus, EVENTS } from './bus.js';
import * as sessionStore from './session_store.js';
import * as chatStore from './chat_store.js';
import * as workStore from './work_store.js';

/** @typedef {'time_desc'|'time_asc'|'title_asc'|'title_desc'} HistorySortMode */

const _SORT_STORAGE_KEY = 'react.history.sortMode';
const SORT_MODES = Object.freeze(['time_desc', 'time_asc', 'title_asc', 'title_desc']);

let _sortMode = _loadSortMode();
let _conversations = [];       // 最近一次拉取的列表快照
const _listeners = new Set();

function _loadSortMode() {
  const raw = String(localStorage.getItem(_SORT_STORAGE_KEY) || 'time_desc').trim();
  return SORT_MODES.includes(raw) ? raw : 'time_desc';
}

export function subscribe(fn) {
  _listeners.add(fn);
  return () => _listeners.delete(fn);
}

function _notifyChanged() {
  // 对外快照一律按当前排序模式整理：订阅方（侧栏/Landing）不做二次排序。
  const snapshot = sortConversations(_conversations);
  for (const fn of [..._listeners]) {
    try {
      fn(snapshot);
    } catch (err) {
      console.warn('[history_store] subscriber error', err);
    }
  }
  bus.emit(EVENTS.historyChanged, { conversations: snapshot });
}

export function getSortMode() {
  return _sortMode;
}

export function setSortMode(mode) {
  const next = String(mode || '').trim();
  if (!SORT_MODES.includes(next)) return _sortMode;
  _sortMode = next;
  localStorage.setItem(_SORT_STORAGE_KEY, next);
  _notifyChanged();
  return _sortMode;
}

export function sortConversations(list) {
  const items = Array.isArray(list) ? [...list] : [];
  const mode = _sortMode;
  items.sort((a, b) => {
    if (mode === 'title_asc' || mode === 'title_desc') {
      const cmp = String(a.title || '').localeCompare(String(b.title || ''), 'zh-CN', {
        sensitivity: 'base',
      });
      if (cmp !== 0) return mode === 'title_asc' ? cmp : -cmp;
      // 同名 title：再用创建时间区分，避免合并观感
      const ta = Date.parse(a.created_at || a.updated_at || '') || 0;
      const tb = Date.parse(b.created_at || b.updated_at || '') || 0;
      return mode === 'title_asc' ? ta - tb : tb - ta;
    }
    const ta = Date.parse(a.created_at || a.updated_at || '') || 0;
    const tb = Date.parse(b.created_at || b.updated_at || '') || 0;
    return mode === 'time_asc' ? ta - tb : tb - ta;
  });
  return items;
}

export async function refreshList() {
  const { conversations } = await http.get(API.history.list);
  _conversations = Array.isArray(conversations) ? conversations : [];
  _notifyChanged();
  return _conversations;
}

export function conversations() {
  return sortConversations(_conversations);
}

// ── 加载 / 保存 / 删除 ───────────────────────────────────────────────────────

/**
 * 打开一条历史线程：写 session_store 身份、恢复消息与 work 快照。
 * 返回后端会话数据；未读 proactive 线程自动清除未读并回存。
 */
export async function loadConversation(convId, { onBeforeSwitch } = {}) {
  const id = String(convId ?? '').trim();
  if (!id) throw new Error('history conv_id required');

  const data = await http.get(API.history.item(id));
  const st = sessionStore.state();

  if (typeof onBeforeSwitch === 'function') await onBeforeSwitch();
  if (st.convId && st.convId !== id && chatStore.getMessages().length) {
    await saveConversation().catch(() => {});
  }

  const channelId = data.channel_id || st.channelId;
  const unread = Boolean(data.proactive_unread);
  sessionStore.update({
    convId: data.id,
    convTitle: data.title,
    channelId,
    sessionId: sessionStore.speakLiveSessionId(channelId),
    proactiveUnread: unread,
    proactiveUrge: unread,
    convCreatedAt: data.created_at || '',
  });
  chatStore.setMessages(data.messages ?? []);
  workStore.restoreFromHistory(data.work_items ?? []);

  if (unread) {
    sessionStore.update({ proactiveUnread: false, proactiveUrge: false });
    bus.emit(EVENTS.proactiveUnread, { unread: false, urge: false });
    await saveConversation({ clearProactiveUnread: true, forcePersist: true });
    return data;
  }
  await refreshList();
  return data;
}

/**
 * 保存当前线程（消息、work 摘要、未读标记）。
 * @param {{clearProactiveUnread?:boolean, proactiveUnread?:boolean,
 *          agentInitiated?:boolean, forcePersist?:boolean}} [extra]
 */
export async function saveConversation(extra = {}) {
  // single-stream R1：轮次历史退役——转录不再落盘，记忆系统是唯一的历史
  // （看过去 = /api/memory/timeline 回忆面板）。保留 proactive 未读的
  // 会话侧副作用，调用方（work 联动等）无需改动。
  if (extra.clearProactiveUnread === true) {
    sessionStore.update({ proactiveUnread: false, proactiveUrge: false }, { silent: true });
    bus.emit(EVENTS.proactiveUnread, { unread: false, urge: false });
  } else if (extra.proactiveUnread === true || extra.agentInitiated === true) {
    sessionStore.update({ proactiveUnread: true, proactiveUrge: true }, { silent: true });
    bus.emit(EVENTS.proactiveUnread, { unread: true, urge: true });
  }
  return { ok: true, skipped: 'single-stream' };
}

export async function deleteConversation(_convId) {
  // single-stream：旧转录只读存档，不再提供删除（后端 history 路由已只读化）
  return { ok: false, skipped: 'single-stream' };
}

export async function clearAllHistory() {
  return { ok: false, skipped: 'single-stream' };
}

/**
 * 新对话：只创建历史线程；Speak 仍复用同一 channel 生命线。
 * @param {{resetBackendSession?: (sid:string)=>Promise<any>, interactorId?: string}} [opts]
 */
export async function beginNewConversation(opts = {}) {
  const st = sessionStore.state();
  if (st.convId && chatStore.getMessages().length) {
    await saveConversation().catch(() => {});
  }
  const ids = sessionStore.newIds(opts.interactorId);
  sessionStore.update({
    convId: ids.convId,
    sessionId: ids.sessionId,
    channelId: ids.channelId,
    convTitle: '新对话',
    convCreatedAt: new Date().toISOString(),
  });
  chatStore.setMessages([]);
  workStore.clear();
  if (typeof opts.resetBackendSession === 'function') {
    await opts.resetBackendSession(ids.sessionId).catch(err => {
      console.warn('[history] reset backend session skipped', err?.message ?? err);
    });
  }
  await refreshList();
  return ids;
}

/** 为指定渠道找历史线程：优先未读 proactive，其次最新。 */
export async function findConversationForChannel(channelId) {
  const ch = String(channelId || '').trim();
  if (!ch) return null;
  const { conversations } = await http.get(API.history.list);
  const sorted = sortConversations(conversations).filter(
    item => String(item.channel_id || '').trim() === ch,
  );
  return sorted.find(item => Boolean(item.proactive_unread)) || sorted[0] || null;
}
