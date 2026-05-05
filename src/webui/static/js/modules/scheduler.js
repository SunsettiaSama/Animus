/**
 * modules/scheduler.js — Scheduled task CRUD and workstation panel.
 */

import { http, PATHS } from '../api.js';

const _cb = { onToast: () => {} };
export function setCallbacks(cbs) { Object.assign(_cb, cbs); }

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

// ── Workstation panel ─────────────────────────────────────────────────────────

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
    <div class="mc-row"><span class="mc-key">Tasks</span>
      <span class="mc-val">${tasks.length}</span></div>
    <div class="mc-row"><span class="mc-key">Pending</span>
      <span class="mc-val">${pending}</span></div>
    <div class="mc-row"><span class="mc-key">Running</span>
      <span class="mc-val">${running}</span></div>`;
}

export async function renderTaskTable() {
  const tbody = document.getElementById('sched-task-body');
  if (!tbody) return;

  const { tasks, ready } = await listTasks().catch(() => ({ tasks: [], ready: false }));
  if (!ready) {
    tbody.innerHTML = '<tr><td colspan="6" class="sched-empty">ReAct not initialized.</td></tr>';
    return;
  }
  if (!tasks.length) {
    tbody.innerHTML = '<tr><td colspan="6" class="sched-empty">No scheduled tasks.</td></tr>';
    return;
  }

  tbody.innerHTML = '';
  tasks.forEach(t => {
    const tr = document.createElement('tr');
    const nextRun = t.next_run ? new Date(t.next_run).toLocaleString() : '—';
    tr.innerHTML = `
      <td>${_esc(t.name)}</td>
      <td>${_esc(t.profile ?? '—')}</td>
      <td>${_esc(t.trigger_type ?? '—')}</td>
      <td>${nextRun}</td>
      <td><span class="task-badge ${t.status}">${t.status}</span></td>
      <td><button class="btn-secondary sched-cancel-btn" data-id="${t.id}">Cancel</button></td>`;
    tr.querySelector('.sched-cancel-btn').addEventListener('click', async () => {
      await cancelTask(t.id);
      renderTaskTable();
    });
    tbody.appendChild(tr);
  });
}

function _esc(s) {
  return String(s ?? '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}
