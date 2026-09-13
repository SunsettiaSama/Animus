import * as llmMod   from '../../../features/basics.js';
import * as infraMod  from '../../../features/basics.js';
import * as reactMod  from '../../../features/basics.js';
import { $, _v, _c, _si, _sc } from './_helpers.js';

// ── 次语言模型（aux）区块 ─────────────────────────────────────────────────────

const AUX_LABELS = {
  life: 'Life（体验编写）',
  persona: 'Persona（画像蒸馏）',
  memory: 'Memory（反刍/睡眠过滤）',
  presence: 'Presence（当下态蒸馏）',
  speak: 'Speak（对话引擎）',
  speak_director: 'Speak Director（导演旁链）',
  heartbeat: 'Heartbeat（心跳）',
};

function _renderAuxRows(slots) {
  const host = $('llm-aux-rows');
  if (!host) return;
  host.innerHTML = (slots || []).map(slot => `
    <div class="aux-slot-row" data-aux-slot="${slot}"
         style="display:grid;grid-template-columns:auto 150px 1fr 1fr 1fr 74px;gap:8px;align-items:center;margin-bottom:8px">
      <label class="switch" title="启用后该槽位使用独立模型，否则回退主模型">
        <input type="checkbox" id="s-aux-${slot}-enabled"><span class="slider"></span>
      </label>
      <span style="font-size:12px;color:var(--text2)">${AUX_LABELS[slot] ?? slot}</span>
      <input id="s-aux-${slot}-model" type="text" placeholder="model 名" />
      <input id="s-aux-${slot}-baseurl" type="text" placeholder="base_url（可选）" />
      <input id="s-aux-${slot}-apikey" type="password" placeholder="api_key（可选）" />
      <input id="s-aux-${slot}-maxtokens" type="number" placeholder="512" />
    </div>`).join('');
}

function _fillAuxRows(models) {
  for (const [slot, cfg] of Object.entries(models ?? {})) {
    _sc(`s-aux-${slot}-enabled`, cfg.enabled ?? false);
    _si(`s-aux-${slot}-model`, cfg.model ?? '');
    _si(`s-aux-${slot}-baseurl`, cfg.base_url ?? '');
    _si(`s-aux-${slot}-apikey`, cfg.api_key ?? '');
    _si(`s-aux-${slot}-maxtokens`, cfg.max_tokens ?? 512);
  }
}

function _collectAuxPayload() {
  const models = {};
  document.querySelectorAll('#llm-aux-rows .aux-slot-row').forEach(row => {
    const slot = row.dataset.auxSlot;
    if (!slot) return;
    models[slot] = {
      enabled: _c(`s-aux-${slot}-enabled`),
      backend: 'openai',
      model: _v(`s-aux-${slot}-model`) ?? '',
      base_url: _v(`s-aux-${slot}-baseurl`) ?? '',
      api_key: _v(`s-aux-${slot}-apikey`) ?? '',
      max_tokens: parseInt(_v(`s-aux-${slot}-maxtokens`), 10) || 512,
      temperature: 0.7,
      device: 'auto',
    };
  });
  return { models };
}

async function _loadAuxSection() {
  const aux = await llmMod.loadAux().catch(() => null);
  if (!aux) return;
  _renderAuxRows(aux.slots);
  _fillAuxRows(aux.models);
}

async function _saveAuxSection() {
  const msg = $('llm-aux-msg');
  try {
    const data = await llmMod.saveAux(_collectAuxPayload());
    if (msg && data?.applied) {
      const lines = Object.entries(data.applied)
        .map(([slot, result]) => `${slot}: ${result}`)
        .join('；');
      msg.textContent = lines;
    }
  } catch (err) {
    if (msg) msg.textContent = `保存失败：${err?.message ?? err}`;
  }
}

// ── Backend section visibility ────────────────────────────────────────────────

export function onBackendChange() {
  const b = _v('s-backend');
  $('llm-api-section')?.classList.toggle('hidden', b !== 'openai');
  $('llm-local-section')?.classList.toggle('hidden', b !== 'transformers');
  $('llm-vllm-section')?.classList.toggle('hidden', b !== 'vllm' && b !== 'vllm-clone');
  // Sync hidden provider select to backend so save() always sends the right value
  if (b === 'vllm')       _si('s-vllm-provider', 'official');
  if (b === 'vllm-clone') _si('s-vllm-provider', 'custom');
  _updateVllmProviderNotice();
}

function _updateVllmProviderNotice() {
  const notice = $('vllm-custom-notice');
  if (!notice) return;
  const b = _v('s-backend') ?? '';
  notice.style.display = b === 'vllm-clone' ? '' : 'none';
}

// ── Load ──────────────────────────────────────────────────────────────────────

export async function load() {
  const d = await llmMod.loadConfig().catch(() => null);
  if (!d) return;

  // Backend selector
  _si('s-backend', d.backend ?? 'openai');

  // Model (always visible)
  _si('s-model', d.model);

  // API section
  _si('s-apikey',   d.api_key);
  _si('s-baseurl',  d.base_url);
  _si('s-maxtokens', d.max_tokens ?? 512);
  _si('s-temp',      d.temperature ?? 1.0);

  // Local section
  _si('s-device',      d.device ?? 'auto');
  _si('s-maxtokens-local', d.max_tokens ?? 512);
  _si('s-top-k',       d.top_k ?? 0);
  _si('s-rep-penalty', d.repetition_penalty ?? 1.0);
  _sc('s-do-sample',   d.do_sample ?? false);

  // vLLM section — load from vllm config endpoint
  const vd = await infraMod.vllm.loadConfig().catch(() => null);
  if (vd) {
    _si('s-vllm-provider',     vd.provider ?? 'official');
    _si('s-vllm-host',         vd.host ?? '127.0.0.1');
    _si('s-vllm-port',         vd.port ?? 8000);
    _si('s-vllm-tp',           vd.tensor_parallel_size ?? 1);
    _si('s-vllm-pp',           vd.pipeline_parallel_size ?? 1);
    _si('s-vllm-gpu-util',     vd.gpu_memory_utilization ?? 0.90);
    _si('s-vllm-max-len',      vd.max_model_len ?? '');
    _si('s-vllm-quant',        vd.quantization ?? '');
    _si('s-vllm-dtype',        vd.dtype ?? 'auto');
    _sc('s-vllm-enforce-eager', vd.enforce_eager ?? false);
  }

  // Common
  _si('s-sysprompt',  d.system_prompt ?? '');
  _si('s-lang',       d.prompt_lang ?? 'cn');
  _si('s-maxsteps',   d.max_steps ?? 10);
  _sc('s-tools-enabled',    d.tools_enabled ?? false);
  _sc('s-show-full-prompt', d.show_full_prompt ?? false);
  $('react-cfg-fields')?.classList.toggle('hidden', !(d.tools_enabled ?? false));

  // Apply section visibility
  onBackendChange();

  // 次语言模型（aux）区块
  await _loadAuxSection();
}

// ── Save ──────────────────────────────────────────────────────────────────────

export async function save() {
  const backend = _v('s-backend') ?? 'openai';
  const isLocal = backend === 'transformers';
  const isVllm  = backend === 'vllm' || backend === 'vllm-clone';

  const payload = {
    backend,
    model:            _v('s-model'),
    api_key:          _v('s-apikey'),
    base_url:         _v('s-baseurl'),
    max_tokens:       parseInt(isLocal ? _v('s-maxtokens-local') : _v('s-maxtokens')) || 512,
    temperature:      parseFloat(_v('s-temp')) || 1.0,
    do_sample:        _c('s-do-sample'),
    top_k:            parseInt(_v('s-top-k')) || 0,
    repetition_penalty: parseFloat(_v('s-rep-penalty')) || 1.0,
    device:           _v('s-device') ?? 'auto',
    system_prompt:    _v('s-sysprompt'),
    prompt_lang:      _v('s-lang'),
    max_steps:        parseInt(_v('s-maxsteps')) || 10,
    tools_enabled:    _c('s-tools-enabled'),
    show_full_prompt: _c('s-show-full-prompt'),
  };

  await llmMod.saveConfig(payload);

  // Persist vLLM-specific config separately when applicable
  if (isVllm) {
    await infraMod.vllm.saveConfig({
      provider:               _v('s-vllm-provider') || 'official',
      host:                   _v('s-vllm-host'),
      port:                   parseInt(_v('s-vllm-port')) || 8000,
      tensor_parallel_size:   parseInt(_v('s-vllm-tp')) || 1,
      pipeline_parallel_size: parseInt(_v('s-vllm-pp')) || 1,
      gpu_memory_utilization: parseFloat(_v('s-vllm-gpu-util')) || 0.90,
      max_model_len:          parseInt(_v('s-vllm-max-len')) || null,
      quantization:           _v('s-vllm-quant') || null,
      dtype:                  _v('s-vllm-dtype') || 'auto',
      enforce_eager:          _c('s-vllm-enforce-eager'),
    });
  }

  await llmMod.initLLM(payload);

  if (payload.tools_enabled)
    reactMod.init({ profile: 'default', lang: payload.prompt_lang });

  // 次语言模型（aux）：独立保存并热应用，失败不阻塞主配置保存
  await _saveAuxSection();
}

// ── Tool toggle ───────────────────────────────────────────────────────────────

export function onToggleTools() {
  $('react-cfg-fields')?.classList.toggle('hidden', !_c('s-tools-enabled'));
}
