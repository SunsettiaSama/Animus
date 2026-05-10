/**
 * settings/modal.js — Settings modal controller.
 *
 * Manages modal open/close, tab switching, and delegates all
 * load/save work to the per-tab modules in ./tabs/.
 */

import * as tabLlm     from './tabs/llm.js';
import * as tabMemory  from './tabs/memory.js';
import * as tabPersona from './tabs/persona.js';
import * as tabVoice   from './tabs/voice.js';
import * as tabSandbox from './tabs/sandbox.js';
import * as tabBot     from './tabs/bot.js';
import * as tabScheduler from './tabs/scheduler.js';

const $ = id => document.getElementById(id);

const _TABS = {
  model:     tabLlm,
  memory:    tabMemory,
  persona:   tabPersona,
  voice:     tabVoice,
  sandbox:   tabSandbox,
  bot:       tabBot,
  scheduler: tabScheduler,
};

let _activeTab = 'model';

// ── Open / Close ──────────────────────────────────────────────────────────────

export function open(tab = _activeTab) {
  $('overlay')?.classList.remove('hidden');
  setTab(tab);
}

export function close() {
  $('overlay')?.classList.add('hidden');
}

export function handleOverlayClick(e) {
  if (e.target === $('overlay')) close();
}

// ── Tab switching ─────────────────────────────────────────────────────────────

export function setTab(tab) {
  _activeTab = tab;
  Object.keys(_TABS).forEach(t => {
    $(`tab-${t}`)?.classList.toggle('hidden', t !== tab);
    $(`snav-btn-${t}`)?.classList.toggle('active', t === tab);
  });
  _TABS[tab]?.load().catch(err => console.error(`[settings/${tab}] load failed:`, err));
}

// ── Save current tab ──────────────────────────────────────────────────────────

export async function saveCurrentTab() {
  const msgEl = $('modal-msg');
  if (msgEl) { msgEl.textContent = ''; msgEl.className = ''; }
  const tab = _TABS[_activeTab];
  if (!tab?.save) return;
  if (msgEl) msgEl.textContent = 'Saving…';
  await tab.save().catch(e => {
    if (msgEl) { msgEl.textContent = e.message; msgEl.className = 'err'; }
    throw e;
  });
  if (msgEl) { msgEl.textContent = 'Saved ✓'; msgEl.className = 'ok'; }
  setTimeout(() => { if (msgEl) { msgEl.textContent = ''; msgEl.className = ''; } }, 2000);
}

// ── Per-tab save helpers (called by app.js for dedicated buttons) ─────────────

export const saveModelTab   = ()  => tabLlm.save();
export const saveMemoryTab  = ()  => tabMemory.save();
export const savePersonaTab = ()  => tabPersona.save();
export const saveVoiceTab   = ()  => tabVoice.save();
export const saveSandboxTab = ()  => tabSandbox.save();
export const saveBotTab       = () => tabBot.save();
export const saveSchedulerTab = () => tabScheduler.save();

// ── Action helpers forwarded from tabs ───────────────────────────────────────

export const onToggleTools       = ()  => tabLlm.onToggleTools();
export const onTTSProviderChange = ()  => tabVoice.onTTSProviderChange();
export const onSTTProviderChange = ()  => tabVoice.onSTTProviderChange();
export const onBotTransportChange = () => tabBot.onBotTransportChange();
export const testBark             = () => tabBot.testBark();
export const testNtfy             = () => tabBot.testNtfy();
export const doConsolidate       = ()  => tabMemory.doConsolidate();
export const doClearMemory       = ()  => tabMemory.doClearMemory();
export const doClearPersona      = ()  => tabPersona.doClearPersona();
