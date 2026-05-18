import * as memoryMod from '../../modules/memory.js';
import * as reactMod  from '../../modules/react.js';
import { $, _v, _c, _si, _sc } from './_helpers.js';

export async function load() {
  const d = await memoryMod.loadConfig().catch(() => null);
  if (!d) return;
  const st = d.short_term ?? {};
  _sc('s-st-enabled',         st.enabled);
  _si('s-st-max-turns',       st.max_turns ?? 10);
  _si('s-st-max-tokens',      st.max_tokens ?? 2048);
  _sc('s-st-distill',         st.distill_enabled);
  _si('s-st-distill-trigger', st.distill_trigger ?? 4);
  _si('s-st-distill-tokens',  st.distill_max_tokens ?? 400);

  const mt = d.medium_term ?? {};
  _sc('s-mt-enabled',              mt.enabled);
  _si('s-mt-window-days',          mt.window_days ?? 7);
  _si('s-mt-max-entries',          mt.max_entries ?? 30);
  _si('s-mt-max-chars',            mt.max_chars ?? 3000);
  _sc('s-mt-consolidate',          mt.consolidate_enabled);
  _si('s-mt-consolidate-batch',    mt.consolidate_batch ?? 10);
  _si('s-mt-consolidate-interval', mt.consolidate_interval_days ?? 1);
  _si('s-mt-consolidate-tokens',   mt.consolidate_max_tokens ?? 500);

  const lt = d.long_term ?? {};
  _sc('s-lt-enabled',        lt.enabled);
  _si('s-lt-top-k',          lt.top_k ?? 5);
  _si('s-lt-max-recall',     lt.max_recall_chars ?? 3000);
  _si('s-lt-consolidation',  lt.consolidation_k ?? 0);
  _sc('s-lt-distill',        lt.distill_enabled);
  _si('s-lt-distill-tokens', lt.distill_max_tokens ?? 400);
}

export async function save() {
  await memoryMod.saveConfig({
    short_term: {
      enabled:            _c('s-st-enabled'),
      max_turns:          parseInt(_v('s-st-max-turns'))       || 10,
      max_tokens:         parseInt(_v('s-st-max-tokens'))      || 2048,
      distill_enabled:    _c('s-st-distill'),
      distill_trigger:    parseInt(_v('s-st-distill-trigger')) || 4,
      distill_max_tokens: parseInt(_v('s-st-distill-tokens'))  || 400,
    },
    medium_term: {
      enabled:                   _c('s-mt-enabled'),
      window_days:               parseInt(_v('s-mt-window-days'))          || 7,
      max_entries:               parseInt(_v('s-mt-max-entries'))          || 30,
      max_chars:                 parseInt(_v('s-mt-max-chars'))            || 3000,
      consolidate_enabled:       _c('s-mt-consolidate'),
      consolidate_batch:         parseInt(_v('s-mt-consolidate-batch'))    || 10,
      consolidate_interval_days: parseInt(_v('s-mt-consolidate-interval')) || 1,
      consolidate_max_tokens:    parseInt(_v('s-mt-consolidate-tokens'))   || 500,
    },
    long_term: {
      enabled:            _c('s-lt-enabled'),
      top_k:              parseInt(_v('s-lt-top-k'))         || 5,
      max_recall_chars:   parseInt(_v('s-lt-max-recall'))    || 3000,
      consolidation_k:    parseInt(_v('s-lt-consolidation')) || 0,
      distill_enabled:    _c('s-lt-distill'),
      distill_max_tokens: parseInt(_v('s-lt-distill-tokens')) || 400,
    },
  });
}

export async function doConsolidate() {
  const msgEl = $('consolidate-msg');
  if (msgEl) msgEl.textContent = 'Consolidating…';
  const data = await memoryMod.consolidate().catch(e => ({ error: e.message }));
  if (msgEl) msgEl.textContent = data.error ?? `Done. ${data.consolidated ?? 0} items.`;
}

export async function doClearMemory() {
  if (!confirm('Clear ALL memory tiers? This cannot be undone.')) return;
  const msgEl = $('clear-memory-msg');
  if (msgEl) msgEl.textContent = 'Clearing…';
  await reactMod.clearMemory().catch(e => { if (msgEl) msgEl.textContent = e.message; });
  if (msgEl) msgEl.textContent = 'Memory cleared.';
}
