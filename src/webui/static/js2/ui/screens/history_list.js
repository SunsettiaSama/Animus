/**
 * ui/screens/history_list.js — 历史侧栏与 Landing 最近列表渲染。
 *
 * 纯渲染：数据来自 history_store（订阅 history:changed），点击意图回调
 * features/conversation 的 openConversation。删除确认后经 store 删除。
 */

import { bus, EVENTS } from '../../store/bus.js';
import * as historyStore from '../../store/history_store.js';
import * as sessionStore from '../../store/session_store.js';
import { esc } from '../chat/markdown.js';

const _id = id => document.getElementById(id);

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
  if (diff < 60) return '刚刚';
  if (diff < 3600) return `${Math.floor(diff / 60)} 分钟前`;
  if (diff < 86400) return `${Math.floor(diff / 3600)} 小时前`;
  return `${Math.floor(diff / 86400)} 天前`;
}

function _conversationItem(c, activeId, onOpen) {
  const item = document.createElement('div');
  const proactive = Boolean(c.agent_initiated);
  const unread = Boolean(c.proactive_unread);
  item.className = `hist-item${c.id === activeId ? ' active' : ''}${proactive ? ' proactive-urge' : ''}`;
  item.dataset.id = c.id;
  item.innerHTML = `
    <span class="hi-icon">💬</span>
    <div class="hi-body">
      <div class="hi-title">${esc(c.title)}</div>
      <div class="hi-meta">${esc(_fmtStamp(c.created_at) || _relTime(c.updated_at))}</div>
    </div>
    ${unread ? '<span class="hi-proactive-dot" title="Agent 主动通信 · 未回复"></span>' : ''}
    <button class="hi-del" title="Delete" data-id="${esc(c.id)}">🗑</button>`;
  item.addEventListener('click', e => {
    if (e.target.closest('.hi-del')) return;
    onOpen?.(c.id);
  });
  item.querySelector('.hi-del')?.addEventListener('click', async e => {
    e.stopPropagation();
    if (!confirm('删除这条对话记录？')) return;
    await historyStore.deleteConversation(c.id);
    bus.emit(EVENTS.toastShow, '已删除');
  });
  return item;
}

export function renderSidebar(conversations, activeConvId, onOpen) {
  const listEl = _id('sidebar-list');
  if (!listEl) return;
  listEl.innerHTML = '';
  if (!conversations.length) {
    listEl.innerHTML = '<div class="sidebar-empty">暂无历史对话</div>';
    return;
  }
  conversations.forEach(c => listEl.appendChild(_conversationItem(c, activeConvId, onOpen)));
}

export function renderRecentLanding(containerEl, conversations, onOpen) {
  if (!containerEl) return;
  containerEl.innerHTML = '';
  const sorted = (conversations || []).slice(0, 6);
  sorted.forEach(c => {
    const unread = Boolean(c.proactive_unread);
    const item = document.createElement('div');
    item.className = `recent-tl-item${unread ? ' proactive-unread' : ''}`;
    item.innerHTML = `
      <span class="ri-badge conversation">对话</span>
      <span class="ri-title">${esc(c.title)}</span>
      ${unread ? '<span class="ri-proactive-dot" title="Agent 主动通信 · 未回复"></span>' : ''}
      <span class="ri-time">${esc(_fmtStamp(c.created_at) || _relTime(c.updated_at))}</span>
      <span class="ri-arrow">›</span>`;
    item.addEventListener('click', () => onOpen?.(c.id));
    containerEl.appendChild(item);
  });
}

let _onOpen = null;

/** app 装配：注入「打开会话」动作并订阅列表变更。 */
export function initHistoryLists(onOpen) {
  _onOpen = onOpen;
  bus.on(EVENTS.historyChanged, ({ conversations } = {}) => {
    renderSidebar(
      conversations ?? [],
      sessionStore.state().convId,
      _onOpen,
    );
    renderRecentLanding(_id('landing-recent'), conversations ?? [], _onOpen);
  });
}
