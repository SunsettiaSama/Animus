/**
 * history.js — 前端对话历史（展示/归档），与后端 Speak session 解耦。
 *
 * - convId：历史线程 ID（列表、持久化主键）
 * - sessionId：后端 Speak 上下文（distiller / 队列），存于每条历史记录
 * - channelId：记忆渠道（认人绑定），多线程共享，见 channel.js
 */

import { http, PATHS } from './api.js';
import { S, set }      from './state.js';
import { getChannelId } from './channel.js';

/** 供 ConvLoop.restore：仅 role + content。 */
export function messagesForConvRestore(msgs) {
  return (msgs ?? [])
    .filter(m => (m.role === 'user' || m.role === 'assistant') && m.content != null)
    .map(m => ({
      role:    m.role,
      content: typeof m.content === 'string' ? m.content : String(m.content),
    }));
}

export async function syncConvLoopFromMessages(msgs) {
  const wire = messagesForConvRestore(msgs);
  if (!wire.length) return;
  await http.post(PATHS.react.restore, { messages: wire });
}

/** 重置指定后端 Speak session（不影响其它历史线程）。 */
export async function resetBackendSession(sessionId) {
  const sid = String(sessionId ?? '').trim();
  if (!sid) return;
  const speak = await import('./modules/speak.js');
  await speak.resetSession(sid);
}

const _cb = {
  onLoad:         () => {},
  onToast:        () => {},
  onBeforeSwitch: () => {},
};

export function setCallbacks(cbs) {
  Object.assign(_cb, cbs);
}

let _messages = [];

export function getMessages() { return _messages; }

export function setMessages(msgs) {
  _messages = Array.isArray(msgs) ? [...msgs] : [];
}

export function pushMessage(msg) {
  _messages.push(msg);
}

export function clearMessages() {
  _messages = [];
}

export function newIds() {
  return {
    convId:    crypto.randomUUID(),
    sessionId: crypto.randomUUID(),
    channelId: getChannelId(),
  };
}

/** 当前线程无记录时创建；返回是否新建。 */
export function ensureActiveConversation() {
  if (S.convId && S.sessionId) return false;
  const ids = newIds();
  set('convId', ids.convId);
  set('sessionId', ids.sessionId);
  set('channelId', ids.channelId);
  set('convTitle', '新对话');
  set('_createdAt', new Date().toISOString());
  return true;
}

export async function saveConversation(extra = {}) {
  if (!_messages.length) return;
  ensureActiveConversation();
  const now = new Date().toISOString();
  const convId = S.convId;
  const title  = _defaultTitle();
  set('convTitle', title);
  const agentInitiated = Boolean(
    extra.agentInitiated ?? S.proactiveUrge ?? _messages.some(m => m.agent_initiated),
  );
  let proactiveUnread = Boolean(S.proactiveUnread);
  if (extra.proactiveUnread === true) proactiveUnread = true;
  if (extra.agentInitiated === true) proactiveUnread = true;
  if (extra.clearProactiveUnread === true) proactiveUnread = false;
  set('proactiveUnread', proactiveUnread);
  set('proactiveUrge', proactiveUnread);
  await http.post(PATHS.history.item(convId), {
    id:         convId,
    title,
    mode:       S.convMode ?? 'speak',
    messages:   _messages,
    session_id: S.sessionId ?? '',
    channel_id: S.channelId || getChannelId(),
    agent_initiated: agentInitiated,
    proactive_unread: proactiveUnread,
    created_at: S._createdAt ?? now,
    updated_at: now,
  });
  await renderSidebar();
  await renderRecentLanding(document.getElementById('landing-recent'));
}

export async function loadConversation(convId) {
  await _cb.onBeforeSwitch();
  if (S.convId && S.convId !== convId && _messages.length) {
    await saveConversation().catch(() => {});
  }
  const data = await http.get(PATHS.history.item(convId));
  set('convId', data.id);
  set('convTitle', data.title);
  set('convMode', data.mode ?? 'speak');
  set('sessionId', data.session_id || data.id);
  set('channelId', data.channel_id || getChannelId());
  const unread = Boolean(data.proactive_unread);
  set('proactiveUnread', unread);
  set('proactiveUrge', unread);
  set('_createdAt', data.created_at || '');
  _messages = data.messages ?? [];
  if (S.convMode === 'react' && S.reactReady) {
    await syncConvLoopFromMessages(_messages).catch(() => {});
  }
  const tb = document.getElementById('tb-title');
  if (tb) tb.textContent = data.title || '对话';
  _cb.onLoad(_messages);
  await renderSidebar();
}

export async function deleteConversation(convId) {
  await http.del(PATHS.history.item(convId));
  if (S.convId === convId) {
    set('convId', null);
    set('sessionId', null);
    set('convTitle', '新对话');
    clearMessages();
    _cb.onLoad([]);
  }
  await renderSidebar();
}

export async function clearAllHistory() {
  await http.del(PATHS.history.list);
  set('convId', null);
  set('sessionId', null);
  set('convTitle', '新对话');
  clearMessages();
  _cb.onLoad([]);
  await renderSidebar();
}

/** 新对话：新历史线程 + 新后端 session，渠道 ID 不变。 */
export async function beginNewConversation({ resetBackend = true } = {}) {
  await _cb.onBeforeSwitch();
  if (S.convId && _messages.length) {
    await saveConversation().catch(() => {});
  }
  const ids = newIds();
  set('convId', ids.convId);
  set('sessionId', ids.sessionId);
  set('channelId', ids.channelId);
  set('convTitle', '新对话');
  set('_createdAt', new Date().toISOString());
  clearMessages();
  if (resetBackend) {
    await resetBackendSession(ids.sessionId);
  }
  const tb = document.getElementById('tb-title');
  if (tb) tb.textContent = '新对话';
  await renderSidebar();
}

export async function renderSidebar() {
  const listEl = document.getElementById('sidebar-list');
  if (!listEl) return;

  const { conversations } = await http.get(PATHS.history.list);

  listEl.innerHTML = '';

  if (!conversations.length) {
    listEl.innerHTML = '<div class="sidebar-empty">暂无历史对话</div>';
    return;
  }

  conversations.forEach(c => {
    const icon = c.mode === 'react' ? '⚡' : '💬';
    const item = document.createElement('div');
    const proactive = Boolean(c.agent_initiated);
    const unread = Boolean(c.proactive_unread);
    item.className = `hist-item${c.id === S.convId ? ' active' : ''}${proactive ? ' proactive-urge' : ''}`;
    item.dataset.id = c.id;
    item.innerHTML = `
      <span class="hi-icon">${icon}</span>
      <div class="hi-body">
        <div class="hi-title">${_esc(c.title)}</div>
        <div class="hi-meta">${_relTime(c.updated_at)}</div>
      </div>
      ${unread ? '<span class="hi-proactive-dot" title="Agent 主动通信 · 未回复"></span>' : ''}
      <button class="hi-del" title="Delete" data-id="${c.id}">🗑</button>`;
    item.addEventListener('click', e => {
      if (e.target.closest('.hi-del')) return;
      loadConversation(c.id);
    });
    item.querySelector('.hi-del').addEventListener('click', async e => {
      e.stopPropagation();
      if (!confirm('删除这条对话记录？')) return;
      await deleteConversation(c.id);
      _cb.onToast('已删除');
    });
    listEl.appendChild(item);
  });
}

export async function renderRecentLanding(containerEl) {
  if (!containerEl) return;
  const { conversations } = await http.get(PATHS.history.list);
  containerEl.innerHTML = '';
  if (!conversations.length) {
    return;
  }

  conversations.slice(0, 6).forEach(c => {
    const unread = Boolean(c.proactive_unread);
    const item = document.createElement('div');
    item.className = `recent-tl-item${unread ? ' proactive-unread' : ''}`;
    item.innerHTML = `
      <span class="ri-badge ${c.mode}">${(c.mode || 'speak').toUpperCase()}</span>
      <span class="ri-title">${_esc(c.title)}</span>
      ${unread ? '<span class="ri-proactive-dot" title="Agent 主动通信 · 未回复"></span>' : ''}
      <span class="ri-time">${_relTime(c.updated_at)}</span>
      <span class="ri-arrow">›</span>`;
    item.addEventListener('click', async () => {
      document.getElementById('s-landing')?.classList.add('hidden');
      document.getElementById('s-workspace')?.classList.remove('hidden');
      await loadConversation(c.id);
    });
    containerEl.appendChild(item);
  });
}

function _defaultTitle() {
  const first = _messages.find(m => m.role === 'user');
  if (!first) return '新对话';
  const text = String(first.content ?? '');
  return text.slice(0, 48) + (text.length > 48 ? '…' : '');
}

function _esc(s) {
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

function _relTime(iso) {
  if (!iso) return '';
  const diff = (Date.now() - new Date(iso).getTime()) / 1000;
  if (diff <  60)   return '刚刚';
  if (diff <  3600) return `${Math.floor(diff / 60)} 分钟前`;
  if (diff <  86400)return `${Math.floor(diff / 3600)} 小时前`;
  return `${Math.floor(diff / 86400)} 天前`;
}
