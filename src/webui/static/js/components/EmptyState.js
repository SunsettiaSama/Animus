/**
 * EmptyState.js — Standardised empty-state placeholder.
 *
 * Usage:
 *   import { EmptyState } from './components/EmptyState.js';
 *   el.innerHTML = EmptyState.html({ icon: '⚡', text: 'No results', hint: 'Run ...' });
 *   el.appendChild(EmptyState.create({ text: 'Nothing here' }));
 */

/** Return an HTML string for the empty state block. */
function html({ icon = '', text = 'Nothing here', hint = '', small = false } = {}) {
  return `
    <div class="app-empty${small ? ' app-empty--sm' : ''}">
      ${icon ? `<div class="app-empty-icon">${icon}</div>` : ''}
      <div class="app-empty-text">${text}</div>
      ${hint ? `<div class="app-empty-hint">${hint}</div>` : ''}
    </div>`;
}

/** Create a live DOM element. */
function create(opts = {}) {
  const div = document.createElement('div');
  div.innerHTML = html(opts);
  return div.firstElementChild;
}

export const EmptyState = { html, create };
