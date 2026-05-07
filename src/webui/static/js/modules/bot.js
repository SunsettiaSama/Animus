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

// ── Workstation card ──────────────────────────────────────────────────────────

export async function updateWorkstationCard() {
  const badgeEl = document.getElementById('mc-bot-badge');
  const bodyEl  = document.getElementById('mc-bot-body');
  if (!bodyEl) return;

  const [cfg, st] = await Promise.allSettled([loadConfig(), getStatus()]);
  const c = cfg.status === 'fulfilled' ? cfg.value : null;
  const s = st.status  === 'fulfilled' ? st.value  : null;

  const state    = (s?.state         ?? 'unavailable').trim();
  const svcState = (s?.service_state ?? '').trim();
  // Consider the service "on" if either the transport is connected/running OR
  // the service itself reports running (transport may lag on first connect).
  const isOn       = state === 'connected' || state === 'running' || svcState === 'running';
  const isLoading  = !isOn && state === 'connecting';
  if (badgeEl) {
    if (isOn)       { badgeEl.textContent = 'ON';  badgeEl.className = 'mc-badge on'; }
    else if (isLoading) { badgeEl.textContent = '…';   badgeEl.className = 'mc-badge'; }
    else            { badgeEl.textContent = 'OFF'; badgeEl.className = 'mc-badge off'; }
  }

  const transport = c?.transport ?? 'forward_ws';
  const connInfo  = transport === 'qq_official'
    ? (c?.appid ? `appid: ${_esc(c.appid)}` : '—')
    : _esc(c?.ws_url || '—');
  const connLabel = transport === 'qq_official' ? 'AppID' : 'WS';
  const sessions  = s?.active_sessions ?? 0;
  const prefix    = c?.command_prefix
    ? `<code style="font-size:11px">${_esc(c.command_prefix)}</code>`
    : '<span style="color:var(--text3)">无前缀</span>';

  bodyEl.innerHTML = `
    <div class="mc-row"><span class="mc-key">状态</span>
      <span class="mc-val">${_stateLabel(state)}</span></div>
    <div class="mc-row"><span class="mc-key">${connLabel}</span>
      <span class="mc-val mc-truncate" title="${connInfo}">${connInfo}</span></div>
    <div class="mc-row"><span class="mc-key">会话</span>
      <span class="mc-val">${sessions} 活跃</span></div>
    <div class="mc-row"><span class="mc-key">前缀</span>
      <span class="mc-val">${prefix}</span></div>`;
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
