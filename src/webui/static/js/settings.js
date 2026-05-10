/**
 * settings.js — Compatibility barrel.
 *
 * All logic has been moved to settings/modal.js + settings/tabs/*.js.
 * This file re-exports everything so existing import sites continue to work.
 */

export {
  open, close, handleOverlayClick,
  setTab, saveCurrentTab,
  saveModelTab, saveMemoryTab, savePersonaTab,
  saveVoiceTab, saveSandboxTab, saveBotTab, saveSchedulerTab,
  onToggleTools, onTTSProviderChange, onSTTProviderChange,
  onBotTransportChange, onChannelChange, testBark, testNtfy,
  doConsolidate, doClearMemory, doClearPersona,
} from './settings/modal.js';
