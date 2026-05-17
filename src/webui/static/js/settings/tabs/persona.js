import * as personaMod from '../../modules/persona.js';
import * as reactMod   from '../../modules/react.js';
import { $, _v, _c, _si, _sc } from './_helpers.js';

export async function load() {
  const d = await personaMod.loadConfig().catch(() => null);
  if (!d) return;
  const p = d.profile ?? {};
  _sc('s-persona-enabled', d.enabled);
  _si('s-p-name',          p.name ?? '');
  _si('s-p-background',    p.background ?? '');
  _si('s-p-traits',        (p.traits ?? []).join(', '));
  _si('s-p-values',        (p.values ?? []).join(', '));
  _si('s-p-style',         p.style ?? '');
  _si('s-p-max-profile',   d.max_profile_chars ?? 500);
}

export async function save() {
  await personaMod.saveConfig({
    enabled:           _c('s-persona-enabled'),
    name:              _v('s-p-name'),
    background:        _v('s-p-background'),
    traits:            _v('s-p-traits').split(',').map(s => s.trim()).filter(Boolean),
    values:            _v('s-p-values').split(',').map(s => s.trim()).filter(Boolean),
    style:             _v('s-p-style'),
    max_profile_chars: parseInt(_v('s-p-max-profile')) || 500,
  });
}

export async function doClearPersona() {
  if (!confirm('Clear persona drift data? This cannot be undone.')) return;
  const msgEl = $('clear-persona-msg');
  if (msgEl) msgEl.textContent = 'Clearing…';
  await reactMod.clearPersona().catch(e => { if (msgEl) msgEl.textContent = e.message; });
  if (msgEl) msgEl.textContent = 'Persona cleared.';
}
