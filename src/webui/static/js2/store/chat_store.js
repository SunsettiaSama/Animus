/**
 * store/chat_store.js — 当前会话消息流与 turn 状态。
 *
 * 消息模型（与后端 /api/history 持久化兼容）：
 *   { role: 'user'|'assistant'|'thread_marker', content, created_at,
 *     agent_initiated?, speak_events?, output?, title_key?, source_*? }
 *
 * UI 渲染入口：subscribe(messagesChanged) 或 bus 上的 chat:* 事件。
 * 网络写入（发送消息）不经本层 —— 见 features/conversation.js。
 */

import { bus, EVENTS } from './bus.js';

let _messages = [];
const _subscribers = new Set();

export function getMessages() {
  return _messages;
}

export function subscribe(fn) {
  _subscribers.add(fn);
  return () => _subscribers.delete(fn);
}

function _commit() {
  const snapshot = [..._messages];
  for (const fn of [..._subscribers]) {
    try {
      fn(snapshot);
    } catch (err) {
      console.warn('[chat_store] subscriber error', err);
    }
  }
  bus.emit(EVENTS.messagesChanged, { messages: snapshot });
}

export function setMessages(msgs) {
  _messages = Array.isArray(msgs) ? [...msgs] : [];
  _commit();
}

export function pushMessage(msg) {
  const now = new Date().toISOString();
  _messages.push({
    ...msg,
    created_at: msg?.created_at || now,
  });
  _commit();
}

/** 末条 assistant 消息（流式回填用）；无则新建并 push。 */
export function upsertLastAssistant(mutator) {
  const last = _messages[_messages.length - 1];
  if (last && last.role === 'assistant') {
    mutator(last);
  } else {
    const fresh = { role: 'assistant', content: '' };
    mutator(fresh);
    _messages.push(fresh);
  }
  _commit();
}

export function clearMessages() {
  _messages = [];
  _commit();
}

/** 供 ConvLoop.restore：仅 role + content。 */
export function messagesForConvRestore(msgs) {
  return (msgs ?? [])
    .filter(m => (m.role === 'user' || m.role === 'assistant') && m.content != null)
    .map(m => ({
      role: m.role,
      content: typeof m.content === 'string' ? m.content : String(m.content),
    }));
}

// ── 默认标题推导（保存历史用） ────────────────────────────────────────────────

/** title 身份：同名标题靠 created_at 区分，避免合并。 */
export function titleKey(title, createdAt) {
  return `${String(title ?? '').trim()}@@${String(createdAt ?? '').trim()}`;
}

export function defaultTitle({ currentTitle = '', bypass = false } = {}) {
  const proactive = _messages.find(
    message => message.role === 'assistant' && message.agent_initiated,
  );
  const hasUser = _messages.some(m => m.role === 'user');
  if (proactive && !hasUser) {
    if (currentTitle && currentTitle !== '新对话' && currentTitle !== '连续会话') {
      return currentTitle;
    }
    const proactiveText = String(proactive.content ?? '');
    return proactiveText.slice(0, 48) + (proactiveText.length > 48 ? '…' : '');
  }
  if (bypass) return '连续会话';
  const first = _messages.find(m => m.role === 'user');
  if (!first) return '新对话';
  const text = String(first.content ?? '');
  return text.slice(0, 48) + (text.length > 48 ? '…' : '');
}
