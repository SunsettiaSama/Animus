/**
 * TopBar.js — Standardised top-bar for every screen.
 *
 * Every screen owns a `.app-topbar` element in its HTML.
 * TopBar.bind(screenId, opts) wires the back button and action buttons.
 * TopBar.update(screenId, { title, status }) refreshes title and badge.
 *
 * HTML convention (must be present in each screen's markup):
 *   <div class="app-topbar" data-screen="s-benchmark">
 *     <button class="app-topbar-back icon-btn">←</button>
 *     <div class="app-topbar-title">
 *       <span class="app-topbar-name"></span>
 *       <span class="app-topbar-badge"></span>
 *     </div>
 *     <div class="app-topbar-actions"></div>
 *   </div>
 */

import { StatusBadge } from './StatusBadge.js';

function _bar(screenId) {
  return document.querySelector(`.app-topbar[data-screen="${screenId}"]`);
}

/**
 * Wire the back button and optionally inject action buttons.
 * @param {string} screenId
 * @param {{ onBack?: () => void, actions?: Array<{label, id, onClick, cls}> }} opts
 */
function bind(screenId, { onBack, actions = [] } = {}) {
  const bar = _bar(screenId);
  if (!bar) return;

  const backBtn = bar.querySelector('.app-topbar-back');
  if (backBtn && onBack) backBtn.addEventListener('click', onBack);

  const actionsEl = bar.querySelector('.app-topbar-actions');
  if (actionsEl && actions.length) {
    actionsEl.innerHTML = actions.map(a =>
      `<button id="${a.id ?? ''}" class="${a.cls ?? 'btn-secondary'}">${a.label}</button>`
    ).join('');
    actions.forEach(a => {
      if (a.id && a.onClick)
        actionsEl.querySelector(`#${a.id}`)?.addEventListener('click', a.onClick);
    });
  }
}

/**
 * Update the title text and status badge of a screen's top-bar.
 * @param {string} screenId
 * @param {{ title?: string, status?: string }} opts
 */
function update(screenId, { title, status } = {}) {
  const bar = _bar(screenId);
  if (!bar) return;
  if (title !== undefined) {
    const nameEl = bar.querySelector('.app-topbar-name');
    if (nameEl) nameEl.textContent = title;
  }
  if (status !== undefined) {
    const badgeEl = bar.querySelector('.app-topbar-badge');
    if (badgeEl) StatusBadge.update(badgeEl, status);
  }
}

export const TopBar = { bind, update };
