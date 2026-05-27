/**
 * modules/soul.js — Soul 配置、就绪检测、Persona build/reload。
 */

import { http, PATHS } from '../api.js';
import { set } from '../state.js';

const _cb = {
  onToast: () => {},
  onReady: () => {},
  onStatusUpdate: () => {},
};

export function setCallbacks(cbs) {
  Object.assign(_cb, cbs);
}

export async function loadConfig() {
  return http.get(PATHS.soul.config);
}

export async function saveConfig(config) {
  await http.post(PATHS.soul.configSave, { config });
  _cb.onToast('Soul config saved（需 Reinit 后生效）');
}

export async function loadMemoryConfig() {
  return http.get(PATHS.soul.memoryConfig);
}

export async function saveMemoryConfig(config) {
  await http.post(PATHS.soul.memoryConfigSave, { config });
  _cb.onToast('Soul memory config saved');
}

export async function loadInfraConfig() {
  return http.get(PATHS.soul.memoryInfra);
}

export async function saveInfraConfig(config) {
  await http.post(PATHS.soul.memoryInfraSave, { config });
  _cb.onToast('Soul memory infra saved');
}

export async function fetchReadiness() {
  const data = await http.get(PATHS.soul.readiness);
  set('soulReady', Boolean(data.ready));
  set('speakReady', Boolean(data.speak_ready));
  _cb.onStatusUpdate(data);
  return data;
}

export async function fetchStatus() {
  const data = await http.get(PATHS.soul.status).catch(() => null);
  if (data?.state) set('soulReady', data.state === 'running');
  return data;
}

export async function rebuildPersona(preserveSelfConcept = false) {
  const data = await http.post(PATHS.soul.personaRebuild, {
    preserve_self_concept: preserveSelfConcept,
  });
  _cb.onToast('Persona build 完成');
  return data;
}

export async function reloadPersona() {
  const data = await http.post(PATHS.soul.personaReload, {});
  _cb.onToast('Persona 已从磁盘 reload');
  return data;
}

export async function fetchPersonaSnapshot() {
  return http.get(PATHS.soul.persona).catch(() => null);
}

/** 渲染 readiness checklist 到容器元素。 */
export function renderReadinessPanel(containerEl, data) {
  if (!containerEl || !data) return;
  const checks = data.checks ?? [];
  const rows = checks.map(c => {
    const icon = c.ok ? '✓' : (c.optional ? '○' : '✗');
    const cls  = c.ok ? 'ok' : (c.optional ? 'opt' : 'fail');
    return `<div class="soul-check ${cls}">
      <span class="soul-check-icon">${icon}</span>
      <span class="soul-check-label">${c.label}</span>
      ${c.ok ? '' : `<span class="soul-check-hint">${c.hint ?? ''}</span>`}
    </div>`;
  }).join('');
  const state = data.soul_state ?? '—';
  containerEl.innerHTML = `
    <div class="soul-readiness-summary">
      <span>Soul: <b>${state}</b></span>
      <span>Speak: <b>${data.speak_ready ? 'ready' : '—'}</b></span>
    </div>
    <div class="soul-checklist">${rows}</div>`;
}

export async function updateWorkstationCard() {
  const badgeEl = document.getElementById('mc-persona-badge');
  const bodyEl  = document.getElementById('mc-persona-body');
  if (!badgeEl || !bodyEl) return;

  const [persona, readiness] = await Promise.all([
    import('./persona.js').then(m => m.loadConfig()).catch(() => null),
    fetchReadiness().catch(() => null),
  ]);

  if (!persona && !readiness) {
    badgeEl.textContent = '—';
    badgeEl.className   = 'mc-badge off';
    bodyEl.innerHTML    = '<span style="color:var(--text3)">Could not load</span>';
    return;
  }

  const on = persona?.enabled;
  const soulOk = readiness?.soul_running;
  badgeEl.textContent = soulOk ? 'RUN' : (on ? 'ON' : 'OFF');
  badgeEl.className   = `mc-badge ${soulOk ? 'on' : (on ? 'warn' : 'off')}`;

  const p = persona?.profile ?? {};
  const files = readiness?.files ?? {};
  bodyEl.innerHTML = `
    <div class="mc-row"><span class="mc-key">Name</span>
      <span class="mc-val">${p.name ?? '—'}</span></div>
    <div class="mc-row"><span class="mc-key">Soul</span>
      <span class="mc-val">${readiness?.soul_state ?? '—'}</span></div>
    <div class="mc-row"><span class="mc-key">Built</span>
      <span class="mc-val">${files.built_profile_exists ? 'yes' : 'no'}</span></div>
    <div class="mc-row mc-actions">
      <button type="button" class="mc-action-btn" data-soul-action="settings">⚙ Setup</button>
      <button type="button" class="mc-action-btn" data-soul-action="reinit">↻ Init</button>
      <button type="button" class="mc-action-btn" data-soul-action="build">🔨 Build</button>
    </div>`;

  bodyEl.querySelectorAll('[data-soul-action]').forEach(btn => {
    btn.addEventListener('click', e => {
      e.stopPropagation();
      const action = btn.dataset.soulAction;
      if (action === 'settings') {
        import('../settings.js').then(m => m.open('persona'));
      } else if (action === 'reinit') {
        bodyEl.dispatchEvent(new CustomEvent('soul:reinit', { bubbles: true }));
      } else if (action === 'build') {
        bodyEl.dispatchEvent(new CustomEvent('soul:build', { bubbles: true }));
      }
    });
  });
}
