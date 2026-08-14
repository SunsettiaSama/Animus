/**
 * modules/react.js — legacy API helpers plus the Soul Speak workstation card.
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

  const [readiness, speak] = await Promise.all([
    http.get(PATHS.soul.readiness).catch(() => null),
    http.get(PATHS.speak.status).catch(() => null),
  ]);

  if (!readiness && !speak) {
    badgeEl.textContent = 'error';
    badgeEl.className   = 'mc-badge off';
    bodyEl.innerHTML    = '<span style="color:var(--text3)">Could not load</span>';
    return;
  }

  const soulRunning = Boolean(readiness?.soul_running);
  const speakReady = Boolean(speak?.ready || readiness?.speak_ready);
  set('soulReady', soulRunning);
  set('speakReady', speakReady);
  badgeEl.textContent = speakReady ? 'READY' : (soulRunning ? 'BOOT' : 'OFF');
  badgeEl.className   = `mc-badge ${speakReady ? 'on' : (soulRunning ? 'warn' : 'off')}`;

  bodyEl.innerHTML = `
    <div class="mc-row"><span class="mc-key">Soul</span>
      <span class="mc-val">${readiness?.soul_state ?? speak?.soul_state ?? '—'}</span></div>
    <div class="mc-row"><span class="mc-key">Speak</span>
      <span class="mc-val">${speakReady ? 'ready' : (speak?.status ?? 'initializing')}</span></div>
    <div class="mc-row"><span class="mc-key">Pipeline</span>
      <span class="mc-val">request_driven</span></div>
    <div class="mc-row"><span class="mc-key">Dialogue</span>
      <span class="mc-val">Soul/Speak primary</span></div>`;
}
