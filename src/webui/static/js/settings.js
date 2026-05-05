/**
 * settings.js — Settings modal open/close, tab switching, and field I/O.
 *
 * Delegates all actual config load/save to domain modules.
 * Never calls showToast directly — fires 'react:toast' CustomEvents instead.
 */

import * as llmMod      from './modules/llm.js';
import * as reactMod    from './modules/react.js';
import * as memoryMod   from './modules/memory.js';
import * as personaMod  from './modules/persona.js';
import * as voiceMod    from './modules/voice.js';
import * as infraMod    from './modules/infra.js';

// ── Helpers ───────────────────────────────────────────────────────────────────

const $ = id => document.getElementById(id);
const _v  = id => $( id)?.value ?? '';
const _c  = id => $( id)?.checked ?? false;
const _si = (id, v) => { const el = $(id); if (el) el.value  = v ?? ''; };
const _sc = (id, v) => { const el = $(id); if (el) el.checked = !!v;   };
const _toast = text => window.dispatchEvent(new CustomEvent('react:toast', { detail: text }));

// ── Modal open/close ──────────────────────────────────────────────────────────

let _activeTab = 'model';

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

const _ALL_TABS = ['model', 'memory', 'persona', 'voice', 'vllm', 'sandbox'];

export function setTab(tab) {
  _activeTab = tab;
  _ALL_TABS.forEach(t => {
    $(`tab-${t}`)?.classList.toggle('hidden', t !== tab);
    $(`snav-btn-${t}`)?.classList.toggle('active', t === tab);
  });
  _loadTab(tab);
}

async function _loadTab(tab) {
  if (tab === 'model')   await _loadModelTab();
  if (tab === 'memory')  await _loadMemoryTab();
  if (tab === 'persona') await _loadPersonaTab();
  if (tab === 'voice')   await _loadVoiceTab();
  if (tab === 'vllm')    await _loadVLLMTab();
  if (tab === 'sandbox') await _loadSandboxTab();
}

// ── Model tab ─────────────────────────────────────────────────────────────────

async function _loadModelTab() {
  const d = await llmMod.loadConfig().catch(() => null);
  if (!d) return;
  _si('s-model',     d.model);
  _si('s-apikey',    d.api_key);
  _si('s-baseurl',   d.base_url);
  _si('s-maxtokens', d.max_tokens ?? 512);
  _si('s-temp',      d.temperature ?? 1.0);
  _si('s-sysprompt', d.system_prompt ?? '');
  _si('s-lang',      d.prompt_lang ?? 'cn');
  _si('s-maxsteps',  d.max_steps ?? 10);
  _sc('s-tools-enabled', d.tools_enabled ?? false);
  _sc('s-show-full-prompt', d.show_full_prompt ?? false);
  $('react-cfg-fields')?.classList.toggle('hidden', !(d.tools_enabled ?? false));
}

export async function saveModelTab() {
  const payload = {
    model:            _v('s-model'),
    api_key:          _v('s-apikey'),
    base_url:         _v('s-baseurl'),
    max_tokens:       parseInt(_v('s-maxtokens')) || 512,
    temperature:      parseFloat(_v('s-temp')) || 1.0,
    system_prompt:    _v('s-sysprompt'),
    prompt_lang:      _v('s-lang'),
    max_steps:        parseInt(_v('s-maxsteps')) || 10,
    tools_enabled:    _c('s-tools-enabled'),
    show_full_prompt: _c('s-show-full-prompt'),
  };
  await llmMod.saveConfig(payload);
  await llmMod.initLLM(payload);
  if (payload.tools_enabled) {
    reactMod.init({ profile: 'default', lang: payload.prompt_lang });
  }
}

export function onToggleTools() {
  const on = _c('s-tools-enabled');
  $('react-cfg-fields')?.classList.toggle('hidden', !on);
}

// ── Memory tab ────────────────────────────────────────────────────────────────

async function _loadMemoryTab() {
  const d = await memoryMod.loadConfig().catch(() => null);
  if (!d) return;
  const st = d.short_term ?? {};
  _sc('s-st-enabled',          st.enabled);
  _si('s-st-max-turns',        st.max_turns ?? 10);
  _si('s-st-max-tokens',       st.max_tokens ?? 2048);
  _sc('s-st-distill',          st.distill_enabled);
  _si('s-st-distill-trigger',  st.distill_trigger ?? 4);
  _si('s-st-distill-tokens',   st.distill_max_tokens ?? 400);

  const mt = d.medium_term ?? {};
  _sc('s-mt-enabled',               mt.enabled);
  _si('s-mt-window-days',           mt.window_days ?? 7);
  _si('s-mt-max-entries',           mt.max_entries ?? 30);
  _si('s-mt-max-chars',             mt.max_chars ?? 3000);
  _sc('s-mt-consolidate',           mt.consolidate_enabled);
  _si('s-mt-consolidate-batch',     mt.consolidate_batch ?? 10);
  _si('s-mt-consolidate-interval',  mt.consolidate_interval_days ?? 1);
  _si('s-mt-consolidate-tokens',    mt.consolidate_max_tokens ?? 500);

  const lt = d.long_term ?? {};
  _sc('s-lt-enabled',        lt.enabled);
  _si('s-lt-top-k',          lt.top_k ?? 5);
  _si('s-lt-max-recall',     lt.max_recall_chars ?? 3000);
  _si('s-lt-consolidation',  lt.consolidation_k ?? 0);
  _sc('s-lt-distill',        lt.distill_enabled);
  _si('s-lt-distill-tokens', lt.distill_max_tokens ?? 400);

  const ms = d.milestone ?? {};
  _sc('s-ms-enabled',       ms.enabled);
  _si('s-ms-threshold',     ms.importance_threshold ?? 0.6);
  _si('s-ms-top-k',         ms.top_k_retrieve ?? 2);
  _si('s-ms-max',           ms.max_milestones ?? 50);
  _sc('s-ms-inject-detail', ms.inject_detail ?? true);
}

export async function saveMemoryTab() {
  const payload = {
    short_term: {
      enabled:               _c('s-st-enabled'),
      max_turns:             parseInt(_v('s-st-max-turns'))        || 10,
      max_tokens:            parseInt(_v('s-st-max-tokens'))       || 2048,
      distill_enabled:       _c('s-st-distill'),
      distill_trigger:       parseInt(_v('s-st-distill-trigger'))  || 4,
      distill_max_tokens:    parseInt(_v('s-st-distill-tokens'))   || 400,
    },
    medium_term: {
      enabled:                     _c('s-mt-enabled'),
      window_days:                 parseInt(_v('s-mt-window-days'))               || 7,
      max_entries:                 parseInt(_v('s-mt-max-entries'))               || 30,
      max_chars:                   parseInt(_v('s-mt-max-chars'))                 || 3000,
      consolidate_enabled:         _c('s-mt-consolidate'),
      consolidate_batch:           parseInt(_v('s-mt-consolidate-batch'))         || 10,
      consolidate_interval_days:   parseInt(_v('s-mt-consolidate-interval'))      || 1,
      consolidate_max_tokens:      parseInt(_v('s-mt-consolidate-tokens'))        || 500,
    },
    long_term: {
      enabled:            _c('s-lt-enabled'),
      top_k:              parseInt(_v('s-lt-top-k'))          || 5,
      max_recall_chars:   parseInt(_v('s-lt-max-recall'))     || 3000,
      consolidation_k:    parseInt(_v('s-lt-consolidation'))  || 0,
      distill_enabled:    _c('s-lt-distill'),
      distill_max_tokens: parseInt(_v('s-lt-distill-tokens')) || 400,
    },
    milestone: {
      enabled:              _c('s-ms-enabled'),
      importance_threshold: parseFloat(_v('s-ms-threshold'))    || 0.6,
      top_k_retrieve:       parseInt(_v('s-ms-top-k'))          || 2,
      max_milestones:       parseInt(_v('s-ms-max'))            || 50,
      inject_detail:        _c('s-ms-inject-detail'),
    },
  };
  await memoryMod.saveConfig(payload);
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

// ── Persona tab ───────────────────────────────────────────────────────────────

async function _loadPersonaTab() {
  const d = await personaMod.loadConfig().catch(() => null);
  if (!d) return;
  const p = d.profile ?? {};
  _sc('s-persona-enabled', d.enabled);
  _si('s-p-name',       p.name ?? '');
  _si('s-p-background', p.background ?? '');
  _si('s-p-traits',     (p.traits ?? []).join(', '));
  _si('s-p-values',     (p.values ?? []).join(', '));
  _si('s-p-style',      p.style ?? '');
  _si('s-p-max-profile', d.max_profile_chars ?? 500);
}

export async function savePersonaTab() {
  const payload = {
    enabled:            _c('s-persona-enabled'),
    name:               _v('s-p-name'),
    background:         _v('s-p-background'),
    traits:             _v('s-p-traits').split(',').map(s => s.trim()).filter(Boolean),
    values:             _v('s-p-values').split(',').map(s => s.trim()).filter(Boolean),
    style:              _v('s-p-style'),
    max_profile_chars:  parseInt(_v('s-p-max-profile')) || 500,
  };
  await personaMod.saveConfig(payload);
}

export async function doClearPersona() {
  if (!confirm('Clear persona drift data? This cannot be undone.')) return;
  const msgEl = $('clear-persona-msg');
  if (msgEl) msgEl.textContent = 'Clearing…';
  await reactMod.clearPersona().catch(e => { if (msgEl) msgEl.textContent = e.message; });
  if (msgEl) msgEl.textContent = 'Persona cleared.';
}

// ── Voice tab ─────────────────────────────────────────────────────────────────

async function _loadVoiceTab() {
  const [tts, stt] = await Promise.allSettled([
    voiceMod.loadTTSConfig(),
    voiceMod.loadSTTConfig(),
  ]);
  if (tts.status === 'fulfilled') {
    const d = tts.value;
    _si('s-tts-provider',        d.provider);
    _si('s-tts-voice',           d.voice);
    _si('s-tts-format',          d.output_format);
    _si('s-tts-rate',            d.rate);
    _si('s-tts-volume',          d.volume);
    _si('s-tts-openai-model',    d.openai_model);
    _si('s-tts-openai-voice',    d.voice);
    _si('s-tts-openai-base-url', d.openai_base_url);
    _si('s-tts-openai-api-key',  d.openai_api_key);
    _si('s-tts-kokoro-path',     d.kokoro_model_path);
    _si('s-tts-kokoro-device',   d.kokoro_device);
    _si('s-tts-kokoro-voice',    d.voice);
    _si('s-tts-kokoro-hf-repo',  d.kokoro_hf_repo_id);
    _si('s-tts-hf-endpoint',     d.hf_endpoint);
    _si('s-tts-hf-token',        d.hf_token);
    onTTSProviderChange();
  }
  if (stt.status === 'fulfilled') {
    const d = stt.value;
    _si('s-stt-provider',       d.provider);
    _si('s-stt-language',       d.language);
    _si('s-stt-openai-model',   d.openai_model);
    _si('s-stt-openai-base-url',d.openai_base_url);
    _si('s-stt-openai-api-key', d.openai_api_key);
    _si('s-stt-local-path',     d.local_model_path);
    _si('s-stt-local-size',     d.local_model_size);
    _si('s-stt-local-device',   d.local_device);
    _si('s-stt-local-compute',  d.local_compute_type);
    _si('s-stt-hf-endpoint',    d.hf_endpoint);
    _si('s-stt-hf-token',       d.hf_token);
    onSTTProviderChange();
  }
}

export function onTTSProviderChange() {
  const p = _v('s-tts-provider');
  document.querySelectorAll('.voice-provider-section[id^="tts-"]').forEach(el => {
    el.classList.toggle('active', el.id === `tts-${p}-fields`);
  });
}

export function onSTTProviderChange() {
  const p = _v('s-stt-provider');
  const key = p === 'faster_whisper' ? 'local' : 'openai';
  document.querySelectorAll('.voice-provider-section[id^="stt-"]').forEach(el => {
    el.classList.toggle('active', el.id === `stt-${key}-fields`);
  });
}

export async function saveVoiceTab() {
  const ttsPayload = {
    provider:          _v('s-tts-provider'),
    voice:             _v('s-tts-provider') === 'openai'  ? _v('s-tts-openai-voice')
                     : _v('s-tts-provider') === 'kokoro'  ? _v('s-tts-kokoro-voice')
                     : _v('s-tts-voice'),
    rate:              _v('s-tts-rate'),
    volume:            _v('s-tts-volume'),
    output_format:     _v('s-tts-format'),
    openai_model:      _v('s-tts-openai-model'),
    openai_base_url:   _v('s-tts-openai-base-url'),
    openai_api_key:    _v('s-tts-openai-api-key'),
    kokoro_model_path: _v('s-tts-kokoro-path'),
    kokoro_device:     _v('s-tts-kokoro-device'),
    kokoro_hf_repo_id: _v('s-tts-kokoro-hf-repo'),
    hf_endpoint:       _v('s-tts-hf-endpoint'),
    hf_token:          _v('s-tts-hf-token'),
  };
  await voiceMod.saveTTSConfig(ttsPayload);

  const sttPayload = {
    provider:           _v('s-stt-provider'),
    language:           _v('s-stt-language'),
    openai_model:       _v('s-stt-openai-model'),
    openai_base_url:    _v('s-stt-openai-base-url'),
    openai_api_key:     _v('s-stt-openai-api-key'),
    local_model_path:   _v('s-stt-local-path'),
    local_model_size:   _v('s-stt-local-size'),
    local_device:       _v('s-stt-local-device'),
    local_compute_type: _v('s-stt-local-compute'),
    hf_endpoint:        _v('s-stt-hf-endpoint'),
    hf_token:           _v('s-stt-hf-token'),
  };
  await voiceMod.saveSTTConfig(sttPayload);
}

// ── vLLM tab ──────────────────────────────────────────────────────────────────

async function _loadVLLMTab() {
  const d = await infraMod.vllm.loadConfig().catch(() => null);
  if (!d) return;
  _si('s-vllm-host',               d.host ?? '127.0.0.1');
  _si('s-vllm-port',               d.port ?? 8000);
  _si('s-vllm-tp',                 d.tensor_parallel_size ?? 1);
  _si('s-vllm-pp',                 d.pipeline_parallel_size ?? 1);
  _si('s-vllm-gpu-util',           d.gpu_memory_utilization ?? 0.90);
  _si('s-vllm-max-len',            d.max_model_len ?? '');
  _si('s-vllm-quant',              d.quantization ?? '');
  _si('s-vllm-dtype',              d.dtype ?? 'auto');
  _sc('s-vllm-enforce-eager',      d.enforce_eager);
}

export async function saveVLLMTab() {
  const payload = {
    host:                    _v('s-vllm-host'),
    port:                    parseInt(_v('s-vllm-port'))          || 8000,
    tensor_parallel_size:    parseInt(_v('s-vllm-tp'))            || 1,
    pipeline_parallel_size:  parseInt(_v('s-vllm-pp'))            || 1,
    gpu_memory_utilization:  parseFloat(_v('s-vllm-gpu-util'))    || 0.90,
    max_model_len:           parseInt(_v('s-vllm-max-len'))        || null,
    quantization:            _v('s-vllm-quant') || null,
    dtype:                   _v('s-vllm-dtype') || 'auto',
    enforce_eager:           _c('s-vllm-enforce-eager'),
  };
  await infraMod.vllm.saveConfig(payload);
  _toast('vLLM config saved');
}

// ── Sandbox tab ───────────────────────────────────────────────────────────────

async function _loadSandboxTab() {
  const d = await infraMod.sandbox.loadConfig().catch(() => null);
  if (!d) return;
  _si('s-sandbox-workspace',   d.workspace_root);
  _si('s-sandbox-py-timeout',  d.python_timeout_secs ?? 10);
  _si('s-sandbox-py-maxout',   d.python_max_output_chars ?? 5000);
  _si('s-sandbox-py-blocked',  (d.python_blocked_modules ?? []).join(', '));
  _si('s-sandbox-http-allow',  (d.http_allowed_domains ?? []).join(', '));
  _si('s-sandbox-http-block',  (d.http_blocked_domains ?? []).join(', '));
  _si('s-sandbox-max-file',    d.max_file_size_bytes ?? 10485760);
}

export async function saveSandboxTab() {
  const _arr = id => _v(id).split(',').map(s => s.trim()).filter(Boolean);
  const payload = {
    workspace_root:          _v('s-sandbox-workspace'),
    python_timeout_secs:     parseInt(_v('s-sandbox-py-timeout'))  || 10,
    python_max_output_chars: parseInt(_v('s-sandbox-py-maxout'))   || 5000,
    python_blocked_modules:  _arr('s-sandbox-py-blocked'),
    http_allowed_domains:    _arr('s-sandbox-http-allow'),
    http_blocked_domains:    _arr('s-sandbox-http-block'),
    max_file_size_bytes:     parseInt(_v('s-sandbox-max-file'))    || 10485760,
  };
  await infraMod.sandbox.saveConfig(payload);
  _toast('Sandbox config saved');
}

// ── Modal footer Save button ──────────────────────────────────────────────────

export async function saveCurrentTab() {
  const msgEl = $('modal-msg');
  if (msgEl) { msgEl.textContent = ''; msgEl.className = ''; }
  const actions = {
    model:   saveModelTab,
    memory:  saveMemoryTab,
    persona: savePersonaTab,
    voice:   saveVoiceTab,
    vllm:    saveVLLMTab,
    sandbox: saveSandboxTab,
  };
  const fn = actions[_activeTab];
  if (!fn) return;
  if (msgEl) msgEl.textContent = 'Saving…';
  await fn().catch(e => {
    if (msgEl) { msgEl.textContent = e.message; msgEl.className = 'err'; }
    throw e;
  });
  if (msgEl) { msgEl.textContent = 'Saved ✓'; msgEl.className = 'ok'; }
  setTimeout(() => { if (msgEl) { msgEl.textContent = ''; msgEl.className = ''; } }, 2000);
}
