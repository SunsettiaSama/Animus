/**
 * DetailDrawer.js — Inline sliding detail panel (third flex column).
 *
 * Unlike Inspector (position:fixed overlay), DetailDrawer expands as a
 * third column inside the screen's flex layout — it pushes content left
 * rather than covering it.
 *
 * Usage:
 *   import { DetailDrawer } from './components/DetailDrawer.js';
 *   DetailDrawer.bind('bench-detail-col', { closeId: 'bench-detail-close' });
 *   DetailDrawer.open('bench-detail-col', { title: 'scenario-name',
 *     fetchContent: async () => '<div>html</div>' });
 *   DetailDrawer.close('bench-detail-col');
 *
 * HTML convention:
 *   <div class="app-drawer hidden" id="XXX-detail-col">
 *     <div class="app-drawer-topbar">
 *       <span class="app-drawer-title" id="XXX-detail-title">—</span>
 *       <button id="XXX-detail-close" class="icon-btn">✕</button>
 *     </div>
 *     <div class="app-drawer-body" id="XXX-detail-body">...</div>
 *   </div>
 */

const _active = new Map();   // drawerId → { name }

/**
 * Wire close button for a drawer.
 * @param {string} drawerId  DOM id of the drawer element.
 * @param {{ closeId?: string, onClose?: () => void }} opts
 */
function bind(drawerId, { closeId, onClose } = {}) {
  if (closeId) {
    document.getElementById(closeId)?.addEventListener('click', () => close(drawerId));
  }
  if (onClose) _active.set(drawerId, { onClose });
}

/**
 * Open a drawer and load content.
 * @param {string} drawerId
 * @param {{ title?: string, bodyId?: string,
 *            fetchContent?: () => Promise<string> }} opts
 */
async function open(drawerId, { title, bodyId, fetchContent } = {}) {
  const drawer = document.getElementById(drawerId);
  if (!drawer) return;

  const titleEl = drawer.querySelector('.app-drawer-title');
  if (title !== undefined && titleEl) titleEl.textContent = title;

  drawer.classList.remove('hidden');

  if (fetchContent) {
    const body = bodyId
      ? document.getElementById(bodyId)
      : drawer.querySelector('.app-drawer-body');
    if (body) {
      body.innerHTML = '<div class="app-drawer-loading">Loading…</div>';
      body.innerHTML = await fetchContent().catch(() => '<div class="app-drawer-error">Failed to load.</div>');
    }
  }
}

/**
 * Close a drawer.
 * @param {string} drawerId
 */
function close(drawerId) {
  document.getElementById(drawerId)?.classList.add('hidden');
  const stored = _active.get(drawerId);
  if (stored?.onClose) stored.onClose();
}

/** Return whether the drawer is currently open. */
function isOpen(drawerId) {
  return !document.getElementById(drawerId)?.classList.contains('hidden');
}

export const DetailDrawer = { bind, open, close, isOpen };
