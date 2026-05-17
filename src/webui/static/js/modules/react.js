/**
 * modules/react.js — ReAct agent init, status, memory/persona clear.
 *
 * Issue 5 fix: settings saved mid-session apply to the NEXT turn only.
 *   - history is preserved as-is (server keeps conv_loop / PromptManager intact).
 *   - If user wants the new config to take effect NOW they must click "Reinit".
 *   - init() uses /api/react/reinit which is guarded by is_streaming on server.
 *
 * Notifies main.js via callbacks only — no direct DOM or showToast calls.
 */

import { http, PATHS, pollUntilReady } from '../api.js';
import { S, set }                       from '../state.js';

const _cb = {
  onToast:       () => {},
  onReady:       () => {},
  onError:       () => {},
  onStatusUpdate:() => {},
};
export function setCallbacks(cbs) { Object.assign(_cb, cbs); }

// ── Init (guarded — Issue 2 compat) ──────────────────────────────────────────

/**
 * POST /api/react/reinit, then poll until ready.
 * Returns true on success, false if server rejects (streaming active).
 */
export async function init(payload) {
  const resp = await fetch(PATHS.react.reinit, {
    method:  'POST',
    headers: { 'Content-Type': 'application/json' },
    body:    JSON.stringify(payload),
  });
  const data = await resp.json();
  if (!resp.ok) {
    _cb.onToast(data.error ?? 'Cannot reinitialize while streaming');
    return false;
  }
  set('reactReady', false);
  _cb.onToast('ReAct initializing…');

  pollUntilReady()
    .then(() => {
      set('reactReady', true);
      _cb.onReady();
      _cb.onToast('ReAct ready');
    })
    .catch(e => {
      _cb.onError(e.message);
      _cb.onToast('ReAct init failed: ' + e.message);
    });
  return true;
}

// ── Status ────────────────────────────────────────────────────────────────────

export async function fetchStatus() {
  const data = await http.get(PATHS.react.status);
  set('reactReady', data.status === 'ready');
  _cb.onStatusUpdate(data);
  return data;
}

// ── Reset / clear ─────────────────────────────────────────────────────────────

export async function reset() {
  await http.post(PATHS.react.reset, {});
  _cb.onToast('ReAct reset');
}

export async function clearMemory() {
  await http.post(PATHS.memory.clearMem, {});
  _cb.onToast('Memory cleared');
}

export async function clearPersona() {
  await http.post(PATHS.memory.clearPersona, {});
  _cb.onToast('Persona cleared');
}

// ── Tools ─────────────────────────────────────────────────────────────────────

export async function fetchTools() {
  return http.get(PATHS.react.tools);
}

// ── Workstation card ──────────────────────────────────────────────────────────

export async function updateWorkstationCard() {
  const badgeEl = document.getElementById('mc-react-badge');
  const bodyEl  = document.getElementById('mc-react-body');
  if (!badgeEl || !bodyEl) return;

  const data = await fetchStatus().catch(() => null);
  if (!data) {
    badgeEl.textContent = 'error';
    badgeEl.className   = 'mc-badge off';
    bodyEl.innerHTML    = '<span style="color:var(--text3)">Could not load</span>';
    return;
  }

  const ready = data.status === 'ready';
  badgeEl.textContent = ready ? 'ON' : 'OFF';
  badgeEl.className   = `mc-badge ${ready ? 'on' : 'off'}`;

  bodyEl.innerHTML = `
    <div class="mc-row"><span class="mc-key">Status</span>
      <span class="mc-val">${data.status}</span></div>
    <div class="mc-row"><span class="mc-key">Profile</span>
      <span class="mc-val">${data.profile ?? '—'}</span></div>
    <div class="mc-row"><span class="mc-key">Persona</span>
      <span class="mc-val">${data.persona ?? '—'}</span></div>`;
}
