import * as llmMod   from '../../modules/llm.js';
import * as reactMod  from '../../modules/react.js';
import { $, _v, _c, _si, _sc } from './_helpers.js';

export async function load() {
  const d = await llmMod.loadConfig().catch(() => null);
  if (!d) return;
  _si('s-model',          d.model);
  _si('s-apikey',         d.api_key);
  _si('s-baseurl',        d.base_url);
  _si('s-maxtokens',      d.max_tokens ?? 512);
  _si('s-temp',           d.temperature ?? 1.0);
  _si('s-sysprompt',      d.system_prompt ?? '');
  _si('s-lang',           d.prompt_lang ?? 'cn');
  _si('s-maxsteps',       d.max_steps ?? 10);
  _sc('s-tools-enabled',  d.tools_enabled ?? false);
  _sc('s-show-full-prompt', d.show_full_prompt ?? false);
  $('react-cfg-fields')?.classList.toggle('hidden', !(d.tools_enabled ?? false));
}

export async function save() {
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
  if (payload.tools_enabled)
    reactMod.init({ profile: 'default', lang: payload.prompt_lang });
}

export function onToggleTools() {
  $('react-cfg-fields')?.classList.toggle('hidden', !_c('s-tools-enabled'));
}
