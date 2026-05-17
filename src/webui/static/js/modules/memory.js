/**
 * modules/memory.js — Memory config load/save and consolidation.
 */

import { http, PATHS } from '../api.js';

const _cb = { onToast: () => {} };
export function setCallbacks(cbs) { Object.assign(_cb, cbs); }

export async function loadConfig() {
  return http.get(PATHS.memory.get);
}

export async function saveConfig(payload) {
  await http.post(PATHS.memory.save, payload);
  _cb.onToast('Memory config saved');
}

export async function consolidate() {
  const data = await http.post(PATHS.memory.consolidate, {});
  _cb.onToast(`Consolidated: ${data.consolidated ?? 0} items`);
  return data;
}

export async function updateWorkstationCard() {
  const bodyEl = document.getElementById('mc-memory-body');
  if (!bodyEl) return;

  const data = await loadConfig().catch(() => null);
  if (!data) {
    bodyEl.innerHTML = '<span style="color:var(--text3)">Could not load</span>';
    return;
  }

  const row = (label, val) => `<div class="mc-row">
    <span class="mc-key">${label}</span>
    <span class="mc-val">${val}</span></div>`;
  const badge = (on) => `<span class="tier-badge ${on ? 'on' : 'off'}">${on ? '✓ on' : 'off'}</span>`;

  bodyEl.innerHTML = `
    ${row('Long-term',  badge(data.long_term?.enabled))}
    ${row('Medium',     badge(data.medium_term?.enabled))}
    ${row('Milestone',  badge(data.milestone?.enabled))}`;
}
