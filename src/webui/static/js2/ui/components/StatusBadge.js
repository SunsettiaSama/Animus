/**
 * StatusBadge.js — Canonical status indicator.
 *
 * Usage:
 *   import { StatusBadge } from './components/StatusBadge.js';
 *   el.innerHTML = StatusBadge.html('running');
 *   StatusBadge.update(el, 'pass');
 */

import { STATUS } from './design.js';

function _entry(status) {
  const s = String(status ?? '').toLowerCase();
  return STATUS[s] ?? { label: s.toUpperCase(), cls: 'idle', pulse: false };
}

/** Return an HTML string for the badge. */
function html(status) {
  const e = _entry(status);
  return `<span class="app-badge app-badge--${e.cls}${e.pulse ? ' app-badge--pulse' : ''}">${e.label}</span>`;
}

/** Update an existing badge element in-place. */
function update(el, status) {
  if (!el) return;
  const e = _entry(status);
  el.className = `app-badge app-badge--${e.cls}${e.pulse ? ' app-badge--pulse' : ''}`;
  el.textContent = e.label;
}

/** Create a live DOM element. */
function create(status) {
  const span = document.createElement('span');
  update(span, status);
  return span;
}

export const StatusBadge = { html, update, create };
