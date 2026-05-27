import * as personaMod from '../../modules/persona.js';
import * as soulMod    from '../../modules/soul.js';
import * as reactMod   from '../../modules/react.js';
import { $, _v, _c, _si, _sc, _int } from './_helpers.js';

let _cfgCache = null;

async function _refreshReadiness() {
  const panel = $('soul-init-status');
  if (!panel) return;
  const data = await soulMod.fetchReadiness().catch(() => null);
  if (data) soulMod.renderReadinessPanel(panel, data);
}

export async function load() {
  const d = await personaMod.loadConfig().catch(() => null);
  if (!d) return;
  _cfgCache = d;
  const p = d.profile ?? {};
  _sc('s-persona-enabled', d.enabled);
  _sc('s-persona-toast', d.show_evolution_toast ?? true);
  _si('s-p-name',          p.name ?? '');
  _si('s-p-background',    p.background ?? '');
  _si('s-p-traits',        (p.traits ?? []).join(', '));
  _si('s-p-values',        (p.values ?? []).join(', '));
  _si('s-p-style',         p.style ?? '');
  _si('s-p-max-profile',   d.max_profile_chars ?? 500);
  _sc('s-p-evolution',     d.evolution_enabled ?? false);
  _si('s-p-evolve-int',    d.evolve_interval ?? 1);
  _sc('s-p-skills',        d.skills_enabled ?? true);
  await _refreshReadiness();
  _wireInitButtons();
}

let _initButtonsWired = false;

function _wireInitButtons() {
  if (_initButtonsWired) return;
  _initButtonsWired = true;
  $('btn-soul-reinit')?.addEventListener('click', _doReinit);
  $('btn-soul-build')?.addEventListener('click', _doBuild);
  $('btn-soul-reload')?.addEventListener('click', _doReload);
}

async function _doReinit() {
  const msgEl = $('soul-init-msg');
  if (msgEl) msgEl.textContent = 'Saving persona & reinitializing…';
  await save();
  const ok = await reactMod.init({});
  if (msgEl) msgEl.textContent = ok ? 'Reinit submitted — wait for ready' : 'Reinit rejected';
  await _refreshReadiness();
}

async function _doBuild() {
  const msgEl = $('soul-init-msg');
  const preserve = _c('s-soul-preserve-sc');
  if (msgEl) msgEl.textContent = 'Building persona profile (LLM)…';
  await soulMod.rebuildPersona(preserve).catch(e => {
    if (msgEl) msgEl.textContent = e.message;
    throw e;
  });
  if (msgEl) msgEl.textContent = 'Build complete';
  await _refreshReadiness();
}

async function _doReload() {
  const msgEl = $('soul-init-msg');
  if (msgEl) msgEl.textContent = 'Reloading…';
  await soulMod.reloadPersona().catch(e => {
    if (msgEl) msgEl.textContent = e.message;
    throw e;
  });
  if (msgEl) msgEl.textContent = 'Reloaded';
  await _refreshReadiness();
}

export async function save() {
  const base = _cfgCache ?? {};
  await personaMod.saveConfig({
    enabled:           _c('s-persona-enabled'),
    name:              _v('s-p-name'),
    background:        _v('s-p-background'),
    traits:            _v('s-p-traits').split(',').map(s => s.trim()).filter(Boolean),
    values:            _v('s-p-values').split(',').map(s => s.trim()).filter(Boolean),
    style:             _v('s-p-style'),
    max_profile_chars: parseInt(_v('s-p-max-profile')) || 500,
    evolution_enabled:    _c('s-p-evolution'),
    evolve_interval:      _int('s-p-evolve-int', base.evolve_interval ?? 1),
    skills_enabled:       _c('s-p-skills'),
    max_skills_in_prompt: base.max_skills_in_prompt ?? 5,
    max_skills_chars:     base.max_skills_chars ?? 600,
    reflection_enabled:   base.reflection_enabled ?? false,
    reflect_interval:     base.reflect_interval ?? 3,
    max_reflection_chars: base.max_reflection_chars ?? 400,
    show_evolution_toast: _c('s-persona-toast'),
  });
  _cfgCache = await personaMod.loadConfig().catch(() => _cfgCache);
  await _refreshReadiness();
}

export async function doClearPersona() {
  if (!confirm('Clear persona drift data? This cannot be undone.')) return;
  const msgEl = $('clear-persona-msg');
  if (msgEl) msgEl.textContent = 'Clearing…';
  await reactMod.clearPersona().catch(e => { if (msgEl) msgEl.textContent = e.message; });
  if (msgEl) msgEl.textContent = 'Persona cleared.';
}
