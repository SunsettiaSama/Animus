/**
 * modules/persona.js — Persona config load/save and workstation card.
 */

import { http, PATHS } from '../api.js';
import { set }         from '../state.js';

const _cb = { onToast: () => {}, onPersonaLoad: () => {} };
export function setCallbacks(cbs) { Object.assign(_cb, cbs); }

export async function loadConfig() {
  const data = await http.get(PATHS.persona.get);
  _cb.onPersonaLoad(data);
  return data;
}

export async function saveConfig(payload) {
  await http.post(PATHS.persona.save, payload);
  _cb.onToast('Persona saved');
  const name = payload.enabled ? (payload.name ?? payload.profile?.name ?? null) : null;
  set('personaName', name);
}

export async function updateWorkstationCard() {
  const soulMod = await import('./soul.js');
  await soulMod.updateWorkstationCard();
}
