/**
 * ui/chat/timeline.js — 时间轴排布基件（single-stream：表面按时间轴组织）。
 *
 * 流不再是逐轮 transcript：任何条目（轮次 / 剧情事件 / 卡片）插入前先保证
 * 有日期分隔条；beat 演出等"生活事件"有自己的时间轴条目形态（不含对话气泡，
 * 是时间轴上的一等公民）。纯 DOM，无外部依赖。
 *
 * 后端数据源：/api/memory/timeline 条目 kind=story（beat 演出落账，R5）。
 */

import { esc, ts, msgsEl, scrollBottom } from './markdown.js';

let _lastDayKey = '';

function _dayKey(iso) {
  const d = iso ? new Date(iso) : new Date();
  if (Number.isNaN(d.getTime())) return '';
  const p = n => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}

function _dayLabel(key) {
  const [y, m, d] = String(key).split('-').map(Number);
  if (!y || !m || !d) return key;
  const date = new Date(y, m - 1, d);
  const today = new Date();
  const yesterday = new Date();
  yesterday.setDate(today.getDate() - 1);
  const same = (a, b) => a.getFullYear() === b.getFullYear()
    && a.getMonth() === b.getMonth() && a.getDate() === b.getDate();
  const weekday = ['周日', '周一', '周二', '周三', '周四', '周五', '周六'][date.getDay()] ?? '';
  if (same(date, today)) return `今天 · ${weekday}`;
  if (same(date, yesterday)) return `昨天 · ${weekday}`;
  return `${m}月${d}日 · ${weekday}`;
}

/** 清空消息区后必须调用：分隔条状态归零。 */
export function resetTimeline() {
  _lastDayKey = '';
}

/**
 * 保证 createdAt 所在日期的分隔条存在（同日只插一条；乱序插入时以最后
 * 一条为准——消息流本身是按时间追加的）。
 */
export function ensureDayDivider(createdAt) {
  const el = msgsEl();
  const key = _dayKey(createdAt);
  if (!el || !key) return null;
  if (key === _lastDayKey) return null;
  const div = document.createElement('div');
  div.className = 'timeline-day-divider';
  div.dataset.dayKey = key;
  div.innerHTML = `
    <div class="timeline-day-line"></div>
    <span class="timeline-day-label">${esc(_dayLabel(key))}</span>
    <div class="timeline-day-line"></div>`;
  el.appendChild(div);
  _lastDayKey = key;
  return div;
}

/**
 * 剧情事件条（beat 演出 / 生活事件）：时间轴一等公民，不是聊天气泡。
 * entry: {text, at, occurred_at, kind?('story'|'story_intent'), beat_id?, card_id?, salience?}
 */
export function appendStoryEvent(entry = {}) {
  const el = msgsEl();
  if (!el) return null;
  const when = String(entry.occurred_at || entry.at || '').trim();
  ensureDayDivider(when || undefined);
  el.querySelector('.empty-state')?.remove();
  const salience = Number(entry.salience ?? 0);
  const hot = salience >= 0.7 ? '<span class="timeline-story-hot" title="高显著事件">✦</span>' : '';
  const isIntent = String(entry.kind || 'story') === 'story_intent';
  const tag = isIntent ? '意向' : '剧情';
  const dot = isIntent ? '▷' : '◐';
  const div = document.createElement('div');
  div.className = `timeline-story${isIntent ? ' timeline-story-intent' : ''}`;
  div.dataset.beatId = String(entry.beat_id || '');
  div.dataset.cardId = String(entry.card_id || '');
  div.innerHTML = `
    <div class="timeline-story-rail">
      <span class="timeline-story-dot">${dot}</span>
      <span class="timeline-story-time">${esc(ts(when || undefined))}</span>
    </div>
    <div class="timeline-story-body">
      <span class="timeline-story-tag">${tag}</span>${hot}
      <span class="timeline-story-text">${esc(String(entry.text || ''))}</span>
    </div>`;
  el.appendChild(div);
  scrollBottom();
  return div;
}
