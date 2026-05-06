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

  const state = s?.state ?? 'unavailable';
  if (badgeEl) {
    if (state === 'connected')  { badgeEl.textContent = 'ON';  badgeEl.className = 'mc-badge on'; }
    else if (state === 'connecting') { badgeEl.textContent = '…'; badgeEl.className = 'mc-badge'; }
    else                             { badgeEl.textContent = 'OFF'; badgeEl.className = 'mc-badge off'; }
  }

  const url      = c?.ws_url || '—';
  const sessions = s?.sessions ?? 0;
  const prefix   = c?.command_prefix ? `<code style="font-size:11px">${_esc(c.command_prefix)}</code>` : '<span style="color:var(--text3)">无前缀</span>';

  bodyEl.innerHTML = `
    <div class="mc-row"><span class="mc-key">状态</span>
      <span class="mc-val">${_stateLabel(state)}</span></div>
    <div class="mc-row"><span class="mc-key">WS</span>
      <span class="mc-val mc-truncate" title="${_esc(url)}">${_esc(url)}</span></div>
    <div class="mc-row"><span class="mc-key">会话</span>
      <span class="mc-val">${sessions} 活跃</span></div>
    <div class="mc-row"><span class="mc-key">前缀</span>
      <span class="mc-val">${prefix}</span></div>`;
}

function _stateLabel(state) {
  if (state === 'connected')   return '<span style="color:#16a34a">已连接</span>';
  if (state === 'connecting')  return '<span style="color:#1e40af">连接中…</span>';
  if (state === 'unavailable') return '<span style="color:var(--text3)">未启动</span>';
  return `<span style="color:var(--text3)">${_esc(state)}</span>`;
}

function _esc(s) {
  return String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}
