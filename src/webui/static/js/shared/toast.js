/**
 * shared/toast.js — Application-wide toast notification.
 *
 * Listens to bus event 'toast' so any module can trigger a toast
 * without importing this file directly.
 *
 * Usage:
 *   import { showToast, initToast } from './shared/toast.js';
 *   showToast('Hello!');
 *   initToast();   // call once in app.js to wire bus listener
 */

import { bus } from '../eventBus.js';

let _timer = null;

export function showToast(text) {
  const el = document.getElementById('toast');
  if (!el) return;
  el.textContent = text;
  el.classList.add('show');
  clearTimeout(_timer);
  _timer = setTimeout(() => el.classList.remove('show'), 2500);
}

/** Wire the bus 'toast' event and legacy window CustomEvent. */
export function initToast() {
  bus.on('toast', showToast);
  window.addEventListener('react:toast', e => showToast(e.detail));
}
