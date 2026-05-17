import { _v, _c, _si, _sc } from './_helpers.js';

const $ = id => document.getElementById(id);

// ── 状态提示工具 ───────────────────────────────────────────────────────────

function _setMsg(elId, text, isErr = false) {
  const el = $(elId);
  if (!el) return;
  el.textContent = text;
  el.style.color = isErr ? 'var(--danger, #e05)' : 'var(--text3)';
  if (text && !isErr) setTimeout(() => { if (el.textContent === text) el.textContent = ''; }, 2500);
}

// ── Load ──────────────────────────────────────────────────────────────────

export async function load() {
  const [bark, ntfy] = await Promise.all([
    fetch('/api/notify/bark/config').then(r => r.ok ? r.json() : null).catch(() => null),
    fetch('/api/notify/ntfy/config').then(r => r.ok ? r.json() : null).catch(() => null),
  ]);

  if (bark) {
    _sc('s-bark-enabled',     bark.enabled    ?? false);
    _si('s-bark-server-url',  bark.server_url ?? 'https://api.day.app');
    _si('s-bark-device-key',  bark.device_key ?? '');
    _si('s-bark-sound',       bark.sound      ?? '');
    _si('s-bark-group',       bark.group      ?? 'ReAct');
  }

  if (ntfy) {
    _sc('s-ntfy-enabled',     ntfy.enabled    ?? false);
    _si('s-ntfy-server-url',  ntfy.server_url ?? 'https://ntfy.sh');
    _si('s-ntfy-topic',       ntfy.topic      ?? '');
    _si('s-ntfy-username',    ntfy.username   ?? '');
    _si('s-ntfy-password',    ntfy.password   ?? '');
    const pri = $('s-ntfy-priority');
    if (pri) pri.value = String(ntfy.priority ?? 3);
  }
}

// ── Save ──────────────────────────────────────────────────────────────────

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

export async function save() {
  await Promise.all([_saveBark(), _saveNtfy()]);
}

// ── Test ──────────────────────────────────────────────────────────────────

export async function testBark() {
  _setMsg('bark-cfg-msg', '发送中…');
  const res = await fetch('/api/notify/bark/test', { method: 'POST' });
  const d = await res.json().catch(() => ({}));
  if (res.ok) {
    _setMsg('bark-cfg-msg', '✓ 发送成功');
  } else {
    _setMsg('bark-cfg-msg', `✗ ${d.error ?? '发送失败'}`, true);
  }
}

export async function testNtfy() {
  _setMsg('ntfy-cfg-msg', '发送中…');
  const res = await fetch('/api/notify/ntfy/test', { method: 'POST' });
  const d = await res.json().catch(() => ({}));
  if (res.ok) {
    _setMsg('ntfy-cfg-msg', '✓ 发送成功');
  } else {
    _setMsg('ntfy-cfg-msg', `✗ ${d.error ?? '发送失败'}`, true);
  }
}

// ── Dedicated save buttons (wired in app.js) ─────────────────────────────

export async function saveBarkWithFeedback() {
  _setMsg('bark-cfg-msg', '保存中…');
  await _saveBark().then(() => _setMsg('bark-cfg-msg', '✓ 已保存'))
                   .catch(e => _setMsg('bark-cfg-msg', e.message, true));
}

export async function saveNtfyWithFeedback() {
  _setMsg('ntfy-cfg-msg', '保存中…');
  await _saveNtfy().then(() => _setMsg('ntfy-cfg-msg', '✓ 已保存'))
                   .catch(e => _setMsg('ntfy-cfg-msg', e.message, true));
}
