/**
 * ui/chat/bubbles.js — 基础消息气泡：用户消息、assistant 流式气泡、
 * thread_marker、proactive banner、空态与清空。
 */

import { esc, ts, fmtThreadStamp, scrollBottom, msgsEl, renderMarkdown } from './markdown.js';
import { setTitleBarTyping } from './typing.js';
import { ensureDayDivider, resetTimeline, appendStoryEvent } from './timeline.js';

// 剧情事件条（时间轴一等公民）从本模块转发，与气泡同一插入面。
export { appendStoryEvent };

// ── Agent avatar (unified, configurable) ────────────────────────────────────

let _agentAvatar = '⚡';

export function setAgentAvatar(v) {
  _agentAvatar = v || '⚡';
}

export function agentAvatar() {
  return _agentAvatar;
}

// ── Clear / empty state ─────────────────────────────────────────────────────

export function clearMsgs() {
  const el = msgsEl();
  if (el) el.innerHTML = '';
  resetTimeline();
}

export function showEmptyState(mode = 'chat') {
  const icon = mode === 'react' ? '⚡' : '💬';
  const text = mode === 'react'
    ? 'Ask me anything — I will reason step-by-step.'
    : mode === 'speak'
      ? 'Say something — Soul will respond in real time.'
      : 'Start a conversation.';
  const el = msgsEl();
  if (!el) return;
  el.innerHTML = `<div class="empty-state"><span class="empty-icon">${icon}</span><span>${text}</span></div>`;
}

// ── User message ────────────────────────────────────────────────────────────

export function appendUserMsg(text, meta = {}) {
  const el = msgsEl();
  if (!el) return;
  ensureDayDivider(meta.created_at);
  el.querySelector('.empty-state')?.remove();
  const div = document.createElement('div');
  div.className = 'message user';
  if (meta.title_key) div.dataset.titleKey = meta.title_key;
  div.innerHTML = `
    <div class="msg-avatar">U</div>
    <div class="msg-body">
      <div class="msg-bubble">${esc(text)}</div>
      <span class="msg-time">${ts(meta.created_at)}</span>
    </div>`;
  el.appendChild(div);
  scrollBottom();
  return div;
}

/** 旧历史段分隔：title + created_at，同名 title 靠时间戳区分。 */
export function appendThreadMarker(title, createdAt, meta = {}) {
  const el = msgsEl();
  if (!el) return null;
  ensureDayDivider(createdAt);
  el.querySelector('.empty-state')?.remove();
  const div = document.createElement('div');
  div.className = 'thread-marker';
  const key = meta.title_key || `${title}@@${createdAt || ''}`;
  div.dataset.titleKey = key;
  const stamp = fmtThreadStamp(createdAt);
  div.innerHTML = `
    <div class="thread-marker-line"></div>
    <div class="thread-marker-body">
      <span class="thread-marker-title">${esc(title || '对话')}</span>
      ${stamp ? `<span class="thread-marker-time">${esc(stamp)}</span>` : ''}
    </div>
    <div class="thread-marker-line"></div>`;
  el.appendChild(div);
  scrollBottom();
  return div;
}

export function appendProactiveBanner(bannerText, meta = {}) {
  const el = msgsEl();
  if (!el) return null;
  el.querySelector('.empty-state')?.remove();
  const div = document.createElement('div');
  div.className = 'proactive-session-banner';
  div.dataset.proactiveIntentId = meta.proactiveIntentId ?? '';
  div.innerHTML = `<span class="proactive-banner-text">${esc(bannerText)}</span>`;
  el.appendChild(div);
  scrollBottom();
  return div;
}

// ── Chat assistant message ──────────────────────────────────────────────────

/**
 * Creates an assistant bubble for streaming chat output.
 * Returns a controller object.
 */
export function appendAssistantMsg(idOrOpts) {
  const opts = typeof idOrOpts === 'object' && idOrOpts !== null
    ? idOrOpts
    : { id: idOrOpts };
  const el = msgsEl();
  if (!el) return null;
  ensureDayDivider(opts.created_at);
  el.querySelector('.empty-state')?.remove();

  const div = document.createElement('div');
  div.className = 'message assistant';
  if (opts.id) div.dataset.msgId = opts.id;

  const bubble = document.createElement('div');
  bubble.className = 'msg-bubble streaming';

  const createdAt = String(opts.created_at ?? '').trim();
  const timeEl = document.createElement('span');
  timeEl.className = 'msg-time';
  timeEl.textContent = ts(createdAt || undefined);

  const ttsBtn = document.createElement('button');
  ttsBtn.className = 'msg-tts-btn hidden';
  ttsBtn.title = 'Play';
  ttsBtn.innerHTML = `<span class="sound-wave"><b></b><b></b><b></b><b></b><b></b></span>`;

  const body = document.createElement('div');
  body.className = 'msg-body';
  body.append(bubble, timeEl, ttsBtn);
  const avatar = document.createElement('div');
  avatar.className = 'msg-avatar';
  avatar.textContent = _agentAvatar;
  div.append(avatar, body);
  el.appendChild(div);
  scrollBottom();

  let _text = '';
  let _rafPending = false;
  return {
    el,
    bubble,
    append(chunk) {
      _text += chunk;
      if (!_rafPending) {
        _rafPending = true;
        requestAnimationFrame(() => {
          bubble.textContent = _text;
          scrollBottom();
          _rafPending = false;
        });
      }
    },
    finalize(aborted = false) {
      bubble.classList.remove('streaming');
      if (createdAt) timeEl.textContent = ts(createdAt);
      if (aborted) {
        bubble.innerHTML += '<br><span style="color:var(--text3);font-size:11px">⊘ aborted</span>';
      } else {
        renderMarkdown(bubble, _text);
        ttsBtn.classList.remove('hidden');
        ttsBtn.dataset.text = _text;
      }
      scrollBottom();
    },
    get text() { return _text; },
  };
}

export { scrollBottom, setTitleBarTyping };
