/**
 * history.js — Conversation CRUD and sidebar rendering.
 *
 * All persistence goes through /api/history/*.
 * UI callbacks are provided by main.js via setCallbacks().
 */

import { http, PATHS } from './api.js';
import { S, set }      from './state.js';

// ── Callbacks (wired by main.js) ──────────────────────────────────────────────

const _cb = {
  onLoad:   () => {},   // (messages, mode) — rebuild the UI message list
  onToast:  () => {},   // (text)
};

export function setCallbacks(cbs) {
  Object.assign(_cb, cbs);
}

// ── In-memory conversation state ──────────────────────────────────────────────

let _messages = [];      // [{role, content, …}]

export function getMessages() { return _messages; }

export function pushMessage(msg) {
  _messages.push(msg);
}

export function clearMessages() {
  _messages = [];
}

// ── CRUD ──────────────────────────────────────────────────────────────────────

export async function saveConversation() {
  if (!_messages.length) return;
  const now    = new Date().toISOString();
  const convId = S.convId ?? crypto.randomUUID();
  const title  = S.convTitle || _defaultTitle();
  await http.post(PATHS.history.item(convId), {
    id:         convId,
    title,
    mode:       S.mode,
    messages:   _messages,
    created_at: S._createdAt ?? now,
    updated_at: now,
  });
  if (!S.convId) {
    set('convId', convId);
    set('_createdAt', now);
  }
  await renderSidebar();
}

export async function loadConversation(convId) {
  const data = await http.get(PATHS.history.item(convId));
  set('convId',    data.id);
  set('convTitle', data.title);
  set('mode',      data.mode ?? 'chat');
  _messages = data.messages ?? [];
  _cb.onLoad(_messages, S.mode);
}

export async function deleteConversation(convId) {
  await http.del(PATHS.history.item(convId));
  if (S.convId === convId) {
    set('convId', null);
    set('convTitle', 'New Conversation');
    clearMessages();
  }
  await renderSidebar();
}

export async function clearAllHistory() {
  await http.del(PATHS.history.list);
  set('convId', null);
  set('convTitle', 'New Conversation');
  clearMessages();
  await renderSidebar();
}

// ── Sidebar rendering ─────────────────────────────────────────────────────────

export async function renderSidebar() {
  const listEl = document.getElementById('sidebar-list');
  if (!listEl) return;

  const { conversations } = await http.get(PATHS.history.list);
  if (!conversations.length) {
    listEl.innerHTML = '<div class="sidebar-empty">No history yet</div>';
    return;
  }

  listEl.innerHTML = '';
  conversations.forEach(c => {
    const icon = c.mode === 'react' ? '⚡' : '💬';
    const item = document.createElement('div');
    item.className = `hist-item${c.id === S.convId ? ' active' : ''}`;
    item.dataset.id = c.id;
    item.innerHTML = `
      <span class="hi-icon">${icon}</span>
      <div class="hi-body">
        <div class="hi-title">${_esc(c.title)}</div>
        <div class="hi-meta">${_relTime(c.updated_at)}</div>
      </div>
      <button class="hi-del" title="Delete" data-id="${c.id}">🗑</button>`;
    item.addEventListener('click', e => {
      if (e.target.closest('.hi-del')) return;
      loadConversation(c.id);
    });
    item.querySelector('.hi-del').addEventListener('click', async e => {
      e.stopPropagation();
      if (!confirm('Delete this conversation?')) return;
      await deleteConversation(c.id);
      _cb.onToast('Conversation deleted');
    });
    listEl.appendChild(item);
  });
}

// ── Landing page recent list ──────────────────────────────────────────────────

export async function renderRecentLanding(containerEl) {
  const { conversations } = await http.get(PATHS.history.list);
  if (!conversations.length) { containerEl.innerHTML = ''; return; }

  const label = document.createElement('div');
  label.className = 'recent-label';
  label.textContent = 'Recent';
  containerEl.innerHTML = '';
  containerEl.appendChild(label);

  conversations.slice(0, 6).forEach(c => {
    const item = document.createElement('div');
    item.className = 'recent-tl-item';
    item.innerHTML = `
      <span class="ri-badge ${c.mode}">${c.mode.toUpperCase()}</span>
      <span class="ri-title">${_esc(c.title)}</span>
      <span class="ri-time">${_relTime(c.updated_at)}</span>
      <span class="ri-arrow">›</span>`;
    item.addEventListener('click', () => {
      document.getElementById('s-landing')?.classList.add('hidden');
      document.getElementById('s-workspace')?.classList.remove('hidden');
      loadConversation(c.id);
    });
    containerEl.appendChild(item);
  });
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function _defaultTitle() {
  const first = _messages.find(m => m.role === 'user');
  if (!first) return 'Untitled';
  return first.content.slice(0, 48) + (first.content.length > 48 ? '…' : '');
}

function _esc(s) {
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

function _relTime(iso) {
  if (!iso) return '';
  const diff = (Date.now() - new Date(iso).getTime()) / 1000;
  if (diff <  60)   return 'just now';
  if (diff <  3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff <  86400)return `${Math.floor(diff / 3600)}h ago`;
  return `${Math.floor(diff / 86400)}d ago`;
}
