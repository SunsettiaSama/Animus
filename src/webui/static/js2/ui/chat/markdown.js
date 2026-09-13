/**
 * ui/chat/markdown.js — Markdown 渲染与文本/时间工具。
 *
 * 依赖 CDN 全局 marked / hljs（index.html 引入）。
 */

export const esc = s => String(s ?? '')
  .replace(/&/g, '&amp;')
  .replace(/</g, '&lt;')
  .replace(/>/g, '&gt;');

export function renderMarkdown(el, text) {
  if (typeof marked === 'undefined' || !text.trim()) return;
  el.innerHTML = marked.parse(text);
  el.classList.add('md-rendered');
  el.style.whiteSpace = 'normal';
  el.querySelectorAll('pre code').forEach(b => {
    if (typeof hljs !== 'undefined') hljs.highlightElement(b);
  });
}

const _msgsEl = () => document.getElementById('msgs');

export function scrollBottom() {
  const el = _msgsEl();
  if (el) el.scrollTop = el.scrollHeight;
}

export function msgsEl() {
  return _msgsEl();
}

/** 气泡时间戳 HH:MM。 */
export function ts(iso) {
  const d = iso ? new Date(iso) : new Date();
  if (Number.isNaN(d.getTime())) {
    const now = new Date();
    return `${now.getHours().toString().padStart(2, '0')}:${now.getMinutes().toString().padStart(2, '0')}`;
  }
  return `${d.getHours().toString().padStart(2, '0')}:${d.getMinutes().toString().padStart(2, '0')}`;
}

/** thread_marker 时间戳 YYYY-MM-DD HH:MM。 */
export function fmtThreadStamp(iso) {
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
