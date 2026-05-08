/**
 * modules/scheduler.js — Scheduled task CRUD + 24h horizontal timeline axis.
 */

import { http, PATHS } from '../api.js';

const _cb = { onToast: () => {} };
export function setCallbacks(cbs) { Object.assign(_cb, cbs); }

// ── Screen init ───────────────────────────────────────────────────────────────

let _axisRefreshTimer = null;
let _needleTimer      = null;

export async function init() {
  _setTlDate();
  _wireFormTriggerTabs();
  _wireProactiveToggle();

  await Promise.allSettled([
    renderTaskTable(),
    renderTimelineAxis(),
  ]);

  // Refresh axis data every 30 s; update needle position every second
  if (_axisRefreshTimer) clearInterval(_axisRefreshTimer);
  if (_needleTimer)      clearInterval(_needleTimer);
  _axisRefreshTimer = setInterval(renderTimelineAxis, 30_000);
  _needleTimer      = setInterval(_updateNeedle, 1_000);
}

function _setTlDate() {
  const el = document.getElementById('sched-tl-date');
  if (el) el.textContent = new Date().toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
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
  const bodyEl = document.getElementById('mc-scheduler-body');
  if (!bodyEl) return;

  const { tasks, ready } = await listTasks().catch(() => ({ tasks: [], ready: false }));
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

  if (!tasks.length) {
    listEl.innerHTML = `
      <div class="sched-empty-state">
        <div class="sched-empty-icon">🗓</div>
        <div class="sched-empty-text">No scheduled tasks</div>
        <div class="sched-empty-hint">Click <strong>+ New Task</strong> to schedule your first agent run</div>
      </div>`;
    return;
  }

  listEl.innerHTML = '';
  tasks.forEach(t => {
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
  _renderTimelineList(data.events ?? []);
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

// ── Vertical event list (below axis) ─────────────────────────────────────────

const _TYPE_LABEL = {
  scheduled_task: 'Scheduled Task',
  delegate_task:  'Delegated Task',
  tool_call:      'Tool Call',
  conversation:   'Conversation',
  plan_event:     'Plan Event',
  error:          'Error',
};

function _renderTimelineList(events) {
  const el = document.getElementById('sched-timeline-list');
  if (!el) return;

  const reversed = [...events].reverse();

  if (!reversed.length) {
    el.innerHTML = '<div class="sched-tl-empty">No activity today.</div>';
    return;
  }

  el.innerHTML = reversed.map(ev => {
    const time   = new Date(ev.ts).toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' });
    const name   = ev.payload?.task_name ?? ev.payload?.name ?? ev.payload?.summary ?? ev.type;
    const dotCls = Object.keys(_TYPE_LABEL).includes(ev.type) ? ev.type : 'default';
    const label  = _TYPE_LABEL[ev.type] ?? ev.type;
    return `
      <div class="sched-tl-event">
        <span class="sched-tl-dot ${_esc(dotCls)}"></span>
        <div class="sched-tl-body">
          <div class="sched-tl-name">${_esc(String(name ?? ''))}</div>
          <div class="sched-tl-type">${_esc(label)}</div>
        </div>
        <span class="sched-tl-time">${time}</span>
      </div>`;
  }).join('');
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

// ── Helpers ───────────────────────────────────────────────────────────────────

function _esc(s) {
  return String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

// Re-export renderTimeline alias for backward compatibility
export const renderTimeline = renderTimelineAxis;
