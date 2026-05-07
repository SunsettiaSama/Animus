import * as infraMod from '../../modules/infra.js';
import { bus } from '../../eventBus.js';
import { $, _v, _c, _si, _sc } from './_helpers.js';

export async function load() {
  const d = await infraMod.vllm.loadConfig().catch(() => null);
  if (!d) return;
  _si('s-vllm-provider',      d.provider ?? 'official');
  _si('s-vllm-host',          d.host ?? '127.0.0.1');
  _si('s-vllm-port',          d.port ?? 8000);
  _si('s-vllm-tp',            d.tensor_parallel_size ?? 1);
  _si('s-vllm-pp',            d.pipeline_parallel_size ?? 1);
  _si('s-vllm-gpu-util',      d.gpu_memory_utilization ?? 0.90);
  _si('s-vllm-max-len',       d.max_model_len ?? '');
  _si('s-vllm-quant',         d.quantization ?? '');
  _si('s-vllm-dtype',         d.dtype ?? 'auto');
  _sc('s-vllm-enforce-eager', d.enforce_eager);
  _updateProviderNotice();
}

function _updateProviderNotice() {
  const sel    = $('s-vllm-provider');
  const notice = $('vllm-custom-notice');
  if (!sel || !notice) return;
  notice.style.display = sel.value === 'custom' ? '' : 'none';
  sel.addEventListener('change', () => {
    notice.style.display = sel.value === 'custom' ? '' : 'none';
  }, { once: true });
}

export async function save() {
  await infraMod.vllm.saveConfig({
    provider:               _v('s-vllm-provider') || 'official',
    host:                   _v('s-vllm-host'),
    port:                   parseInt(_v('s-vllm-port'))       || 8000,
    tensor_parallel_size:   parseInt(_v('s-vllm-tp'))         || 1,
    pipeline_parallel_size: parseInt(_v('s-vllm-pp'))         || 1,
    gpu_memory_utilization: parseFloat(_v('s-vllm-gpu-util')) || 0.90,
    max_model_len:          parseInt(_v('s-vllm-max-len'))    || null,
    quantization:           _v('s-vllm-quant') || null,
    dtype:                  _v('s-vllm-dtype') || 'auto',
    enforce_eager:          _c('s-vllm-enforce-eager'),
  });
  bus.emit('toast', 'vLLM config saved');
}
