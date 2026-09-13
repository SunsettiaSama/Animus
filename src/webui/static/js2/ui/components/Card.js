/**
 * Card.js — Standardised list-row / card rendering with interaction contract:
 *   click   → calls opts.onClick(key, item)   → typically opens DetailDrawer
 *   dblclick → calls opts.onDblClick(key, item) → typically opens Inspector
 *
 * Usage:
 *   import { Card } from './components/Card.js';
 *   Card.render(containerEl, items, {
 *     key:        item => item.id,
 *     label:      item => item.name,
 *     badge:      item => StatusBadge.html(item.status),  // optional HTML string
 *     meta:       item => item.wall + ' ms',              // optional
 *     onClick:    (key, item) => DetailDrawer.open('detail-col', { title: key }),
 *     onDblClick: (key, item) => Inspector.open({ title: key }),
 *   });
 */

import { EmptyState } from './EmptyState.js';

function _esc(s) {
  return String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

/**
 * Render a list of items as app-card rows into a container.
 * @param {HTMLElement} container
 * @param {any[]} items
 * @param {{
 *   key:         (item: any) => string,
 *   label:       (item: any) => string,
 *   badge?:      (item: any) => string,
 *   meta?:       (item: any) => string,
 *   onClick?:    (key: string, item: any) => void,
 *   onDblClick?: (key: string, item: any) => void,
 *   empty?:      { icon?: string, text?: string, hint?: string },
 * }} opts
 */
function render(container, items, opts = {}) {
  if (!container) return;

  if (!items?.length) {
    container.innerHTML = EmptyState.html(opts.empty ?? { text: 'Nothing here yet' });
    return;
  }

  container.innerHTML = items.map(item => {
    const k     = _esc(opts.key(item));
    const label = _esc(opts.label(item));
    const badge = opts.badge ? opts.badge(item) : '';
    const meta  = opts.meta  ? `<span class="app-card-meta">${_esc(opts.meta(item))}</span>` : '';
    return `
      <div class="app-card" data-key="${k}">
        <span class="app-card-label">${label}</span>
        ${badge ? `<span class="app-card-badge">${badge}</span>` : ''}
        ${meta}
      </div>`;
  }).join('');

  container.querySelectorAll('.app-card').forEach((el, idx) => {
    const item = items[idx];
    const key  = opts.key(item);
    if (opts.onClick)    el.addEventListener('click',    () => opts.onClick(key, item));
    if (opts.onDblClick) el.addEventListener('dblclick', () => opts.onDblClick(key, item));
  });
}

export const Card = { render };
