/**
 * modules/persona.js — Persona config load/save and workstation card.
 */

import { http, PATHS } from '../api.js';
import { set }         from '../state.js';

const _cb = { onToast: () => {} };
export function setCallbacks(cbs) { Object.assign(_cb, cbs); }

export async function loadConfig() {
  return http.get(PATHS.persona.get);
}

export async function saveConfig(payload) {
  await http.post(PATHS.persona.save, payload);
  _cb.onToast('Persona saved');
  set('personaName', payload.enabled ? (payload.name ?? null) : null);
}

export async function updateWorkstationCard() {
  const badgeEl = document.getElementById('mc-persona-badge');
  const bodyEl  = document.getElementById('mc-persona-body');
  if (!badgeEl || !bodyEl) return;

  const data = await loadConfig().catch(() => null);
  if (!data) {
    badgeEl.textContent = '—';
    badgeEl.className   = 'mc-badge off';
    bodyEl.innerHTML    = '<span style="color:var(--text3)">Could not load</span>';
    return;
  }

  const on = data.enabled;
  badgeEl.textContent = on ? 'ON' : 'OFF';
  badgeEl.className   = `mc-badge ${on ? 'on' : 'off'}`;

  const p = data.profile ?? {};
  bodyEl.innerHTML = `
    <div class="mc-row"><span class="mc-key">Name</span>
      <span class="mc-val">${p.name ?? '—'}</span></div>
    <div class="mc-row"><span class="mc-key">Evolution</span>
      <span class="mc-val">${data.evolution_enabled ? 'on' : 'off'}</span></div>
    <div class="mc-row"><span class="mc-key">Skills</span>
      <span class="mc-val">${data.skills_enabled ? 'on' : 'off'}</span></div>`;
}
