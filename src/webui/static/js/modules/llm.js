/**
 * modules/llm.js — LLM configuration, initialization, and status.
 *
 * Wires to: api.js PATHS.llm.*
 * Notifies main.js via callbacks (no direct showToast calls).
 */

import { http, PATHS }  from '../api.js';
import { S, set }       from '../state.js';

const _cb = {
  onToast:   () => {},
  onStatus:  () => {},
};
export function setCallbacks(cbs) { Object.assign(_cb, cbs); }

// ── Config read/write ─────────────────────────────────────────────────────────

export async function loadConfig() {
  return http.get(PATHS.llm.config);
}

export async function saveConfig(payload) {
  await http.post(PATHS.llm.save, payload);
  _cb.onToast('LLM config saved');
}

// ── Init / hot-swap ───────────────────────────────────────────────────────────

export async function initLLM(payload) {
  const { status } = await http.post(PATHS.llm.init, payload);
  _cb.onToast(status === 'ok' ? 'LLM initialized' : 'LLM init failed');
  set('llmModel', payload.model ?? null);
  return status;
}

/**
 * Issue 2 fix: use PATCH to hot-swap LLM while streaming guard is on server.
 * Returns the server response; 409 = streaming active.
 */
export async function patchLLM(fields) {
  const resp = await fetch(PATHS.llm.patch, {
    method:  'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body:    JSON.stringify(fields),
  });
  const data = await resp.json();
  if (!resp.ok) {
    _cb.onToast(data.error ?? 'Cannot modify LLM while streaming');
    return null;
  }
  _cb.onToast('LLM updated');
  if (fields.model) set('llmModel', fields.model);
  return data;
}

// ── Status ────────────────────────────────────────────────────────────────────

export async function fetchStatus() {
  const data = await http.get(PATHS.llm.status);
  _cb.onStatus(data);
  return data;
}

// ── Workstation card ──────────────────────────────────────────────────────────

export async function updateWorkstationCard() {
  const badgeEl = document.getElementById('mc-llm-badge');
  const bodyEl  = document.getElementById('mc-llm-body');
  if (!badgeEl || !bodyEl) return;

  const data = await fetchStatus().catch(() => null);
  if (!data) {
    badgeEl.textContent = 'error';
    badgeEl.className   = 'mc-badge off';
    bodyEl.innerHTML    = '<span style="color:var(--text3)">Could not load status</span>';
    return;
  }

  if (data.initialized) {
    badgeEl.textContent = 'ON';
    badgeEl.className   = 'mc-badge on';
  } else {
    badgeEl.textContent = '—';
    badgeEl.className   = 'mc-badge off';
  }

  bodyEl.innerHTML = `
    <div class="mc-row"><span class="mc-key">Model</span>
      <span class="mc-val mc-truncate">${data.model ?? '—'}</span></div>
    <div class="mc-row"><span class="mc-key">Provider</span>
      <span class="mc-val">${data.backend ?? '—'}</span></div>
    <div class="mc-row"><span class="mc-key">Streaming</span>
      <span class="mc-val">${data.is_streaming ? '⏳ active' : '—'}</span></div>`;
}
