import { _v, _c, _si, _sc } from './_helpers.js';

async function _fetchConfig() {
  const res = await fetch('/api/scheduler/config');
  if (!res.ok) return null;
  return res.json();
}

async function _fetchStatus() {
  const res = await fetch('/api/scheduler/status');
  if (!res.ok) return null;
  return res.json();
}

let _engineButtonsWired = false;
let _heartbeatButtonsWired = false;

export async function load() {
  const [cfg, status] = await Promise.all([
    _fetchConfig().catch(() => null),
    _fetchStatus().catch(() => null),
  ]);

  if (cfg) {
    _si('s-sched-poll-interval',  cfg.poll_interval ?? 1.0);
    _sc('s-sched-proactive',      cfg.proactive_enabled ?? true);
    _si('s-sched-system-note',    cfg.scheduler_system_note ?? '');

    const defProfileEl = document.getElementById('s-sched-default-profile');
    if (defProfileEl) defProfileEl.value = cfg.default_profile ?? 'minimal';
    _si('s-sched-max-concurrent', cfg.max_concurrent ?? 3);
    _si('s-sched-retention',      cfg.task_retention_days ?? 30);

    const profiles = cfg.profiles ?? {};
    for (const [key, info] of Object.entries(profiles)) {
      const el = document.getElementById(`s-sched-steps-${key}`);
      if (el) el.value = info.max_steps ?? 10;
    }

    // ── Heartbeat fields ──
    const hb = cfg.heartbeat ?? {};
    _si('s-hb-interval',        hb.interval ?? 1800);
    const hbProfileEl = document.getElementById('s-hb-profile');
    if (hbProfileEl) hbProfileEl.value = hb.profile ?? 'with_memory';
    _si('s-hb-llm-aux-name',    hb.llm_aux_name ?? 'heartbeat');
    _sc('s-hb-light-context',   hb.light_context ?? true);
    _si('s-hb-max-escalations', hb.max_escalations_per_day ?? 10);
    _si('s-hb-active-start',    hb.active_hours_start ?? '07:00');
    _si('s-hb-active-end',      hb.active_hours_end ?? '22:00');
    _si('s-hb-active-tz',       hb.active_timezone ?? 'Asia/Shanghai');
    _si('s-hb-file-path',       hb.heartbeat_file ?? '.react/scheduler/HEARTBEAT.md');
    _si('s-hb-webhook-secret',  hb.webhook_secret ?? '');

    // ── Comm rate limits ──
    _si('s-comm-notify-rpm', cfg.comm_notify_rpm ?? 5);
    _si('s-comm-notify-rph', cfg.comm_notify_rph ?? 20);
    _si('s-comm-bot-rpm',    cfg.comm_bot_rpm ?? 3);
    _si('s-comm-bot-rph',    cfg.comm_bot_rph ?? 15);
  }

  if (status) {
    _updateEngineUI(status);
  }

  if (!_engineButtonsWired) {
    _wireEngineButtons();
    _engineButtonsWired = true;
  }

  if (!_heartbeatButtonsWired) {
    _wireHeartbeatButtons();
    _heartbeatButtonsWired = true;
  }

  // Update webhook URL display
  const urlEl = document.getElementById('s-hb-webhook-url');
  if (urlEl) {
    urlEl.textContent = `${location.origin}/api/scheduler/webhook/heartbeat`;
  }
}

function _updateEngineUI(status) {
  const dot   = document.getElementById('sched-engine-dot');
  const label = document.getElementById('sched-engine-label');
  const tz    = document.getElementById('sched-engine-tz');
  const pauseBtn  = document.getElementById('btn-sched-engine-pause');
  const resumeBtn = document.getElementById('btn-sched-engine-resume');

  if (!dot) return;

  dot.className = 'sched-engine-dot';
  if (!status.engine_ready) {
    dot.classList.add('stopped');
    if (label) label.textContent = '未初始化（请先启动 ReAct Agent）';
  } else if (status.is_paused) {
    dot.classList.add('paused');
    if (label) label.textContent = '已暂停';
  } else if (status.is_running) {
    dot.classList.add('running');
    if (label) label.textContent = '运行中';
  } else {
    dot.classList.add('stopped');
    if (label) label.textContent = '已停止';
  }
  if (tz) tz.textContent = `时区: ${status.server_timezone ?? '—'}`;
  if (pauseBtn)  pauseBtn.style.display  = (status.is_running && !status.is_paused) ? '' : 'none';
  if (resumeBtn) resumeBtn.style.display = status.is_paused ? '' : 'none';
}

function _wireEngineButtons() {
  const pauseBtn  = document.getElementById('btn-sched-engine-pause');
  const resumeBtn = document.getElementById('btn-sched-engine-resume');

  const _doControl = async (action) => {
    const res = await fetch('/api/scheduler/control', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action }),
    });
    if (res.ok) {
      const status = await fetch('/api/scheduler/status').then(r => r.json()).catch(() => null);
      if (status) _updateEngineUI(status);
    }
  };

  pauseBtn?.addEventListener('click',  () => _doControl('pause'));
  resumeBtn?.addEventListener('click', () => _doControl('resume'));
}

function _wireHeartbeatButtons() {
  // Heartbeat file load/save
  document.getElementById('btn-hb-file-reload')?.addEventListener('click', async () => {
    const res = await fetch('/api/scheduler/heartbeat-file').catch(() => null);
    if (res && res.ok) {
      const data = await res.json();
      _si('s-hb-file-content', data.content ?? '');
    }
  });

  document.getElementById('btn-hb-file-save')?.addEventListener('click', async () => {
    const content = _v('s-hb-file-content');
    await fetch('/api/scheduler/heartbeat-file', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ content }),
    });
  });

  // Tick log refresh
  document.getElementById('btn-hb-log-refresh')?.addEventListener('click', _refreshTickLog);
}

async function _refreshTickLog() {
  const res = await fetch('/api/scheduler/heartbeat-log?n=20').catch(() => null);
  if (!res || !res.ok) return;
  const data = await res.json();
  const tbody = document.getElementById('hb-log-tbody');
  if (!tbody) return;

  const entries = data.entries ?? [];
  if (entries.length === 0) {
    tbody.innerHTML = '<tr><td colspan="4" style="padding:8px;color:var(--text3)">暂无记录</td></tr>';
    return;
  }

  const _outcomeColor = (o) => {
    if (o === 'ok') return 'color:#10b981';
    if (o === 'escalate') return 'color:#f59e0b';
    if (o === 'skip') return 'color:var(--text3)';
    if (o === 'error') return 'color:#ef4444';
    return '';
  };

  tbody.innerHTML = entries.map(e => {
    const ts = e.ts ? new Date(e.ts).toLocaleString() : '—';
    return `<tr>
      <td style="padding:4px 8px;border-bottom:1px solid var(--border);font-size:11px">${ts}</td>
      <td style="padding:4px 8px;border-bottom:1px solid var(--border);${_outcomeColor(e.outcome)}">${e.outcome ?? '—'}</td>
      <td style="padding:4px 8px;border-bottom:1px solid var(--border);max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="${(e.reason ?? '').replace(/"/g, '&quot;')}">${e.reason ?? ''}</td>
      <td style="padding:4px 8px;border-bottom:1px solid var(--border)">${e.duration_ms ?? '—'}</td>
    </tr>`;
  }).join('');
}

export async function save() {
  const profileMaxSteps = {};
  for (const key of ['minimal', 'with_memory', 'full']) {
    const el = document.getElementById(`s-sched-steps-${key}`);
    if (el) profileMaxSteps[key] = parseInt(el.value, 10) || 10;
  }

  const heartbeat = {
    interval:                parseInt(_v('s-hb-interval'), 10) || 1800,
    profile:                 _v('s-hb-profile') || 'with_memory',
    llm_aux_name:            _v('s-hb-llm-aux-name') || 'heartbeat',
    light_context:           _c('s-hb-light-context'),
    max_escalations_per_day: parseInt(_v('s-hb-max-escalations'), 10) || 10,
    active_hours_start:      _v('s-hb-active-start') || '07:00',
    active_hours_end:        _v('s-hb-active-end') || '22:00',
    active_timezone:         _v('s-hb-active-tz') || 'Asia/Shanghai',
    heartbeat_file:          _v('s-hb-file-path') || '.react/scheduler/HEARTBEAT.md',
    webhook_secret:          _v('s-hb-webhook-secret') || '',
  };

  const body = {
    poll_interval:          parseFloat(_v('s-sched-poll-interval')) || 1.0,
    proactive_enabled:      _c('s-sched-proactive'),
    scheduler_system_note:  _v('s-sched-system-note'),
    default_profile:        _v('s-sched-default-profile') || 'minimal',
    max_concurrent:         parseInt(_v('s-sched-max-concurrent'), 10) || 3,
    task_retention_days:    parseInt(_v('s-sched-retention'), 10) ?? 30,
    profile_max_steps:      profileMaxSteps,
    heartbeat,
    comm_notify_rpm:        parseInt(_v('s-comm-notify-rpm'), 10) || 0,
    comm_notify_rph:        parseInt(_v('s-comm-notify-rph'), 10) || 0,
    comm_bot_rpm:           parseInt(_v('s-comm-bot-rpm'), 10) || 0,
    comm_bot_rph:           parseInt(_v('s-comm-bot-rph'), 10) || 0,
  };

  const res = await fetch('/api/scheduler/config', {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.error ?? 'Failed to save scheduler config');
  }
}
