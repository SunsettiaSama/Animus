import * as infraMod from '../../modules/infra.js';
import { bus } from '../../eventBus.js';
import { _v, _c, _si, _sc } from './_helpers.js';

export async function load() {
  const d = await infraMod.sandbox.loadConfig().catch(() => null);
  if (!d) return;
  _si('s-sandbox-workspace',  d.workspace_root);
  _si('s-sandbox-py-timeout', d.python_timeout_secs ?? 10);
  _si('s-sandbox-py-maxout',  d.python_max_output_chars ?? 5000);
  _si('s-sandbox-py-blocked', (d.python_blocked_modules ?? []).join(', '));
  _si('s-sandbox-http-allow', (d.http_allowed_domains ?? []).join(', '));
  _si('s-sandbox-http-block', (d.http_blocked_domains ?? []).join(', '));
  _si('s-sandbox-max-file',   d.max_file_size_bytes ?? 10485760);
}

export async function save() {
  const _arr = id => _v(id).split(',').map(s => s.trim()).filter(Boolean);
  await infraMod.sandbox.saveConfig({
    workspace_root:          _v('s-sandbox-workspace'),
    python_timeout_secs:     parseInt(_v('s-sandbox-py-timeout')) || 10,
    python_max_output_chars: parseInt(_v('s-sandbox-py-maxout'))  || 5000,
    python_blocked_modules:  _arr('s-sandbox-py-blocked'),
    http_allowed_domains:    _arr('s-sandbox-http-allow'),
    http_blocked_domains:    _arr('s-sandbox-http-block'),
    max_file_size_bytes:     parseInt(_v('s-sandbox-max-file'))   || 10485760,
  });
  bus.emit('toast', 'Sandbox config saved');
}
