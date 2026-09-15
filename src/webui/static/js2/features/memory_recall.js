/**
 * features/memory_recall.js — 回忆面板（single-stream R2）。
 *
 * "看过去" = 记忆检索，不是会话列表：侧栏不再展示对话线程，改为展示
 * 记忆时间轴（/api/memory/timeline，append-only 轮次流水的读模型）。
 * 本模块只读不写；剧情卡片（R8）在 workspace 流内渲染，不在此。
 */

import { http } from '../transport/http.js';
import { API } from '../protocol/http_api.js';
import * as sessionStore from '../store/session_store.js';
import { esc } from '../ui/chat/markdown.js';

const PAGE_SIZE = 30;

let _cursor = '';
let _hasMore = false;
let _loading = false;
let _mounted = false;

function _channel() {
  const st = sessionStore.state();
  const ch = String(st?.channelId || 'main');
  return ch.replace(/^live:/, '') || 'main';
}

function _fmt(iso) {
  if (!iso) return '';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return String(iso);
  const p = n => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
}

async function _fetchPage(before = '') {
  const qs = new URLSearchParams({ channel: _channel(), limit: String(PAGE_SIZE) });
  if (before) qs.set('before', before);
  return http.get(`${API.memory.timeline}?${qs.toString()}`);
}

function _itemEl(entry) {
  const div = document.createElement('div');
  div.className = 'recall-item';
  const salience = Number(entry.salience ?? 0);
  const hot = salience >= 0.7 ? '<span class="recall-hot" title="高显著记忆">✦</span>' : '';
  const timeHtml = `<div class="recall-time">${esc(_fmt(entry.at))}${hot}</div>`;
  // 剧情事件/意向条目（beat 演出与改期落账，R5/R7）：单行呈现，非对话轮
  const kind = String(entry.kind);
  if (kind === 'story' || kind === 'story_intent') {
    const mark = kind === 'story_intent' ? '▷' : '◐';
    div.innerHTML = `${timeHtml}
      <div class="recall-story">${mark} ${esc(String(entry.text || '').slice(0, 240))}</div>`;
    return div;
  }
  div.innerHTML = `${timeHtml}
    <div class="recall-user">${esc(String(entry.user_text || '').slice(0, 200) || '（无声的一轮）')}</div>
    <div class="recall-agent">${esc(String(entry.agent_text || '').slice(0, 200))}</div>`;
  return div;
}

function _listEl() {
  return document.getElementById('sidebar-list');
}

/** 渲染一页；reset=true 重新从头取。 */
export async function refresh(reset = true) {
  const el = _listEl();
  if (!el || _loading) return;
  _loading = true;
  if (reset) {
    _cursor = '';
    _hasMore = false;
    el.innerHTML = '<div class="recall-empty">正在取回回忆…</div>';
  }
  try {
    const data = await _fetchPage(reset ? '' : _cursor);
    const items = Array.isArray(data?.items) ? data.items : [];
    if (reset) el.innerHTML = '';
    if (!items.length && reset) {
      el.innerHTML = '<div class="recall-empty">还没有记忆——去和她聊点什么吧。</div>';
    }
    for (const entry of items) el.appendChild(_itemEl(entry));
    _cursor = String(data?.next_before || '');
    _hasMore = Boolean(_cursor);
    if (!reset && !_hasMore) {
      el.querySelector('.recall-more')?.remove();
      const end = document.createElement('div');
      end.className = 'recall-empty';
      end.textContent = '—— 更早的事，她记得的不多了 ——';
      el.appendChild(end);
    }
    if (_hasMore && !el.querySelector('.recall-more')) {
      const more = document.createElement('button');
      more.className = 'recall-more';
      more.textContent = '回忆更早';
      more.addEventListener('click', () => refresh(false));
      el.appendChild(more);
    }
  } catch (err) {
    if (reset) el.innerHTML = `<div class="recall-empty">回忆暂不可用（${esc(err?.message || err)}）</div>`;
  } finally {
    _loading = false;
  }
}

/** 挂载侧栏（workspace 初始化时调用一次）。 */
export function mountSidebar() {
  if (_mounted) return;
  _mounted = true;
  document.getElementById('btn-recall-refresh')?.addEventListener('click', () => refresh(true));
  refresh(true);
}
