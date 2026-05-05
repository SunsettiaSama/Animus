/**
 * modules/scheduler.js — Scheduled task CRUD and workstation panel.
 */

import { http, PATHS } from '../api.js';

const _cb = { onToast: () => {} };
export function setCallbacks(cbs) { Object.assign(_cb, cbs); }

// ── Screen init ───────────────────────────────────────────────────────────────

export async function init() {
  _setTlDate();
  await Promise.allSettled([
    renderTaskTable(),
    renderTimeline(),
  ]);
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
  const done    = tasks.filter(t => t.status === 'done').length;
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
  running:   '⚡',
  done:      '✓',
  failed:    '✗',
  cancelled: '—',
};

export async function renderTaskTable() {
  const listEl = document.getElementById('sched-task-list');
  if (!listEl) return;

  const { tasks, ready } = await listTasks().catch(() => ({ tasks: [], ready: false }));

  // Update stats bar
  _setStat('sstat-total',   ready ? tasks.length : 0);
  _setStat('sstat-pending', tasks.filter(t => t.status === 'pending').length);
  _setStat('sstat-running', tasks.filter(t => t.status === 'running').length);
  _setStat('sstat-done',    tasks.filter(t => t.status === 'done').length);

  // Update status badge
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
    const trigClass  = `trigger-${t.trigger_type ?? 'once'}`;
    const icon       = _STATUS_ICON[t.status] ?? '●';

    card.innerHTML = `
      <div class="sched-task-icon ${_esc(t.status)}">${icon}</div>
      <div class="sched-task-main">
        <div class="sched-task-name">${_esc(t.name)}</div>
        <div class="sched-task-meta">
          ${t.config_profile ? `<span class="sched-tag">${_esc(t.config_profile)}</span>` : ''}
          ${t.trigger_type   ? `<span class="sched-tag ${_esc(trigClass)}">${_esc(t.trigger_type)}</span>` : ''}
        </div>
      </div>
      <div class="sched-task-right">
        <span class="task-badge ${_esc(t.status)}">${_esc(t.status)}</span>
        <span class="sched-task-next">${nextRun !== '—' ? `Next: ${nextRun}` : '—'}</span>
      </div>
      <button class="sched-task-cancel" title="Cancel task">Cancel</button>`;

    card.querySelector('.sched-task-cancel').addEventListener('click', async (e) => {
      e.stopPropagation();
      await cancelTask(t.id);
      renderTaskTable();
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

// ── Timeline ──────────────────────────────────────────────────────────────────

const _TYPE_LABEL = {
  scheduled_task: 'Scheduled Task',
  delegate_task:  'Delegated Task',
  tool_call:      'Tool Call',
  error:          'Error',
};

export async function renderTimeline() {
  const el = document.getElementById('sched-timeline-list');
  if (!el) return;

  const data   = await http.get(PATHS.timeline).catch(() => ({ events: [] }));
  const events = (data.events ?? []).slice().reverse();

  if (!events.length) {
    el.innerHTML = '<div class="sched-tl-empty">No activity today.</div>';
    return;
  }

  el.innerHTML = events.map(ev => {
    const time   = new Date(ev.ts).toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' });
    const name   = ev.payload?.task_name ?? ev.payload?.name ?? ev.type;
    const dotCls = Object.keys(_TYPE_LABEL).includes(ev.type) ? ev.type : 'default';
    const label  = _TYPE_LABEL[ev.type] ?? ev.type;
    return `
      <div class="sched-tl-event">
        <span class="sched-tl-dot ${_esc(dotCls)}"></span>
        <div class="sched-tl-body">
          <div class="sched-tl-name">${_esc(name)}</div>
          <div class="sched-tl-type">${_esc(label)}</div>
        </div>
        <span class="sched-tl-time">${time}</span>
      </div>`;
  }).join('');
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function _esc(s) {
  return String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}
