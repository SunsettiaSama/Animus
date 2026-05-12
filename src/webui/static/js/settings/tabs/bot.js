import * as infraMod from '../../modules/infra.js';
import * as botMod    from '../../modules/bot.js';
import { $, _v, _c, _si, _sc } from './_helpers.js';

// ── Transport section toggle ──────────────────────────────────────────────────

export function onBotTransportChange() {
  const t = _v('s-bot-transport');
  $('bot-forward-ws-section')?.classList.toggle('hidden', t !== 'forward_ws');
  $('bot-official-section')?.classList.toggle('hidden', t !== 'qq_official');
  if (t === 'qq_official') _loadPublicIp();
}

async function _loadPublicIp() {
  const el = $('s-bot-public-ip');
  if (!el) return;
  el.textContent = '查询中…';
  const d = await botMod.getPublicIp().catch(() => null);
  el.textContent = d?.ip ?? '查询失败';
}

// ── Channel selector ─────────────────────────────────────────────────────────

export function onChannelChange() {
  const ch = _v('s-channel-select');
  localStorage.setItem('react-active-channel', ch);
  $('channel-bot-section')?.classList.toggle('hidden',  ch !== 'bot');
  $('channel-bark-section')?.classList.toggle('hidden', ch !== 'bark');
  $('channel-ntfy-section')?.classList.toggle('hidden', ch !== 'ntfy');
}

// ── Notify section helpers ────────────────────────────────────────────────────

function _setNotifyMsg(elId, text, isErr = false) {
  const el = $(elId);
  if (!el) return;
  el.textContent = text;
  el.style.color = isErr ? 'var(--danger, #e05)' : 'var(--text3)';
  if (text && !isErr) setTimeout(() => { if (el.textContent === text) el.textContent = ''; }, 2500);
}

// ── Load ──────────────────────────────────────────────────────────────────────

export async function load() {
  // ── Bot config ──────────────────────────────────────────────────────────────
  const d = await infraMod.bot.loadConfig().catch(() => null);
  if (d) {
    _sc('s-bot-enabled',      d.enabled ?? false);
    _si('s-bot-transport',    d.transport ?? 'forward_ws');
    _si('s-bot-ws-url',       d.ws_url ?? '');
    _si('s-bot-token',        d.access_token ?? '');
    _si('s-bot-reconnect',    d.reconnect_interval_sec ?? 5);
    _si('s-bot-appid',        d.appid ?? '');
    _si('s-bot-secret',       d.secret ?? '');
    _sc('s-bot-sandbox',      d.is_sandbox ?? false);
    _si('s-bot-proxy',        d.proxy ?? '');
    _si('s-bot-users',        (d.allowed_private_users ?? []).join(', '));
    _si('s-bot-groups',       (d.allowed_groups ?? []).join(', '));
    _si('s-bot-prefix',       d.command_prefix ?? '');
    _si('s-bot-max-sessions', d.max_sessions ?? 100);
    _si('s-bot-ttl',          d.session_ttl_hours ?? 24);
    _si('s-bot-invite-code',  d.invite_code ?? '');
    _si('s-bot-invite-limit', d.invite_daily_limit ?? 4);
    _sc('s-bot-show-step-progress', d.show_step_progress    ?? false);
    _si('s-bot-debounce',          d.message_debounce_secs ?? 2);
    onBotTransportChange();
  }

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
    if (sessEl) sessEl.textContent = `${st.active_sessions ?? 0} 个活跃会话`;
  }

  // ── Notify config ───────────────────────────────────────────────────────────
  const [bark, ntfy] = await Promise.all([
    fetch('/api/notify/bark/config').then(r => r.ok ? r.json() : null).catch(() => null),
    fetch('/api/notify/ntfy/config').then(r => r.ok ? r.json() : null).catch(() => null),
  ]);

  if (bark) {
    _sc('s-bark-enabled',    bark.enabled    ?? false);
    _si('s-bark-server-url', bark.server_url ?? 'https://api.day.app');
    _si('s-bark-device-key', bark.device_key ?? '');
    _si('s-bark-sound',      bark.sound      ?? '');
    _si('s-bark-group',      bark.group      ?? 'ReAct');
  }

  if (ntfy) {
    _sc('s-ntfy-enabled',    ntfy.enabled    ?? false);
    _si('s-ntfy-server-url', ntfy.server_url ?? 'https://ntfy.sh');
    _si('s-ntfy-topic',      ntfy.topic      ?? '');
    _si('s-ntfy-username',   ntfy.username   ?? '');
    _si('s-ntfy-password',   ntfy.password   ?? '');
    const pri = $('s-ntfy-priority');
    if (pri) pri.value = String(ntfy.priority ?? 3);
  }

  // Restore the channel selection the user last saved, falling back to
  // inferring from which channels are enabled.
  const sel = $('s-channel-select');
  if (sel) {
    const saved = localStorage.getItem('react-active-channel');
    const validChannels = ['bot', 'bark', 'ntfy'];
    if (saved && validChannels.includes(saved)) {
      sel.value = saved;
    } else {
      const botEnabled  = d?.enabled  ?? false;
      const barkEnabled = !!(bark?.enabled && bark?.device_key);
      const ntfyEnabled = !!(ntfy?.enabled && ntfy?.topic);
      if (!botEnabled && barkEnabled) {
        sel.value = 'bark';
      } else if (!botEnabled && ntfyEnabled) {
        sel.value = 'ntfy';
      }
    }
  }

  onChannelChange();
}

// ── Save ──────────────────────────────────────────────────────────────────────

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
    proxy:                  _v('s-bot-proxy').trim(),
    allowed_private_users:  _ids('s-bot-users'),
    allowed_groups:         _ids('s-bot-groups'),
    command_prefix:         _v('s-bot-prefix'),
    max_sessions:           parseInt(_v('s-bot-max-sessions')) || 100,
    session_ttl_hours:      parseFloat(_v('s-bot-ttl')) || 24,
    invite_code:              _v('s-bot-invite-code').trim(),
    invite_daily_limit:       parseInt(_v('s-bot-invite-limit')) || 4,
    show_step_progress:    _c('s-bot-show-step-progress'),
    message_debounce_secs: parseFloat(_v('s-bot-debounce')) || 0,
  });

  await Promise.all([_saveBark(), _saveNtfy()]);
}

// ── Bark save / test ──────────────────────────────────────────────────────────

async function _saveBark() {
  const res = await fetch('/api/notify/bark/config', {
    method:  'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      enabled:    _c('s-bark-enabled'),
      server_url: _v('s-bark-server-url').trim(),
      device_key: _v('s-bark-device-key').trim(),
      sound:      _v('s-bark-sound').trim(),
      group:      _v('s-bark-group').trim(),
    }),
  });
  if (!res.ok) {
    const e = await res.json().catch(() => ({}));
    throw new Error(e.error ?? 'Failed to save Bark config');
  }
}

async function _saveNtfy() {
  const res = await fetch('/api/notify/ntfy/config', {
    method:  'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      enabled:    _c('s-ntfy-enabled'),
      server_url: _v('s-ntfy-server-url').trim(),
      topic:      _v('s-ntfy-topic').trim(),
      username:   _v('s-ntfy-username').trim(),
      password:   _v('s-ntfy-password'),
      priority:   parseInt(_v('s-ntfy-priority')) || 3,
    }),
  });
  if (!res.ok) {
    const e = await res.json().catch(() => ({}));
    throw new Error(e.error ?? 'Failed to save ntfy config');
  }
}

export async function testBark() {
  _setNotifyMsg('bark-cfg-msg', '发送中…');
  const res = await fetch('/api/notify/bark/test', { method: 'POST' });
  const d = await res.json().catch(() => ({}));
  res.ok
    ? _setNotifyMsg('bark-cfg-msg', '✓ 发送成功')
    : _setNotifyMsg('bark-cfg-msg', `✗ ${d.error ?? '发送失败'}`, true);
}

export async function testNtfy() {
  _setNotifyMsg('ntfy-cfg-msg', '发送中…');
  const res = await fetch('/api/notify/ntfy/test', { method: 'POST' });
  const d = await res.json().catch(() => ({}));
  res.ok
    ? _setNotifyMsg('ntfy-cfg-msg', '✓ 发送成功')
    : _setNotifyMsg('ntfy-cfg-msg', `✗ ${d.error ?? '发送失败'}`, true);
}
