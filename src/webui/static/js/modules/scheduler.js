/**
 * modules/scheduler.js — Scheduled task CRUD + 24h horizontal timeline axis.
 */

import { http, PATHS } from '../api.js';

const _cb = { onToast: () => {} };
export function setCallbacks(cbs) { Object.assign(_cb, cbs); }

// ── Screen init ───────────────────────────────────────────────────────────────

let _axisRefreshTimer = null;
let _needleTimer      = null;

// Calendar state
let _calYear  = new Date().getFullYear();
let _calMonth = new Date().getMonth();   // 0-based
let _calFilter = null;                   // 'yyyy-mm-dd' or null

export async function init() {
  _setTlDate();
  _wireFormTriggerTabs();
  _wireProactiveToggle();
  _wireCalendarNav();
  _wireEngineStatClick();
  _wireHeartbeatPanel();

  await Promise.allSettled([
    renderTaskTable(),
    renderTimelineAxis(),
    renderEngineStatus(),
    renderHeartbeatPanel(),
  ]);

  // Refresh axis data every 30 s; update needle every second; engine status every 10 s
  if (_axisRefreshTimer) clearInterval(_axisRefreshTimer);
  if (_needleTimer)      clearInterval(_needleTimer);
  _axisRefreshTimer = setInterval(() => {
    renderTimelineAxis();
    renderEngineStatus();
    renderHeartbeatPanel();
    _renderSessionJournal();
  }, 30_000);
  _needleTimer = setInterval(_updateNeedle, 1_000);

  _wireSessionJournal();
}

function _setTlDate() {
  const el = document.getElementById('sched-tl-date');
  if (el) el.textContent = new Date().toLocaleDateString('zh-CN', { month: 'long', day: 'numeric' });
}

// ── API helpers ───────────────────────────────────────────────────────────────

export async function listTasks() {
  const { tasks, ready } = await http.get(PATHS.scheduler.tasks);
  return { tasks, ready };
}

export async function createTask(payload) {
  const task = await http.post(PATHS.scheduler.tasks, payload);
  _cb.onToast(`Task "${task.name}" created`);
  return task;
}

export async function cancelTask(id) {
  await http.del(PATHS.scheduler.task(id));
  _cb.onToast('Task cancelled');
}

export async function patchTask(id, action) {
  await http.patch(PATHS.scheduler.task(id), { action });
  _cb.onToast(`Task ${action}d`);
}

// ── Workstation card ───────────────────────────────────────────────────────────

export async function updateWorkstationCard() {
  const bodyEl  = document.getElementById('mc-scheduler-body');
  const badgeEl = document.getElementById('mc-sched-engine-badge');
  if (!bodyEl) return;

  const [tasksRes, statusRes] = await Promise.allSettled([
    listTasks().catch(() => ({ tasks: [], ready: false })),
    fetch('/api/scheduler/status').then(r => r.ok ? r.json() : null).catch(() => null),
  ]);

  const { tasks, ready } = tasksRes.value ?? { tasks: [], ready: false };
  const status = statusRes.value ?? null;

  // Engine badge in card header
  if (badgeEl) {
    badgeEl.style.display = '';
    if (status?.is_running && !status?.is_paused) {
      badgeEl.textContent  = 'ON';
      badgeEl.className    = 'mc-badge on';
    } else if (status?.is_paused) {
      badgeEl.textContent  = 'PAUSED';
      badgeEl.className    = 'mc-badge paused';
    } else {
      badgeEl.textContent  = 'OFF';
      badgeEl.className    = 'mc-badge off';
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

// ── Task list ─────────────────────────────────────────────────────────────────

const _STATUS_ICON = {
  pending:   '⏳',
  paused:    '⏸',
  running:   '⚡',
  done:      '✓',
  failed:    '✗',
  cancelled: '—',
};

export async function renderTaskTable() {
  const listEl = document.getElementById('sched-task-list');
  if (!listEl) return;

  const { tasks, ready } = await listTasks().catch(() => ({ tasks: [], ready: false }));

  _setStat('sstat-total',   ready ? tasks.length : 0);
  _setStat('sstat-pending', tasks.filter(t => t.status === 'pending').length);
  _setStat('sstat-running', tasks.filter(t => t.status === 'running').length);
  _setStat('sstat-done',    tasks.filter(t => t.status === 'done').length);

  const badge = document.getElementById('sched-status-badge');
  if (badge) {
    const running = tasks.filter(t => t.status === 'running').length;
    badge.textContent = running ? 'RUNNING' : ready ? 'READY' : '—';
    badge.className   = running ? 'plan-badge running' : 'plan-badge';
  }

  if (!ready) {
    listEl.innerHTML = `
      <div class="sched-empty-state">
        <div class="sched-empty-icon">🔌</div>
        <div class="sched-empty-text">ReAct not initialized</div>
        <div class="sched-empty-hint">Initialize the agent from the settings panel first</div>
      </div>`;
    return;
  }

  // Apply date filter from mini calendar
  let filtered = tasks;
  if (_calFilter) {
    filtered = tasks.filter(t => {
      const ts = t.next_run_at || t.created_at;
      return ts && ts.slice(0, 10) === _calFilter;
    });
  }

  // Sort: active/upcoming first (pending, paused, running) → done → cancelled/failed
  // Within each group: ascending by next_run_at
  const _RANK = { running: 0, pending: 1, paused: 2, done: 3, failed: 4, cancelled: 5 };
  filtered.sort((a, b) => {
    const ra = _RANK[a.status] ?? 9;
    const rb = _RANK[b.status] ?? 9;
    if (ra !== rb) return ra - rb;
    const ta = a.next_run_at ? new Date(a.next_run_at).getTime() : Infinity;
    const tb = b.next_run_at ? new Date(b.next_run_at).getTime() : Infinity;
    return ta - tb;
  });

  if (!filtered.length) {
    listEl.innerHTML = `
      <div class="sched-empty-state">
        <div class="sched-empty-icon">🗓</div>
        <div class="sched-empty-text">${_calFilter ? `${_calFilter} 无任务` : 'No scheduled tasks'}</div>
        <div class="sched-empty-hint">${_calFilter ? '点击日历其他日期或再次点击取消筛选' : 'Click <strong>＋ New Task</strong> to schedule your first agent run'}</div>
      </div>`;
    return;
  }

  listEl.innerHTML = '';
  filtered.forEach(t => {
    const card = document.createElement('div');
    card.className = 'sched-task-card';

    const nextRun    = t.next_run_at ? _fmtTime(t.next_run_at) : '—';
    const trigType   = t.trigger_type ?? t.trigger?.type ?? 'once';
    const trigClass  = `trigger-${trigType}`;
    const icon       = _STATUS_ICON[t.status] ?? '●';
    const retryInfo  = t.max_retries > 0
      ? `<span class="sched-tag" title="retries">${t.retry_count}/${t.max_retries} retry</span>` : '';

    card.innerHTML = `
      <div class="sched-task-icon ${_esc(t.status)}">${icon}</div>
      <div class="sched-task-main">
        <div class="sched-task-name">${_esc(t.name)}</div>
        <div class="sched-task-meta">
          ${t.config_profile ? `<span class="sched-tag">${_esc(t.config_profile)}</span>` : ''}
          ${trigType ? `<span class="sched-tag ${_esc(trigClass)}">${_esc(trigType)}</span>` : ''}
          ${t.delivery && t.delivery !== 'push' ? `<span class="sched-tag">${_esc(t.delivery)}</span>` : ''}
          ${retryInfo}
        </div>
      </div>
      <div class="sched-task-right">
        <span class="task-badge ${_esc(t.status)}">${_esc(t.status)}</span>
        <span class="sched-task-next">${nextRun !== '—' ? `Next: ${nextRun}` : '—'}</span>
      </div>
      <div class="sched-task-actions">
        ${t.status === 'pending'  ? `<button class="sched-task-btn" data-action="pause"  data-id="${_esc(t.id)}">Pause</button>` : ''}
        ${t.status === 'paused'   ? `<button class="sched-task-btn" data-action="resume" data-id="${_esc(t.id)}">Resume</button>` : ''}
        <button class="sched-task-cancel" data-id="${_esc(t.id)}" title="Cancel task">Cancel</button>
      </div>`;

    card.querySelectorAll('.sched-task-btn').forEach(btn => {
      btn.addEventListener('click', async (e) => {
        e.stopPropagation();
        await patchTask(btn.dataset.id, btn.dataset.action);
        renderTaskTable();
        renderTimelineAxis();
      });
    });

    card.querySelector('.sched-task-cancel').addEventListener('click', async (e) => {
      e.stopPropagation();
      await cancelTask(t.id);
      renderTaskTable();
      renderTimelineAxis();
    });

    listEl.appendChild(card);
  });
}

function _setStat(id, val) {
  const el = document.getElementById(id);
  if (el) el.textContent = val;
}

function _fmtTime(iso) {
  const d = new Date(iso);
  const now = new Date();
  const diff = d - now;
  if (Math.abs(diff) < 60_000) return 'now';
  if (diff > 0 && diff < 86_400_000) {
    return `Today ${d.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' })}`;
  }
  return d.toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
}

// ── 24h Horizontal Timeline Axis ──────────────────────────────────────────────

let _axisData = { events: [], tasks: [] };

export async function renderTimelineAxis() {
  const canvas = document.getElementById('tl-axis-canvas');
  if (!canvas) return;

  // Fetch merged data from /api/scheduler/axis
  const data = await http.get(PATHS.scheduler.axis).catch(() => ({ events: [], tasks: [] }));
  _axisData = data;

  _buildAxis(canvas, data.events ?? [], data.tasks ?? []);
  renderMiniCalendar();
}

function _buildAxis(canvas, events, tasks) {
  // Clear previous dots (keep the axis line)
  canvas.querySelectorAll('.tl-dot, .tl-needle, .tl-hour-label').forEach(el => el.remove());

  const W = canvas.clientWidth || canvas.offsetWidth || 600;

  // Hour labels: 00, 03, 06, 09, 12, 15, 18, 21, 24
  [0, 3, 6, 9, 12, 15, 18, 21, 24].forEach(h => {
    const lbl = document.createElement('div');
    lbl.className = 'tl-hour-label';
    lbl.textContent = h === 24 ? '24' : String(h).padStart(2, '0');
    lbl.style.left = `${(h / 24) * 100}%`;
    canvas.appendChild(lbl);
  });

  const today = new Date();
  const midnightMs = new Date(today.getFullYear(), today.getMonth(), today.getDate()).getTime();

  // Past events
  events.forEach(ev => {
    const ms = new Date(ev.ts).getTime();
    const frac = (ms - midnightMs) / 86_400_000;
    if (frac < 0 || frac > 1) return;
    const dot = _makeDot(`tl-past ${ev.type ?? ''}`, frac, ev, false);
    canvas.appendChild(dot);
  });

  // Future / scheduled tasks
  tasks.forEach(t => {
    if (!t.next_run_at || ['done', 'cancelled', 'failed'].includes(t.status)) return;
    const ms = new Date(t.next_run_at).getTime();
    const frac = (ms - midnightMs) / 86_400_000;
    if (frac < 0 || frac > 1) return;
    const dot = _makeDot(`tl-future ${t.status ?? 'pending'}`, frac, t, true);
    canvas.appendChild(dot);
  });

  // Current time needle
  _appendNeedle(canvas, midnightMs);
}

function _makeDot(classes, frac, data, isTask) {
  const dot = document.createElement('div');
  dot.className = `tl-dot ${classes}`;
  dot.style.left = `${frac * 100}%`;
  dot.title = isTask
    ? `[${data.status}] ${data.name}\nNext: ${_fmtTime(data.next_run_at)}`
    : `[${data.type}] ${new Date(data.ts).toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' })}`;
  dot.addEventListener('click', (e) => {
    e.stopPropagation();
    _showDetail(data, isTask);
  });
  return dot;
}

function _appendNeedle(canvas, midnightMs) {
  const now = Date.now();
  const frac = (now - midnightMs) / 86_400_000;
  if (frac < 0 || frac > 1) return;

  const needle = document.createElement('div');
  needle.className = 'tl-needle';
  needle.id = 'tl-needle';
  needle.style.left = `${frac * 100}%`;

  const timeEl = document.createElement('div');
  timeEl.className = 'tl-needle-time';
  timeEl.id = 'tl-needle-time';
  timeEl.textContent = new Date().toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' });
  needle.appendChild(timeEl);

  canvas.appendChild(needle);
}

function _updateNeedle() {
  const needle = document.getElementById('tl-needle');
  const timeEl = document.getElementById('tl-needle-time');
  if (!needle) return;

  const today = new Date();
  const midnightMs = new Date(today.getFullYear(), today.getMonth(), today.getDate()).getTime();
  const frac = (Date.now() - midnightMs) / 86_400_000;
  needle.style.left = `${frac * 100}%`;
  if (timeEl) {
    timeEl.textContent = today.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' });
  }
}

// ── Detail card ───────────────────────────────────────────────────────────────

function _showDetail(data, isTask) {
  const card = document.getElementById('tl-detail-card');
  if (!card) return;

  card.style.display = 'block';

  if (isTask) {
    const trigType = data.trigger_type ?? data.trigger?.type ?? '';
    const cronInfo = trigType === 'cron' ? ` [${data.trigger?.cron_expr ?? ''}]` : '';
    card.innerHTML = `
      <button class="tl-detail-close" id="tl-detail-close">✕</button>
      <div class="tl-detail-type">Scheduled Task · ${_esc(trigType)}${_esc(cronInfo)}</div>
      <div class="tl-detail-name">${_esc(data.name)}</div>
      <div class="tl-detail-body">
        <strong>Next run:</strong> ${_esc(_fmtTime(data.next_run_at))}<br>
        <strong>Status:</strong> ${_esc(data.status)}&nbsp;&nbsp;
        <strong>Delivery:</strong> ${_esc(data.delivery ?? 'push')}<br>
        ${data.max_retries > 0 ? `<strong>Retries:</strong> ${data.retry_count}/${data.max_retries}<br>` : ''}
        ${data.on_complete ? `<strong>Chain:</strong> ${_esc(data.on_complete.slice(0, 80))}${data.on_complete.length > 80 ? '…' : ''}<br>` : ''}
        <strong>Instruction:</strong> ${_esc((data.instruction ?? '').slice(0, 120))}${(data.instruction ?? '').length > 120 ? '…' : ''}
      </div>
      <div class="tl-detail-actions">
        ${data.status === 'pending' ? `<button class="btn-secondary" data-task-action="pause"  data-id="${_esc(data.id)}">Pause</button>` : ''}
        ${data.status === 'paused'  ? `<button class="btn-primary"   data-task-action="resume" data-id="${_esc(data.id)}">Resume</button>` : ''}
        <button class="btn-secondary" style="color:#ef4444;border-color:#ef4444" data-task-action="cancel" data-id="${_esc(data.id)}">Cancel</button>
      </div>`;
  } else {
    const payload = data.payload ?? {};
    const name    = payload.task_name ?? payload.name ?? payload.summary ?? data.type;
    const detail  = payload.answer ?? payload.result ?? payload.args ?? '';
    const time    = new Date(data.ts).toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit', second: '2-digit' });
    card.innerHTML = `
      <button class="tl-detail-close" id="tl-detail-close">✕</button>
      <div class="tl-detail-type">${_esc(data.type ?? 'event')} · ${time}</div>
      <div class="tl-detail-name">${_esc(name)}</div>
      <div class="tl-detail-body">${_esc(typeof detail === 'string' ? detail.slice(0, 300) : JSON.stringify(detail).slice(0, 300))}${String(detail).length > 300 ? '…' : ''}</div>`;
  }

  // Wire close button
  card.querySelector('#tl-detail-close')?.addEventListener('click', () => {
    card.style.display = 'none';
  });

  // Wire action buttons
  card.querySelectorAll('[data-task-action]').forEach(btn => {
    btn.addEventListener('click', async () => {
      const action = btn.dataset.taskAction;
      const id     = btn.dataset.id;
      if (action === 'cancel') {
        await cancelTask(id);
      } else {
        await patchTask(id, action);
      }
      card.style.display = 'none';
      renderTaskTable();
      renderTimelineAxis();
    });
  });
}

// ── Form wiring ───────────────────────────────────────────────────────────────

function _wireFormTriggerTabs() {
  document.querySelectorAll('input[name="sched-trigger-radio"]').forEach(radio => {
    radio.addEventListener('change', () => {
      const val = radio.value;
      document.getElementById('sched-once-fields').style.display     = val === 'once'     ? '' : 'none';
      document.getElementById('sched-interval-fields').style.display = val === 'interval' ? '' : 'none';
      document.getElementById('sched-cron-fields').style.display     = val === 'cron'     ? '' : 'none';
    });
  });
}

function _wireProactiveToggle() {
  const cb = document.getElementById('tl-proactive-cb');
  if (!cb) return;

  // Load current state
  http.get(PATHS.scheduler.proactive).then(res => {
    cb.checked = res.proactive_enabled ?? true;
  }).catch(() => {});

  cb.addEventListener('change', () => {
    http.patch(PATHS.scheduler.proactive, { proactive_enabled: cb.checked }).catch(() => {});
  });
}

function _wireCalendarNav() {
  document.getElementById('sched-cal-prev')?.addEventListener('click', () => {
    _calMonth--;
    if (_calMonth < 0) { _calMonth = 11; _calYear--; }
    _calFilter = null;
    renderMiniCalendar();
  });
  document.getElementById('sched-cal-next')?.addEventListener('click', () => {
    _calMonth++;
    if (_calMonth > 11) { _calMonth = 0; _calYear++; }
    _calFilter = null;
    renderMiniCalendar();
  });
}

function _wireEngineStatClick() {
  document.getElementById('sstat-engine')?.addEventListener('click', () => {
    import('../settings/modal.js').then(m => m.open('scheduler')).catch(() => {});
  });
}

// ── Engine status ──────────────────────────────────────────────────────────────

export async function renderEngineStatus() {
  const status = await fetch('/api/scheduler/status').then(r => r.json()).catch(() => null);
  if (!status) return;

  // Stats bar dot
  const dot = document.getElementById('sstat-engine-dot');
  const lbl = document.getElementById('sstat-engine-lbl');
  if (dot && lbl) {
    dot.className = 'sched-engine-dot-sm';
    if (!status.engine_ready) {
      dot.classList.add('stopped');
      lbl.textContent = 'ENGINE ○';
    } else if (status.is_paused) {
      dot.classList.add('paused');
      lbl.textContent = 'ENGINE ⏸';
    } else if (status.is_running) {
      dot.classList.add('running');
      lbl.textContent = 'ENGINE ●';
    } else {
      dot.classList.add('stopped');
      lbl.textContent = 'ENGINE ○';
    }
  }

  // Settings panel status (only if modal is open)
  const settingsDot   = document.getElementById('sched-engine-dot');
  const settingsLabel = document.getElementById('sched-engine-label');
  const settingsTz    = document.getElementById('sched-engine-tz');
  const pauseBtn      = document.getElementById('btn-sched-engine-pause');
  const resumeBtn     = document.getElementById('btn-sched-engine-resume');
  if (settingsDot) {
    settingsDot.className = 'sched-engine-dot';
    if (!status.engine_ready) {
      settingsDot.classList.add('stopped');
      if (settingsLabel) settingsLabel.textContent = '未初始化';
    } else if (status.is_paused) {
      settingsDot.classList.add('paused');
      if (settingsLabel) settingsLabel.textContent = '已暂停';
    } else if (status.is_running) {
      settingsDot.classList.add('running');
      if (settingsLabel) settingsLabel.textContent = '运行中';
    } else {
      settingsDot.classList.add('stopped');
      if (settingsLabel) settingsLabel.textContent = '已停止';
    }
    if (settingsTz) settingsTz.textContent = `时区: ${status.server_timezone ?? '—'}`;
    if (pauseBtn && resumeBtn) {
      pauseBtn.style.display  = (status.is_running && !status.is_paused) ? '' : 'none';
      resumeBtn.style.display = status.is_paused ? '' : 'none';
    }
  }
}

// ── Mini Calendar ──────────────────────────────────────────────────────────────

export async function renderMiniCalendar() {
  const grid    = document.getElementById('sched-cal-grid');
  const titleEl = document.getElementById('sched-cal-title');
  if (!grid) return;

  const today = new Date();
  if (titleEl) {
    titleEl.textContent = new Date(_calYear, _calMonth, 1)
      .toLocaleDateString('zh-CN', { year: 'numeric', month: 'long' });
  }

  // Fetch axis data to get task dates
  const data = await http.get(PATHS.scheduler.axis).catch(() => ({ events: [], tasks: [] }));
  const tasks  = data.tasks  ?? [];
  const events = data.events ?? [];

  // Build date → status map
  const dateMap = {};
  tasks.forEach(t => {
    if (!t.next_run_at) return;
    const d = t.next_run_at.slice(0, 10);
    if (!dateMap[d]) dateMap[d] = new Set();
    dateMap[d].add(t.status);
  });
  events.forEach(ev => {
    if (!ev.ts) return;
    const d = ev.ts.slice(0, 10);
    if (!dateMap[d]) dateMap[d] = new Set();
    dateMap[d].add('event');
  });

  // Build calendar grid
  const firstDay  = new Date(_calYear, _calMonth, 1).getDay();   // 0=Sun
  const daysInMonth = new Date(_calYear, _calMonth + 1, 0).getDate();
  const todayStr  = today.toISOString().slice(0, 10);

  grid.innerHTML = '';

  // Leading empty cells
  for (let i = 0; i < firstDay; i++) {
    const empty = document.createElement('div');
    grid.appendChild(empty);
  }

  for (let day = 1; day <= daysInMonth; day++) {
    const dateStr = `${_calYear}-${String(_calMonth + 1).padStart(2, '0')}-${String(day).padStart(2, '0')}`;
    const cell = document.createElement('div');
    cell.className = 'sched-cal-day';
    if (dateStr === todayStr)   cell.classList.add('today');
    if (dateStr === _calFilter) cell.classList.add('selected');
    if (_calYear !== today.getFullYear() || _calMonth !== today.getMonth()) {
      // nothing (all same month)
    }

    const numEl = document.createElement('span');
    numEl.textContent = day;
    cell.appendChild(numEl);

    // Dots for events
    const statuses = dateMap[dateStr];
    if (statuses) {
      const dotsEl = document.createElement('div');
      dotsEl.className = 'sched-cal-day-dots';
      const dotClasses = _calDotClasses(statuses);
      dotClasses.forEach(cls => {
        const d = document.createElement('span');
        d.className = `sched-cal-dot ${cls}`;
        dotsEl.appendChild(d);
      });
      cell.appendChild(dotsEl);
    }

    cell.addEventListener('click', () => {
      if (_calFilter === dateStr) {
        _calFilter = null;
      } else {
        _calFilter = dateStr;
      }
      // Sync Work Journal date picker to the selected calendar date
      const dateInput = document.getElementById('sched-session-date');
      if (dateInput) dateInput.value = _calFilter ?? new Date().toISOString().slice(0, 10);
      renderMiniCalendar();
      renderTaskTable();
      _renderSessionJournal();
    });

    grid.appendChild(cell);
  }
}

function _calDotClasses(statuses) {
  const s = statuses;
  const dots = [];
  if (s.has('running'))  dots.push('running');
  else if (s.has('pending') || s.has('paused')) dots.push('pending');
  if (s.has('done'))     dots.push('done');
  if (s.has('event'))    dots.push('done');
  return dots.slice(0, 2);
}

// ── Heartbeat Panel ───────────────────────────────────────────────────────────

function _wireHeartbeatPanel() {
  document.getElementById('btn-sched-hb-refresh')?.addEventListener('click', () => renderHeartbeatPanel());

  document.getElementById('btn-sched-hb-load')?.addEventListener('click', () => _loadHbFile());

  document.getElementById('btn-sched-hb-save')?.addEventListener('click', () => _saveHbFile());

  document.getElementById('btn-hb-trigger-now')?.addEventListener('click', async () => {
    const btn = document.getElementById('btn-hb-trigger-now');
    if (btn) { btn.disabled = true; btn.textContent = '…'; }
    await fetch(PATHS.scheduler.webhookTrigger, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: '{}',
    }).catch(() => {});
    if (btn) { btn.disabled = false; btn.textContent = '▶ Now'; }
    setTimeout(() => renderHeartbeatPanel(), 1500);
  });

  _loadHbFile();
}

async function _loadHbFile() {
  const ta  = document.getElementById('sched-hb-content');
  const msg = document.getElementById('sched-hb-file-msg');
  if (!ta) return;
  const res = await fetch(PATHS.scheduler.heartbeatFile)
    .then(r => r.ok ? r.json() : null).catch(() => null);
  if (res?.content !== undefined) {
    ta.value = res.content;
    if (msg) msg.textContent = '';
  } else {
    if (msg) msg.textContent = '未能加载文件（引擎尚未就绪？）';
  }
}

async function _saveHbFile() {
  const ta  = document.getElementById('sched-hb-content');
  const msg = document.getElementById('sched-hb-file-msg');
  if (!ta) return;
  const res = await fetch(PATHS.scheduler.heartbeatFile, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ content: ta.value }),
  }).then(r => r.json()).catch(() => null);
  if (msg) {
    msg.textContent = res?.ok ? '已保存 ✓' : '保存失败';
    if (res?.ok) setTimeout(() => { msg.textContent = ''; }, 2000);
  }
}

export async function renderHeartbeatPanel() {
  const [cfgRes, logRes] = await Promise.allSettled([
    fetch(PATHS.scheduler.config).then(r => r.ok ? r.json() : null).catch(() => null),
    fetch(PATHS.scheduler.heartbeatLog(8)).then(r => r.ok ? r.json() : null).catch(() => null),
  ]);

  const cfg = cfgRes.status === 'fulfilled' ? cfgRes.value : null;
  const log = logRes.status === 'fulfilled' ? logRes.value : null;
  const hb  = cfg?.heartbeat ?? {};

  // Status dot + text from most recent tick
  // Backend returns { entries: [...], ready: bool }
  const ticks  = log?.entries ?? [];
  const latest = ticks[0] ?? null;
  const dot        = document.getElementById('sched-hb-dot');
  const statusText = document.getElementById('sched-hb-status-text');

  if (dot && statusText) {
    if (!cfg) {
      dot.className = 'sched-hb-dot idle';
      statusText.textContent = '调度器未就绪';
    } else {
      const outcome = latest?.outcome ?? 'idle';
      dot.className = `sched-hb-dot ${_esc(outcome)}`;
      if (latest) {
        const ago   = _relTime(latest.ts);
        const durMs = latest.duration_ms ?? 0;
        statusText.textContent = `上次: ${outcome}  ·  ${ago}${durMs ? `  ·  ${durMs}ms` : ''}`;
      } else {
        dot.className = 'sched-hb-dot idle';
        statusText.textContent = '尚无心跳记录';
      }
    }
  }

  // Meta line: interval + active hours
  const metaEl = document.getElementById('sched-hb-meta');
  if (metaEl && Object.keys(hb).length) {
    const mins  = Math.floor((hb.interval ?? 1800) / 60);
    const start = hb.active_hours_start ?? '07:00';
    const end   = hb.active_hours_end   ?? '22:00';
    const tz    = hb.active_timezone    ?? '';
    metaEl.innerHTML =
      `间隔 <b>${mins}m</b> &nbsp;·&nbsp; 活跃时段 <b>${_esc(start)}–${_esc(end)}</b>` +
      (tz ? ` <span style="color:var(--text3)">${_esc(tz)}</span>` : '');
  }

  // Tick log
  const logEl = document.getElementById('sched-hb-log');
  if (logEl) {
    if (!ticks.length) {
      logEl.innerHTML = '<div style="padding:4px 2px;font-size:12px;color:var(--text3)">暂无记录</div>';
    } else {
      logEl.innerHTML = ticks.map(t => {
        const outcome = t.outcome ?? '?';
        const reason  = (t.reason ?? '').slice(0, 40);
        const ts      = _relTime(t.ts);
        return `
          <div class="sched-hb-tick">
            <span class="sched-hb-tick-badge ${_esc(outcome)}">${_esc(outcome)}</span>
            <span class="sched-hb-tick-reason" title="${_esc(t.reason ?? '')}">${_esc(reason)}</span>
            <span class="sched-hb-tick-time">${_esc(ts)}</span>
          </div>`;
      }).join('');
    }
  }
}

function _relTime(isoStr) {
  if (!isoStr) return '—';
  const diff = Date.now() - new Date(isoStr).getTime();
  if (isNaN(diff)) return isoStr;
  const s = Math.floor(diff / 1000);
  if (s < 60)  return `${s}s ago`;
  const m = Math.floor(s / 60);
  if (m < 60)  return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24)  return `${h}h ago`;
  return `${Math.floor(h / 24)}d ago`;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function _esc(s) {
  return String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

// Re-export renderTimeline alias for backward compatibility
export const renderTimeline = renderTimelineAxis;

// ── Journal Session Window ────────────────────────────────────────────────────

let _sessionJournalWired = false;

function _wireSessionJournal() {
  if (_sessionJournalWired) {
    // Already wired — just refresh on re-entry
    _renderSessionJournal();
    return;
  }
  _sessionJournalWired = true;

  const dateInput  = document.getElementById('sched-session-date');
  const refreshBtn = document.getElementById('sched-session-refresh');
  const toggleBtn  = document.getElementById('sched-session-toggle');
  const bodyEl     = document.getElementById('sched-session-body');

  if (dateInput && !dateInput.value)
    dateInput.value = new Date().toISOString().slice(0, 10);

  refreshBtn?.addEventListener('click', () => _renderSessionJournal());
  dateInput?.addEventListener('change', () => _renderSessionJournal());

  if (toggleBtn && bodyEl) {
    toggleBtn.addEventListener('click', e => {
      e.stopPropagation();
      const collapsed = bodyEl.classList.toggle('collapsed');
      toggleBtn.textContent = collapsed ? '▸' : '▾';
    });
  }

  _renderSessionJournal();
}

async function _renderSessionJournal() {
  const bodyEl    = document.getElementById('sched-session-body');
  const dateInput = document.getElementById('sched-session-date');
  if (!bodyEl) return;

  const date = dateInput?.value || undefined;
  const url  = date ? `/api/scheduler/journal?date=${date}` : '/api/scheduler/journal';

  const data = await fetch(url).then(r => r.json()).catch(() => null);

  if (!data || !data.ready) {
    bodyEl.innerHTML = '<div class="sched-session-empty">暂无日志（Scheduler 未初始化）</div>';
    return;
  }

  const msgs = data.messages ?? [];
  if (!msgs.length) {
    bodyEl.innerHTML = '<div class="sched-session-empty">今日暂无日志</div>';
    return;
  }

  // Preserve scroll position if already at bottom
  const atBottom = bodyEl.scrollHeight - bodyEl.scrollTop <= bodyEl.clientHeight + 4;

  bodyEl.innerHTML = '';
  [...msgs].reverse().forEach(msg => {
    const meta    = msg.meta ?? {};
    const ts      = msg.ts
      ? new Date(msg.ts).toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' })
      : '';
    const isMid   = meta.entry_type === 'mid_run_message';
    const tagCls  = isMid ? 'mid-run' : 'result';
    const tagText = isMid ? 'mid-run' : 'result';
    const content = msg.content ?? '';

    const el = document.createElement('div');
    el.className = 'sched-session-msg';
    el.innerHTML = `
      <div class="sched-session-msg-hdr">
        <span class="sched-session-task-name">${_esc(meta.task_name ?? '—')}</span>
        <span class="sched-session-tag ${tagCls}">${tagText}</span>
        <span class="sched-session-ts">${ts}</span>
      </div>
      <div class="sched-session-content">${_esc(content.slice(0, 500))}${content.length > 500 ? '…' : ''}</div>`;
    bodyEl.appendChild(el);
  });

  if (atBottom) bodyEl.scrollTop = bodyEl.scrollHeight;
}
