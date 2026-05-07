import * as voiceMod from '../../modules/voice.js';
import { $, _v, _c, _si, _sc } from './_helpers.js';

export async function load() {
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
    _si('s-stt-provider',        d.provider);
    _si('s-stt-language',        d.language);
    _si('s-stt-openai-model',    d.openai_model);
    _si('s-stt-openai-base-url', d.openai_base_url);
    _si('s-stt-openai-api-key',  d.openai_api_key);
    _si('s-stt-local-path',      d.local_model_path);
    _si('s-stt-local-size',      d.local_model_size);
    _si('s-stt-local-device',    d.local_device);
    _si('s-stt-local-compute',   d.local_compute_type);
    _si('s-stt-hf-endpoint',     d.hf_endpoint);
    _si('s-stt-hf-token',        d.hf_token);
    onSTTProviderChange();
  }
}

export async function save() {
  await voiceMod.saveTTSConfig({
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
  });
  await voiceMod.saveSTTConfig({
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
  });
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
