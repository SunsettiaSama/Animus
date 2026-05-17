/**
 * modules/bot.js — Bot service config / control helpers.
 */

import { http, PATHS } from '../api.js';

const _cb = { onToast: () => {} };
export function setCallbacks(cbs) { Object.assign(_cb, cbs); }

export const loadConfig  = () => http.get(PATHS.infra.bot.config);
export const saveConfig  = payload => http.post(PATHS.infra.bot.save, payload).then(() => _cb.onToast('Bot config saved'));
export const getStatus   = () => http.get(PATHS.infra.bot.status);
export const getSessions = () => http.get(PATHS.infra.bot.sessions);
export const start       = () => http.post(PATHS.infra.bot.start, {}).then(d => { _cb.onToast('Bot service starting…'); return d; });
export const stop        = () => http.post(PATHS.infra.bot.stop,  {}).then(() => _cb.onToast('Bot service stopped'));
export const getPublicIp = () => http.get(PATHS.infra.bot.publicIp);

// ── Workstation card ──────────────────────────────────────────────────────────

export async function updateWorkstationCard() {
  const badgeEl = document.getElementById('mc-bot-badge');
  const bodyEl  = document.getElementById('mc-bot-body');
  if (!bodyEl) return null;

  const [cfgR, stR, barkR, ntfyR] = await Promise.allSettled([
    loadConfig(),
    getStatus(),
    fetch('/api/notify/bark/config').then(r => r.ok ? r.json() : null),
    fetch('/api/notify/ntfy/config').then(r => r.ok ? r.json() : null),
  ]);
  const c    = cfgR.status === 'fulfilled' ? cfgR.value : null;
  const s    = stR.status  === 'fulfilled' ? stR.value  : null;
  const bark = barkR.status === 'fulfilled' ? barkR.value : null;
  const ntfy = ntfyR.status === 'fulfilled' ? ntfyR.value : null;

  const state    = (s?.state         ?? 'unavailable').trim();
  const svcState = (s?.service_state ?? '').trim();
  const botOn    = state === 'connected' || state === 'running' || svcState === 'running';
  const botLoading = !botOn && state === 'connecting';
  const barkOn   = !!(bark?.enabled && bark?.device_key);
  const ntfyOn   = !!(ntfy?.enabled && ntfy?.topic);
  const anyOn    = botOn || barkOn || ntfyOn;
  const anyLoading = !anyOn && botLoading;

  if (badgeEl) {
    if (anyOn)          { badgeEl.textContent = 'ON';  badgeEl.className = 'mc-badge on'; }
    else if (anyLoading){ badgeEl.textContent = '…';   badgeEl.className = 'mc-badge'; }
    else                { badgeEl.textContent = 'OFF'; badgeEl.className = 'mc-badge off'; }
  }

  const rows = [];

  // ── Bark row ────────────────────────────────────────────────────────────────
  if (bark) {
    const bLabel = barkOn
      ? '<span style="color:#16a34a">✓ 已启用</span>'
      : '<span style="color:var(--text3)">未启用</span>';
    rows.push(`<div class="mc-row"><span class="mc-key">🍎 Bark</span>
      <span class="mc-val">${bLabel}</span></div>`);
  }

  // ── ntfy row ────────────────────────────────────────────────────────────────
  if (ntfy) {
    const nLabel = ntfyOn
      ? '<span style="color:#16a34a">✓ 已启用</span>'
      : '<span style="color:var(--text3)">未启用</span>';
    rows.push(`<div class="mc-row"><span class="mc-key">📢 ntfy</span>
      <span class="mc-val">${nLabel}</span></div>`);
  }

  // ── Bot row ─────────────────────────────────────────────────────────────────
  if (c?.enabled !== false) {
    rows.push(`<div class="mc-row"><span class="mc-key">💬 Bot</span>
      <span class="mc-val">${_stateLabel(state)}</span></div>`);
    if (botOn) {
      const sessions = s?.active_sessions ?? 0;
      rows.push(`<div class="mc-row"><span class="mc-key" style="padding-left:14px">会话</span>
        <span class="mc-val">${sessions} 活跃</span></div>`);
    }
  }

  bodyEl.innerHTML = rows.length
    ? rows.join('')
    : '<span style="color:var(--text3);font-size:13px">暂无已启用渠道</span>';

  return { isOn: anyOn, state, svcState };
}

function _stateLabel(state) {
  const s = (state ?? '').trim();
  if (s === 'connected' || s === 'running')
                             return '<span style="color:#16a34a">已连接</span>';
  if (s === 'connecting')    return '<span style="color:#d97706">连接中…</span>';
  if (s === 'stopped')       return '<span style="color:var(--text3)">已停止</span>';
  if (s === 'unavailable')   return '<span style="color:var(--text3)">未启动</span>';
  if (s === 'error')         return '<span style="color:#ef4444">错误</span>';
  return `<span style="color:var(--text3)">${_esc(s)}</span>`;
}

function _esc(s) {
  return String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}
