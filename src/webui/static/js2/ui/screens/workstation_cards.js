/**
 * ui/screens/workstation_cards.js — Landing 工作站卡片与基础设施服务行。
 *
 * 数据读取经 transport（GET 类聚合展示）；失败时降级为占位文本。
 */

import { API } from '../../protocol/http_api.js';
import { http } from '../../transport/http.js';
import { bus, EVENTS } from '../../store/bus.js';
import * as sessionStore from '../../store/session_store.js';

const _stateLabel = (state) => ({
  connected: '✓ 已连接',
  running: '✓ 运行中',
  connecting: '… 连接中',
  stopped: '已停止',
  unavailable: '不可用',
}[state] || state);

// ── LLM ─────────────────────────────────────────────────────────────────────

export async function updateLlmCard() {
  const badgeEl = document.getElementById('mc-llm-badge');
  const bodyEl = document.getElementById('mc-llm-body');
  if (!badgeEl || !bodyEl) return;

  const data = await http.get(API.llm.status).catch(() => null);
  if (!data) {
    badgeEl.textContent = 'error';
    badgeEl.className = 'mc-badge off';
    bodyEl.innerHTML = '<span style="color:var(--text3)">Could not load status</span>';
    return;
  }

  if (data.initialized) {
    badgeEl.textContent = 'ON';
    badgeEl.className = 'mc-badge on';
    sessionStore.update({ llmModel: data.model ?? null });
  } else {
    badgeEl.textContent = '—';
    badgeEl.className = 'mc-badge off';
  }

  bodyEl.innerHTML = `
    <div class="mc-row"><span class="mc-key">Model</span>
      <span class="mc-val mc-truncate">${data.model ?? '—'}</span></div>
    <div class="mc-row"><span class="mc-key">Provider</span>
      <span class="mc-val">${data.backend ?? '—'}</span></div>
    <div class="mc-row"><span class="mc-key">Streaming</span>
      <span class="mc-val">${data.is_streaming ? '⏳ active' : '—'}</span></div>`;
}

// ── Soul / Speak 卡片 ────────────────────────────────────────────────────────

export async function updateSpeakCard() {
  const [readiness, speak] = await Promise.all([
    http.get(API.soul.readiness).catch(() => null),
    http.get(API.speak.status).catch(() => null),
  ]);
  sessionStore.update({
    soulReady: Boolean(readiness?.soul_running),
    speakReady: Boolean(speak?.ready || readiness?.speak_ready),
  });

  const badgeEl = document.getElementById('mc-react-badge');
  const bodyEl = document.getElementById('mc-react-body');
  if (!badgeEl || !bodyEl) return;

  if (!readiness && !speak) {
    badgeEl.textContent = 'error';
    badgeEl.className = 'mc-badge off';
    bodyEl.innerHTML = '<span style="color:var(--text3)">Could not load</span>';
    return;
  }
  const soulRunning = Boolean(readiness?.soul_running);
  const speakReady = Boolean(speak?.ready || readiness?.speak_ready);
  badgeEl.textContent = speakReady ? 'READY' : (soulRunning ? 'BOOT' : 'OFF');
  badgeEl.className = `mc-badge ${speakReady ? 'on' : (soulRunning ? 'warn' : 'off')}`;

  bodyEl.innerHTML = `
    <div class="mc-row"><span class="mc-key">Soul</span>
      <span class="mc-val">${readiness?.soul_state ?? speak?.soul_state ?? '—'}</span></div>
    <div class="mc-row"><span class="mc-key">Speak</span>
      <span class="mc-val">${speakReady ? 'ready' : (speak?.status ?? 'initializing')}</span></div>
    <div class="mc-row"><span class="mc-key">Pipeline</span>
      <span class="mc-val">request_driven</span></div>
    <div class="mc-row"><span class="mc-key">Dialogue</span>
      <span class="mc-val">Soul/Speak primary</span></div>`;
}

// ── Persona / Memory ────────────────────────────────────────────────────────

export async function updatePersonaCard() {
  const badgeEl = document.getElementById('mc-persona-badge');
  const bodyEl = document.getElementById('mc-persona-body');
  if (!badgeEl || !bodyEl) return;

  const [persona, readiness] = await Promise.all([
    http.get(API.persona.get).catch(() => null),
    http.get(API.soul.readiness).catch(() => null),
  ]);
  if (!persona && !readiness) {
    badgeEl.textContent = '—';
    badgeEl.className = 'mc-badge off';
    bodyEl.innerHTML = '<span style="color:var(--text3)">Could not load</span>';
    return;
  }

  const on = persona?.enabled;
  const soulOk = readiness?.soul_running;
  badgeEl.textContent = soulOk ? 'RUN' : (on ? 'ON' : 'OFF');
  badgeEl.className = `mc-badge ${soulOk ? 'on' : (on ? 'warn' : 'off')}`;
  if (on && persona?.profile?.name) {
    sessionStore.update({ personaName: persona.profile.name });
  }

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
      bus.emit('workstation:soul_action', { action: btn.dataset.soulAction });
    });
  });
}

export async function updateMemoryCard() {
  const bodyEl = document.getElementById('mc-memory-body');
  if (!bodyEl) return;

  const data = await http.get(API.memory.get).catch(() => null);
  if (!data) {
    bodyEl.innerHTML = '<span style="color:var(--text3)">Could not load</span>';
    return;
  }
  const row = (label, val) => `<div class="mc-row">
    <span class="mc-key">${label}</span>
    <span class="mc-val">${val}</span></div>`;
  const badge = on => `<span class="tier-badge ${on ? 'on' : 'off'}">${on ? '✓ on' : 'off'}</span>`;

  bodyEl.innerHTML = `
    ${row('Long-term', badge(data.long_term?.enabled))}
    ${row('Medium', badge(data.medium_term?.enabled))}`;
}

// ── Voice ───────────────────────────────────────────────────────────────────

export async function updateVoiceCard() {
  const bodyEl = document.getElementById('mc-voice-body');
  if (!bodyEl) return;

  const [tts, stt] = await Promise.allSettled([
    http.get(API.voice.tts.config),
    http.get(API.voice.stt.config),
  ]);
  const ttsData = tts.status === 'fulfilled' ? tts.value : null;
  const sttData = stt.status === 'fulfilled' ? stt.value : null;

  bodyEl.innerHTML = `
    <div class="mc-row"><span class="mc-key">TTS</span>
      <span class="mc-val">${ttsData?.provider ?? '—'}</span></div>
    <div class="mc-row"><span class="mc-key">STT</span>
      <span class="mc-val">${sttData?.provider ?? '—'}</span></div>
    <div class="mc-row"><span class="mc-key">Voice</span>
      <span class="mc-val mc-truncate">${ttsData?.voice ?? '—'}</span></div>`;
}

// ── Scheduler ───────────────────────────────────────────────────────────────

export async function updateSchedulerCard() {
  const bodyEl = document.getElementById('mc-scheduler-body');
  const badgeEl = document.getElementById('mc-sched-engine-badge');
  if (!bodyEl) return;

  const [tasksRes, statusRes] = await Promise.allSettled([
    http.get(API.scheduler.tasks).catch(() => ({ tasks: [], ready: false })),
    http.getRaw(API.scheduler.status).catch(() => null),
  ]);

  const { tasks, ready } = tasksRes.value ?? { tasks: [], ready: false };
  const status = statusRes.value ?? null;

  if (badgeEl) {
    badgeEl.style.display = '';
    if (status?.is_running && !status?.is_paused) {
      badgeEl.textContent = 'ON';
      badgeEl.className = 'mc-badge on';
    } else if (status?.is_paused) {
      badgeEl.textContent = 'PAUSED';
      badgeEl.className = 'mc-badge paused';
    } else {
      badgeEl.textContent = 'OFF';
      badgeEl.className = 'mc-badge off';
    }
  }

  if (!ready) {
    bodyEl.innerHTML = '<span style="color:var(--text3)">Not initialized</span>';
    return;
  }
  const pending = tasks.filter(t => t.status === 'pending').length;
  const running = tasks.filter(t => t.status === 'running').length;
  bodyEl.innerHTML = `
    <div class="mc-row"><span class="mc-key">Tasks</span><span class="mc-val">${tasks.length}</span></div>
    <div class="mc-row"><span class="mc-key">Pending</span>
      <span class="mc-val" style="color:#b45309">${pending}</span></div>
    <div class="mc-row"><span class="mc-key">Running</span>
      <span class="mc-val" style="color:#1d4ed8">${running}</span></div>`;
}

// ── Benchmark ───────────────────────────────────────────────────────────────

export async function updateBenchmarkCard() {
  const badgeEl = document.getElementById('mc-bench-badge');
  const bodyEl = document.getElementById('mc-bench-body');
  if (!bodyEl) return;

  const data = await http.get(API.benchmark.report).catch(() => null);
  const results = data?.results ?? [];

  if (!results.length) {
    if (badgeEl) {
      badgeEl.textContent = '—';
      badgeEl.className = 'mc-badge off';
    }
    bodyEl.innerHTML = '<span style="color:var(--text3)">No runs yet</span>';
    return;
  }

  const passed = results.filter(r => r.status === 'done').length;
  const pct = Math.round((passed / results.length) * 100);

  if (badgeEl) {
    badgeEl.textContent = `${pct}%`;
    badgeEl.className = pct === 100 ? 'mc-badge on' : 'mc-badge';
  }
  bodyEl.innerHTML = `
    <div class="mc-row"><span class="mc-key">Scenarios</span><span class="mc-val">${results.length}</span></div>
    <div class="mc-row"><span class="mc-key">Passed</span>
      <span class="mc-val" style="color:${pct === 100 ? '#16a34a' : 'var(--text)'}">${passed}/${results.length}</span></div>
    <div class="mc-row"><span class="mc-key">Pass Rate</span><span class="mc-val">${pct}%</span></div>`;
}

// ── Channels / Bot ──────────────────────────────────────────────────────────

export async function updateBotCard() {
  const badgeEl = document.getElementById('mc-bot-badge');
  const bodyEl = document.getElementById('mc-bot-body');
  if (!bodyEl) return null;

  const [cfgR, stR, barkR, ntfyR] = await Promise.allSettled([
    http.get(API.bot.config),
    http.getRaw(API.bot.status),
    http.getRaw(API.notify.barkConfig),
    http.getRaw(API.notify.ntfyConfig),
  ]);
  const c = cfgR.status === 'fulfilled' ? cfgR.value : null;
  const s = stR.status === 'fulfilled' ? stR.value : null;
  const bark = barkR.status === 'fulfilled' ? barkR.value : null;
  const ntfy = ntfyR.status === 'fulfilled' ? ntfyR.value : null;

  const state = String(s?.state ?? 'unavailable').trim();
  const svcState = String(s?.service_state ?? '').trim();
  const botOn = state === 'connected' || state === 'running' || svcState === 'running';
  const botLoading = !botOn && state === 'connecting';
  const barkOn = Boolean(bark?.enabled && bark?.device_key);
  const ntfyOn = Boolean(ntfy?.enabled && ntfy?.topic);
  const anyOn = botOn || barkOn || ntfyOn;
  const anyLoading = !anyOn && botLoading;

  if (badgeEl) {
    if (anyOn) { badgeEl.textContent = 'ON'; badgeEl.className = 'mc-badge on'; }
    else if (anyLoading) { badgeEl.textContent = '…'; badgeEl.className = 'mc-badge'; }
    else { badgeEl.textContent = 'OFF'; badgeEl.className = 'mc-badge off'; }
  }

  const rows = [];
  if (bark) {
    rows.push(`<div class="mc-row"><span class="mc-key">🍎 Bark</span>
      <span class="mc-val">${barkOn
        ? '<span style="color:#16a34a">✓ 已启用</span>'
        : '<span style="color:var(--text3)">未启用</span>'}</span></div>`);
  }
  if (ntfy) {
    rows.push(`<div class="mc-row"><span class="mc-key">📢 ntfy</span>
      <span class="mc-val">${ntfyOn
        ? '<span style="color:#16a34a">✓ 已启用</span>'
        : '<span style="color:var(--text3)">未启用</span>'}</span></div>`);
  }
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

// ── Infra services 行 ───────────────────────────────────────────────────────

const _SERVICE_META = {
  llm: { icon: '🧠', label: 'LLM Core' },
  soul: { icon: '🌟', label: 'Soul' },
  searxng: { icon: '🔍', label: 'SearXNG' },
  scheduler: { icon: '⏰', label: 'Scheduler' },
  bot: { icon: '💬', label: 'Channels' },
  tts: { icon: '🔊', label: 'TTS' },
  stt: { icon: '🎙', label: 'STT' },
};
const _STARTABLE = new Set(['llm', 'searxng', 'bot']);

function _dotClass(state) {
  if (state === 'running' || state === 'connected') return 'ok';
  if (state === 'connecting' || state === 'starting') return 'warn';
  if (state === 'unavailable') return 'off';
  return 'err';
}

export async function updateServicesRow() {
  const el = document.getElementById('ws-services');
  if (!el) return;

  const data = await http.get(API.services.status).catch(() => null);
  if (!data) {
    el.innerHTML = '<span style="font-size:13px;color:var(--text3)">Could not load services</span>';
    return;
  }

  el.innerHTML = '';
  Object.entries(data).forEach(([name, svc]) => {
    const meta = _SERVICE_META[name] ?? { icon: '⚙', label: name };
    const state = typeof svc === 'string' ? svc : (svc.state ?? 'unknown');
    const subtitle = (name === 'llm' && svc.model)
      ? `${svc.model} · ${svc.backend ?? ''}`
      : state;
    const card = document.createElement('div');
    card.className = 'service-card';
    card.innerHTML = `
      <span class="status-dot ${_dotClass(state)}"></span>
      <span class="sc-icon">${meta.icon}</span>
      <div class="sc-info">
        <span class="sc-name">${meta.label}</span>
        <span class="sc-state">${subtitle}</span>
      </div>`;

    if (_STARTABLE.has(name) && state !== 'unavailable') {
      const btn = document.createElement('button');
      btn.className = 'btn-secondary sc-btn';
      const toggle = state === 'running' ? 'stop' : 'start';
      btn.textContent = state === 'running' ? 'Stop' : 'Start';
      btn.addEventListener('click', async () => {
        btn.disabled = true;
        btn.textContent = toggle === 'stop' ? 'Stopping…' : 'Starting…';
        try {
          await (toggle === 'stop'
            ? http.post(API.services.stop(name))
            : http.post(API.services.start(name)));
        } catch (err) {
          bus.emit(EVENTS.toastShow, `${toggle} failed: ${err.message}`);
        }
        await updateServicesRow();
        if (toggle === 'start') {
          let attempts = 0;
          const pollTimer = setInterval(async () => {
            attempts += 1;
            await updateServicesRow().catch(() => {});
            if (attempts >= 10) clearInterval(pollTimer);
          }, 3000);
        }
      });
      card.appendChild(btn);
    }
    el.appendChild(card);
  });
}

/** 全量刷新所有卡片。 */
export async function refreshAll() {
  await Promise.allSettled([
    updateLlmCard(),
    updateSpeakCard(),
    updateMemoryCard(),
    updatePersonaCard(),
    updateVoiceCard(),
    updateSchedulerCard(),
    updateBenchmarkCard(),
    updateBotCard(),
    updateServicesRow(),
  ]);
}
