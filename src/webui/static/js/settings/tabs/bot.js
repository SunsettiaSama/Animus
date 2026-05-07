import * as infraMod from '../../modules/infra.js';
import * as botMod    from '../../modules/bot.js';
import { $, _v, _c, _si, _sc } from './_helpers.js';

export function onBotTransportChange() {
  const t = _v('s-bot-transport');
  $('bot-forward-ws-section')?.classList.toggle('hidden', t !== 'forward_ws');
  $('bot-official-section')?.classList.toggle('hidden', t !== 'qq_official');
}

export async function load() {
  const d = await infraMod.bot.loadConfig().catch(() => null);
  if (!d) return;
  _sc('s-bot-enabled',      d.enabled ?? false);
  _si('s-bot-transport',    d.transport ?? 'forward_ws');
  _si('s-bot-ws-url',       d.ws_url ?? '');
  _si('s-bot-token',        d.access_token ?? '');
  _si('s-bot-reconnect',    d.reconnect_interval_sec ?? 5);
  _si('s-bot-appid',        d.appid ?? '');
  _si('s-bot-secret',       d.secret ?? '');
  _sc('s-bot-sandbox',      d.is_sandbox ?? false);
  _si('s-bot-users',        (d.allowed_private_users ?? []).join(', '));
  _si('s-bot-groups',       (d.allowed_groups ?? []).join(', '));
  _si('s-bot-prefix',       d.command_prefix ?? '');
  _si('s-bot-max-sessions', d.max_sessions ?? 100);
  _si('s-bot-ttl',          d.session_ttl_hours ?? 24);
  _si('s-bot-invite-code',  d.invite_code ?? '');
  _si('s-bot-invite-limit', d.invite_daily_limit ?? 4);
  onBotTransportChange();

  const st    = await infraMod.bot.status().catch(() => null);
  const badge = $('s-bot-status-badge');
  if (badge && st) {
    const state    = (st.state         ?? 'unknown').trim();
    const svcState = (st.service_state ?? '').trim();
    const isOn      = state === 'connected' || state === 'running' || svcState === 'running';
    const isLoading = !isOn && state === 'connecting';
    badge.textContent = state;
    badge.className   = 'bot-status-badge ' + (isOn ? 'ok' : isLoading ? 'loading' : 'off');
    const sessEl = $('s-bot-sessions-count');
    if (sessEl) sessEl.textContent = `${st.active_sessions ?? 0} active sessions`;
  }
}

export async function save() {
  const _ids = id => _v(id).split(',').map(s => s.trim()).filter(s => s.length > 0);
  await botMod.saveConfig({
    enabled:                _c('s-bot-enabled'),
    transport:              _v('s-bot-transport'),
    ws_url:                 _v('s-bot-ws-url'),
    access_token:           _v('s-bot-token'),
    reconnect_interval_sec: parseFloat(_v('s-bot-reconnect')) || 5,
    appid:                  _v('s-bot-appid'),
    secret:                 _v('s-bot-secret'),
    is_sandbox:             _c('s-bot-sandbox'),
    allowed_private_users:  _ids('s-bot-users'),
    allowed_groups:         _ids('s-bot-groups'),
    command_prefix:         _v('s-bot-prefix'),
    max_sessions:           parseInt(_v('s-bot-max-sessions')) || 100,
    session_ttl_hours:      parseFloat(_v('s-bot-ttl')) || 24,
    invite_code:            _v('s-bot-invite-code').trim(),
    invite_daily_limit:     parseInt(_v('s-bot-invite-limit')) || 4,
  });
}
