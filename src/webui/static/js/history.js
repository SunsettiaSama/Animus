/**
 * history.js — 前端对话历史（展示/归档），与后端 Speak session 解耦。
 *
 * - convId：历史线程 ID（列表、持久化主键）
 * - sessionId：Speak 生命线（live:channelId），多对话页共享
 * - channelId：记忆渠道（认人绑定），多线程共享，见 channel.js
 *
 * HISTORY_BYPASS：临时旁路多线程历史。前端表现为微信式连续会话。
 */

import { http, PATHS } from './api.js';
import { S, set }      from './state.js';
import { getChannelId, isLiveSessionId, speakLiveSessionId } from './channel.js';
import * as workStore  from './work/store.js';

/** 临时：取消历史切分，所有消息在同一连续会话展示。 */
export const HISTORY_BYPASS = false;

/** @typedef {'time_desc'|'time_asc'|'title_asc'|'title_desc'} HistorySortMode */
const _SORT_STORAGE_KEY = 'react.history.sortMode';

/** @type {HistorySortMode} */
let _sortMode = _loadSortMode();

function _loadSortMode() {
  const raw = String(localStorage.getItem(_SORT_STORAGE_KEY) || 'time_desc').trim();
  if (['time_desc', 'time_asc', 'title_asc', 'title_desc'].includes(raw)) return raw;
  return 'time_desc';
}

export function getHistorySortMode() {
  return _sortMode;
}

export function setHistorySortMode(mode) {
  const next = String(mode || '').trim();
  if (!['time_desc', 'time_asc', 'title_asc', 'title_desc'].includes(next)) return _sortMode;
  _sortMode = next;
  localStorage.setItem(_SORT_STORAGE_KEY, next);
  return _sortMode;
}

function _sortConversations(list) {
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

function _sortMarkers(markers) {
  const items = Array.isArray(markers) ? [...markers] : [];
  const mode = _sortMode;
  items.sort((a, b) => {
    if (mode === 'title_asc' || mode === 'title_desc') {
      const cmp = String(a.title || a.content || '').localeCompare(
        String(b.title || b.content || ''),
        'zh-CN',
        { sensitivity: 'base' },
      );
      if (cmp !== 0) return mode === 'title_asc' ? cmp : -cmp;
      const ta = Date.parse(a.created_at || '') || 0;
      const tb = Date.parse(b.created_at || '') || 0;
      return mode === 'title_asc' ? ta - tb : tb - ta;
    }
    const ta = Date.parse(a.created_at || '') || 0;
    const tb = Date.parse(b.created_at || '') || 0;
    return mode === 'time_asc' ? ta - tb : tb - ta;
  });
  return items;
}

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
  onOpenConversation: async (convId) => {
    await loadConversation(convId);
  },
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
  const now = new Date().toISOString();
  _messages.push({
    ...msg,
    created_at: msg?.created_at || now,
  });
}

/** title 身份：同名标题靠 created_at 区分，避免合并。 */
export function titleKey(title, createdAt) {
  return `${String(title ?? '').trim()}@@${String(createdAt ?? '').trim()}`;
}

function _stampFromConversation(data) {
  const createdAt = String(data?.created_at || data?.updated_at || '').trim();
  const title = String(data?.title || '对话').trim() || '对话';
  const key = titleKey(title, createdAt);
  return { title, createdAt, key, convId: String(data?.id || '') };
}

/**
 * 连续会话旁路：把旧历史按时间戳拼成一条流。
 * 每条消息带 created_at / source_title / title_key 元数据，
 * 段首插入 thread_marker（title + created_at），同名 title 不会并成一段。
 */
export async function hydrateContinuousFromHistory() {
  if (!HISTORY_BYPASS) return false;
  if (_messages.length) return false;

  const { conversations } = await http.get(PATHS.history.list);
  const list = Array.isArray(conversations) ? [...conversations] : [];
  // 连续流本体永远按时间旧→新拼接；侧栏索引才用用户选择的排序
  list.sort((a, b) => {
    const ta = Date.parse(a.created_at || a.updated_at || '') || 0;
    const tb = Date.parse(b.created_at || b.updated_at || '') || 0;
    return ta - tb;
  });

  const merged = [];
  for (const item of list) {
    const data = await http.get(PATHS.history.item(item.id));
    const stamp = _stampFromConversation(data);
    merged.push({
      role: 'thread_marker',
      content: stamp.title,
      title: stamp.title,
      created_at: stamp.createdAt,
      title_key: stamp.key,
      source_conv_id: stamp.convId,
    });
    for (const m of (data.messages || [])) {
      if (!m || (m.role !== 'user' && m.role !== 'assistant')) continue;
      merged.push({
        ...m,
        created_at: m.created_at || stamp.createdAt,
        source_title: stamp.title,
        source_created_at: stamp.createdAt,
        source_conv_id: stamp.convId,
        title_key: stamp.key,
      });
    }
  }

  _messages = merged;
  ensureActiveConversation();
  const latest = list.length ? list[list.length - 1] : null;
  if (latest?.channel_id) set('channelId', latest.channel_id);
  set('convTitle', '连续会话');
  const tb = document.getElementById('tb-title');
  if (tb) tb.textContent = '连续会话';
  _cb.onLoad(_messages, []);
  await renderSidebar();
  return true;
}

export function clearMessages() {
  _messages = [];
}

export function newIds() {
  const channelId = getChannelId();
  return {
    convId:    crypto.randomUUID(),
    sessionId: speakLiveSessionId(channelId),
    channelId,
  };
}

/** 当前线程无记录时创建；返回是否新建。 */
export function ensureActiveConversation() {
  if (S.convId && S.sessionId) return false;
  const ids = newIds();
  set('convId', ids.convId);
  set('sessionId', ids.sessionId);
  set('channelId', ids.channelId);
  set('convTitle', HISTORY_BYPASS ? '连续会话' : '新对话');
  set('_createdAt', new Date().toISOString());
  return true;
}

export async function saveConversation(extra = {}) {
  if (!_messages.length) return;
  ensureActiveConversation();
  const title = _defaultTitle();
  set('convTitle', title);
  const tb = document.getElementById('tb-title');
  if (tb) tb.textContent = title;

  if (extra.clearProactiveUnread === true) {
    set('proactiveUnread', false);
    set('proactiveUrge', false);
  } else if (extra.proactiveUnread === true || extra.agentInitiated === true) {
    set('proactiveUnread', true);
    set('proactiveUrge', true);
  }

  const persist = extra.forcePersist === true || !HISTORY_BYPASS;
  if (!persist) {
    return;
  }

  const now = new Date().toISOString();
  const convId = S.convId;
  const agentInitiated = Boolean(
    extra.agentInitiated ?? S.proactiveUrge ?? _messages.some(m => m.agent_initiated),
  );
  const proactiveUnread = Boolean(S.proactiveUnread);
  await http.post(PATHS.history.item(convId), {
    id:         convId,
    title,
    mode:       'conversation',
    messages:   _messages,
    work_items: workStore.summariesForHistory(),
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

export async function findConversationForChannel(channelId) {
  const ch = String(channelId || '').trim();
  if (!ch) return null;
  const { conversations } = await http.get(PATHS.history.list);
  const sorted = _sortConversations(conversations).filter(
    item => String(item.channel_id || '').trim() === ch,
  );
  return sorted.find(item => Boolean(item.proactive_unread)) || sorted[0] || null;
}

export async function loadConversation(convId) {
  const id = String(convId ?? '').trim();
  if (!id) {
    throw new Error('history conv_id required');
  }
  const data = await http.get(PATHS.history.item(id));
  const isProactive = Boolean(data.agent_initiated || data.proactive_unread);
  if (HISTORY_BYPASS && !isProactive) {
    return;
  }
  await _cb.onBeforeSwitch();
  if (S.convId && S.convId !== convId && _messages.length) {
    await saveConversation().catch(() => {});
  }
  set('convId', data.id);
  set('convTitle', data.title);
  set('convMode', 'conversation');
  // Speak 生命线固定为 channel live id；历史页 session_id 仅作归档字段
  const channelId = data.channel_id || getChannelId();
  set('channelId', channelId);
  set('sessionId', speakLiveSessionId(channelId));
  const unread = Boolean(data.proactive_unread);
  set('proactiveUnread', unread);
  set('proactiveUrge', unread);
  set('_createdAt', data.created_at || '');
  _messages = data.messages ?? [];
  workStore.restoreFromHistory(data.work_items ?? []);
  const tb = document.getElementById('tb-title');
  if (tb) tb.textContent = data.title || '对话';
  _cb.onLoad(_messages, data.work_items ?? []);
  if (unread) {
    set('proactiveUnread', false);
    set('proactiveUrge', false);
    await saveConversation({ clearProactiveUnread: true, forcePersist: true });
    return;
  }
  await renderSidebar();
}

export async function deleteConversation(convId) {
  if (HISTORY_BYPASS) return;
  await http.del(PATHS.history.item(convId));
  if (S.convId === convId) {
    set('convId', null);
    set('sessionId', null);
    set('convTitle', '新对话');
    clearMessages();
    workStore.clear();
    _cb.onLoad([]);
  }
  await renderSidebar();
}

export async function clearAllHistory() {
  if (HISTORY_BYPASS) {
    clearMessages();
    workStore.clear();
    _cb.onLoad([]);
    await renderSidebar();
    return;
  }
  await http.del(PATHS.history.list);
  set('convId', null);
  set('sessionId', null);
  set('convTitle', '新对话');
  clearMessages();
  workStore.clear();
  _cb.onLoad([]);
  await renderSidebar();
}

/** 新对话只创建历史线程；Speak 仍复用同一 channel 生命线。 */
export async function beginNewConversation({ resetBackend = false } = {}) {
  if (HISTORY_BYPASS) {
    // 旁路：不切线程、不重置后端；首次把旧历史按时间戳拼进连续流
    ensureActiveConversation();
    await hydrateContinuousFromHistory();
    const tb = document.getElementById('tb-title');
    if (tb) tb.textContent = S.convTitle || '连续会话';
    await renderSidebar();
    return;
  }
  await _cb.onBeforeSwitch();
  if (S.convId && _messages.length) {
    await saveConversation().catch(() => {});
  }
  const ids = newIds();
  set('convId', ids.convId);
  set('sessionId', ids.sessionId);
  set('channelId', ids.channelId);
  set('convTitle', '新对话');
  set('convMode', 'conversation');
  set('_createdAt', new Date().toISOString());
  clearMessages();
  workStore.clear();
  if (resetBackend) {
    await resetBackendSession(ids.sessionId).catch(err => {
      console.warn('[speak] reset backend session skipped', {
        session_id: ids.sessionId,
        error: err?.message ?? String(err),
      });
    });
  }
  const tb = document.getElementById('tb-title');
  if (tb) tb.textContent = '新对话';
  await renderSidebar();
}

export async function noteProactiveConversation(payload) {
  const sessionId = String(payload?.session_id ?? '').trim();
  if (!sessionId) return;
  await renderSidebar();
  await renderRecentLanding(document.getElementById('landing-recent'));
}

function _conversationItem(c) {
  const item = document.createElement('div');
  const proactive = Boolean(c.agent_initiated);
  const unread = Boolean(c.proactive_unread);
  item.className = `hist-item${c.id === S.convId ? ' active' : ''}${proactive ? ' proactive-urge' : ''}`;
  item.dataset.id = c.id;
  item.innerHTML = `
    <span class="hi-icon">💬</span>
    <div class="hi-body">
      <div class="hi-title">${_esc(c.title)}</div>
      <div class="hi-meta">${_esc(_fmtStamp(c.created_at) || _relTime(c.updated_at))}</div>
    </div>
    ${unread ? '<span class="hi-proactive-dot" title="Agent 主动通信 · 未回复"></span>' : ''}
    <button class="hi-del" title="Delete" data-id="${c.id}">🗑</button>`;
  item.addEventListener('click', e => {
    if (e.target.closest('.hi-del')) return;
    void _cb.onOpenConversation(c.id);
  });
  item.querySelector('.hi-del').addEventListener('click', async e => {
    e.stopPropagation();
    if (!confirm('删除这条对话记录？')) return;
    await deleteConversation(c.id);
    _cb.onToast('已删除');
  });
  return item;
}

async function _unreadProactiveConversations() {
  const { conversations } = await http.get(PATHS.history.list);
  return _sortConversations(conversations).filter(c => Boolean(c.proactive_unread));
}

export async function renderSidebar() {
  const listEl = document.getElementById('sidebar-list');
  if (!listEl) return;

  const sortEl = document.getElementById('sidebar-sort-mode');
  if (sortEl && sortEl.value !== _sortMode) sortEl.value = _sortMode;

  if (HISTORY_BYPASS) {
    const unread = await _unreadProactiveConversations();
    const markers = _sortMarkers(_messages.filter(m => m.role === 'thread_marker'));
    listEl.innerHTML = '';
    unread.forEach(c => listEl.appendChild(_conversationItem(c)));
    if (!unread.length && !markers.length) {
      listEl.innerHTML = '<div class="sidebar-empty">连续会话模式<br><span style="opacity:.7">暂无旧历史</span></div>';
      return;
    }
    if (markers.length) {
      const label = document.createElement('div');
      label.className = 'sidebar-empty';
      label.style.marginBottom = '8px';
      label.textContent = '连续会话 · 旧段索引';
      listEl.appendChild(label);
      markers.forEach(m => {
        const item = document.createElement('div');
        item.className = 'hist-item';
        item.dataset.titleKey = m.title_key || titleKey(m.title, m.created_at);
        item.innerHTML = `
          <span class="hi-icon">💬</span>
          <div class="hi-body">
            <div class="hi-title">${_esc(m.title || m.content || '对话')}</div>
            <div class="hi-meta">${_esc(_fmtStamp(m.created_at))}</div>
          </div>`;
        item.addEventListener('click', () => {
          const el = document.querySelector(
            `[data-title-key="${CSS.escape(item.dataset.titleKey)}"]`,
          );
          el?.scrollIntoView({ behavior: 'smooth', block: 'start' });
        });
        listEl.appendChild(item);
      });
    }
    return;
  }

  const { conversations } = await http.get(PATHS.history.list);
  const sorted = _sortConversations(conversations);

  listEl.innerHTML = '';

  if (!sorted.length) {
    listEl.innerHTML = '<div class="sidebar-empty">暂无历史对话</div>';
    return;
  }

  sorted.forEach(c => listEl.appendChild(_conversationItem(c)));
}

export async function renderRecentLanding(containerEl) {
  if (!containerEl) return;
  const { conversations } = await http.get(PATHS.history.list);
  const sorted = HISTORY_BYPASS
    ? _sortConversations(conversations).filter(c => Boolean(c.proactive_unread))
    : _sortConversations(conversations);
  containerEl.innerHTML = '';
  if (!sorted.length) {
    return;
  }

  sorted.slice(0, 6).forEach(c => {
    const unread = Boolean(c.proactive_unread);
    const item = document.createElement('div');
    item.className = `recent-tl-item${unread ? ' proactive-unread' : ''}`;
    item.innerHTML = `
      <span class="ri-badge conversation">对话</span>
      <span class="ri-title">${_esc(c.title)}</span>
      ${unread ? '<span class="ri-proactive-dot" title="Agent 主动通信 · 未回复"></span>' : ''}
      <span class="ri-time">${_esc(_fmtStamp(c.created_at) || _relTime(c.updated_at))}</span>
      <span class="ri-arrow">›</span>`;
    item.addEventListener('click', async () => {
      const { goWorkspace } = await import('./router.js');
      goWorkspace();
      await _cb.onOpenConversation(c.id);
    });
    containerEl.appendChild(item);
  });
}

function _defaultTitle() {
  const proactive = _messages.find(
    message => message.role === 'assistant' && message.agent_initiated,
  );
  const hasUser = _messages.some(m => m.role === 'user');
  if (proactive && !hasUser) {
    if (S.convTitle && S.convTitle !== '新对话' && S.convTitle !== '连续会话') {
      return S.convTitle;
    }
    const proactiveText = String(proactive.content ?? '');
    return proactiveText.slice(0, 48) + (proactiveText.length > 48 ? '…' : '');
  }
  if (HISTORY_BYPASS) return '连续会话';
  const first = _messages.find(m => m.role === 'user');
  if (!first) return '新对话';
  const text = String(first.content ?? '');
  return text.slice(0, 48) + (text.length > 48 ? '…' : '');
}

function _esc(s) {
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

function _fmtStamp(iso) {
  if (!iso) return '';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return String(iso);
  const y = d.getFullYear();
  const mo = String(d.getMonth() + 1).padStart(2, '0');
  const da = String(d.getDate()).padStart(2, '0');
  const h = String(d.getHours()).padStart(2, '0');
  const mi = String(d.getMinutes()).padStart(2, '0');
  return `${y}-${mo}-${da} ${h}:${mi}`;
}

function _relTime(iso) {
  if (!iso) return '';
  const diff = (Date.now() - new Date(iso).getTime()) / 1000;
  if (diff <  60)   return '刚刚';
  if (diff <  3600) return `${Math.floor(diff / 60)} 分钟前`;
  if (diff <  86400)return `${Math.floor(diff / 3600)} 小时前`;
  return `${Math.floor(diff / 86400)} 天前`;
}
