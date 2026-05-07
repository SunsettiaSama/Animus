/**
 * Inspector.js — Body-level fixed overlay panel.
 *
 * Single shared instance across all screens (position: fixed,
 * z-index from design.Z.inspector).  Opened by double-clicking
 * a Card row or a DAG node; closed by Escape or the ✕ button.
 *
 * Usage:
 *   import { Inspector } from './components/Inspector.js';
 *   Inspector.open({ title, badge, description, renderBody: (container) => {} });
 *   Inspector.close();
 *
 * The HTML element #plan-node-inspector must exist in index.html
 * at body level (not inside any hidden screen wrapper).
 */

const PANEL_ID = 'plan-node-inspector';

let _onClose = null;

function _panel() { return document.getElementById(PANEL_ID); }

function _bindClose() {
  const panel = _panel();
  if (!panel) return;
  panel.querySelector('#pi-close')?.addEventListener('click', close);
}

/** Open the inspector with given content. */
function open({ title = '', badge = '', description = '', renderBody } = {}) {
  const panel = _panel();
  if (!panel) return;

  const titleEl = panel.querySelector('#pi-task-id');
  const badgeEl = panel.querySelector('#pi-status');
  const descEl  = panel.querySelector('#pi-description');
  const stepsEl = panel.querySelector('#pi-steps');
  const resEl   = panel.querySelector('#pi-result');

  if (titleEl)  titleEl.textContent  = title;
  if (badgeEl)  badgeEl.textContent  = badge;
  if (descEl)   descEl.textContent   = description;
  if (stepsEl)  stepsEl.innerHTML    = '';
  if (resEl)   { resEl.innerHTML = ''; resEl.classList.add('hidden'); }

  if (renderBody && stepsEl) renderBody(stepsEl);

  panel.classList.remove('hidden');
}

/** Close and clean up the inspector. */
function close() {
  _panel()?.classList.add('hidden');
  if (_onClose) { _onClose(); _onClose = null; }
}

/** Register a callback to invoke on close (e.g. tear down SSE). */
function onClose(fn) { _onClose = fn; }

/** Append a rendered step card into the steps container. */
function appendStep(html) {
  const stepsEl = _panel()?.querySelector('#pi-steps');
  if (!stepsEl) return;
  const div = document.createElement('div');
  div.innerHTML = html;
  stepsEl.appendChild(div.firstElementChild ?? div);
  stepsEl.scrollTop = stepsEl.scrollHeight;
}

/** Show or update the result section. */
function setResult(html) {
  const resEl = _panel()?.querySelector('#pi-result');
  if (!resEl) return;
  resEl.innerHTML = html;
  resEl.classList.remove('hidden');
}

/** Return true if the inspector is currently visible. */
function isOpen() { return !(_panel()?.classList.contains('hidden') ?? true); }

/** Wire Escape key to close (call once during app boot). */
function initGlobalKeyHandler() {
  document.addEventListener('keydown', e => {
    if (e.key === 'Escape' && isOpen()) close();
  });
  _bindClose();
}

export const Inspector = {
  open,
  close,
  onClose,
  appendStep,
  setResult,
  isOpen,
  initGlobalKeyHandler,
};
