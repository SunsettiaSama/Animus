/**
 * modules/infra.js — Infrastructure services (vLLM, sandbox, service registry).
 */

import { http, PATHS } from '../api.js';

const _cb = { onToast: () => {} };
export function setCallbacks(cbs) { Object.assign(_cb, cbs); }

// ── vLLM ──────────────────────────────────────────────────────────────────────

export const vllm = {
  loadConfig:  () => http.get(PATHS.infra.vllm.config),
  saveConfig:  payload => http.post(PATHS.infra.vllm.save, payload).then(() => _cb.onToast('vLLM config saved')),
  start:       () => http.post(PATHS.infra.vllm.start, {}).then(d => { _cb.onToast('vLLM starting…'); return d; }),
  stop:        () => http.post(PATHS.infra.vllm.stop, {}).then(() => _cb.onToast('vLLM stopped')),
  status:      () => http.get(PATHS.infra.vllm.status),
  logs:        (n = 100) => http.get(`${PATHS.infra.vllm.logs}?n=${n}`),
};

// ── Sandbox ───────────────────────────────────────────────────────────────────

export const sandbox = {
  loadConfig:  () => http.get(PATHS.infra.sandbox.config),
  saveConfig:  payload => http.post(PATHS.infra.sandbox.save, payload).then(() => _cb.onToast('Sandbox config saved')),
};

// ── Bot service ───────────────────────────────────────────────────────────────

export const bot = {
  loadConfig:  () => http.get(PATHS.infra.bot.config),
  saveConfig:  payload => http.post(PATHS.infra.bot.save, payload).then(() => _cb.onToast('Bot config saved')),
  status:      () => http.get(PATHS.infra.bot.status),
  sessions:    () => http.get(PATHS.infra.bot.sessions),
  start:       () => http.post(PATHS.infra.bot.start, {}).then(d => { _cb.onToast('Bot service starting…'); return d; }),
  stop:        () => http.post(PATHS.infra.bot.stop,  {}).then(() => _cb.onToast('Bot service stopped')),
};

// ── Service registry ──────────────────────────────────────────────────────────

export const services = {
  statusAll: () => http.get(PATHS.infra.services.status),
  status:    name => http.get(PATHS.infra.services.one(name)),
  start:     name => http.post(PATHS.infra.services.start(name), {}).then(d => { _cb.onToast(`${name} starting…`); return d; }),
  stop:      name => http.post(PATHS.infra.services.stop(name), {}).then(() => _cb.onToast(`${name} stopped`)),
  logs:      (name, n = 100) => http.get(`${PATHS.infra.services.logs(name)}?n=${n}`),
};

// ── Workstation services row ──────────────────────────────────────────────────

const _SERVICE_META = {
  llm:     { icon: '🧠', label: 'LLM Core' },
  searxng: { icon: '🔍', label: 'Search' },
  sandbox: { icon: '🏖', label: 'Sandbox' },
  bot:     { icon: '💬', label: 'Channels' },
  tts:     { icon: '🔊', label: 'TTS' },
  stt:     { icon: '🎙', label: 'STT' },
};

// Services that show a Start/Stop button (only when not in 'unavailable' state)
const _STARTABLE = new Set(['llm', 'searxng', 'bot']);

export async function updateServicesRow() {
  const el = document.getElementById('ws-services');
  if (!el) return;

  const [data, barkCfg, ntfyCfg] = await Promise.all([
    services.statusAll().catch(() => null),
    fetch('/api/notify/bark/config').then(r => r.ok ? r.json() : null).catch(() => null),
    fetch('/api/notify/ntfy/config').then(r => r.ok ? r.json() : null).catch(() => null),
  ]);

  if (!data) {
    el.innerHTML = '<span style="font-size:13px;color:var(--text3)">Could not load services</span>';
    return;
  }

  const activeChannel = localStorage.getItem('react-active-channel') || 'bot';

  el.innerHTML = '';
  Object.entries(data).forEach(([name, svc]) => {
    const meta  = _SERVICE_META[name] ?? { icon: '⚙', label: name };
    const state = typeof svc === 'string' ? svc : (svc.state ?? 'unknown');
    const card  = document.createElement('div');
    card.className = 'service-card';

    if (name === 'bot') {
      _renderChannelsCard(card, svc, barkCfg, ntfyCfg, activeChannel);
    } else {
      // LLM card shows model·backend when available; others show state string
      const subtitle = (name === 'llm' && svc.model)
        ? `${svc.model} · ${svc.backend ?? ''}`
        : state;
      card.innerHTML = `
        <span class="status-dot ${_dotClass(state)}"></span>
        <span class="sc-icon">${meta.icon}</span>
        <div class="sc-info">
          <span class="sc-name">${meta.label}</span>
          <span class="sc-state">${subtitle}</span>
        </div>`;

      if (_STARTABLE.has(name) && state !== 'unavailable') {
        const isStarted = state === 'running' || state === 'connecting';
        const btn = document.createElement('button');
        btn.className = 'btn-secondary sc-btn';
        if (isStarted) {
          btn.textContent = 'Stop';
          btn.addEventListener('click', async () => {
            btn.disabled = true;
            btn.textContent = 'Stopping…';
            _cb.onToast(`Stopping ${name}…`);
            await services.stop(name).catch(err => _cb.onToast(`Stop failed: ${err.message}`));
            await updateServicesRow();
          });
        } else {
          btn.textContent = 'Start';
          btn.addEventListener('click', async () => {
            btn.disabled = true;
            btn.textContent = 'Starting…';
            _cb.onToast(`Starting ${name}…`);
            await services.start(name).catch(err => {
              _cb.onToast(`Start failed: ${err.message}`);
              updateServicesRow();
              return;
            });
            let attempts = 0;
            const _poll = setInterval(async () => {
              attempts++;
              await updateServicesRow().catch(() => {});
              if (attempts >= 10) clearInterval(_poll);
            }, 3000);
            await updateServicesRow();
          });
        }
        card.appendChild(btn);
      }
    }

    el.appendChild(card);
  });
}

function _renderChannelsCard(card, botSvc, barkCfg, ntfyCfg, activeChannel) {
  const botState   = typeof botSvc === 'string' ? botSvc : (botSvc?.state ?? 'unknown');
  const barkReady  = !!(barkCfg?.enabled && barkCfg?.device_key);
  const ntfyReady  = !!(ntfyCfg?.enabled && ntfyCfg?.topic);

  let dotCls, subtitle;
  if (activeChannel === 'bark') {
    dotCls   = barkReady ? 'running' : 'stopped';
    subtitle = barkReady ? '🍎 Bark · 已启用' : '🍎 Bark · 未配置';
  } else if (activeChannel === 'ntfy') {
    dotCls   = ntfyReady ? 'running' : 'stopped';
    subtitle = ntfyReady ? '📢 ntfy · 已启用' : '📢 ntfy · 未配置';
  } else {
    dotCls   = _dotClass(botState);
    subtitle = botState;
  }

  card.innerHTML = `
    <span class="status-dot ${dotCls}"></span>
    <span class="sc-icon">💬</span>
    <div class="sc-info">
      <span class="sc-name">Channels</span>
      <span class="sc-state">${subtitle}</span>
    </div>`;

  // Start/Stop only makes sense for the bot (QQ) channel
  if (activeChannel === 'bot' && botState !== 'unavailable') {
    const isStarted = botState === 'running' || botState === 'connecting';
    const btn = document.createElement('button');
    btn.className = 'btn-secondary sc-btn';
    if (isStarted) {
      btn.textContent = 'Stop';
      btn.addEventListener('click', async () => {
        btn.disabled = true;
        btn.textContent = 'Stopping…';
        _cb.onToast('Stopping Bot…');
        await services.stop('bot').catch(err => _cb.onToast(`Stop failed: ${err.message}`));
        await updateServicesRow();
      });
    } else {
      btn.textContent = 'Start';
      btn.addEventListener('click', async () => {
        btn.disabled = true;
        btn.textContent = 'Starting…';
        _cb.onToast('Starting Bot…');
        await services.start('bot').catch(err => {
          _cb.onToast(`Start failed: ${err.message}`);
          updateServicesRow();
          return;
        });
        let attempts = 0;
        const _poll = setInterval(async () => {
          attempts++;
          await updateServicesRow().catch(() => {});
          if (attempts >= 10) clearInterval(_poll);
        }, 3000);
        await updateServicesRow();
      });
    }
    card.appendChild(btn);
  }
}

function _dotClass(state) {
  if (state === 'running')  return 'running';
  if (state === 'loading' || state === 'starting' || state === 'connecting') return 'loading';
  return 'stopped';
}
