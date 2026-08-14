/**
 * Work UI — confirmation cards, task cards, monitor panel.
 */
import * as store from './store.js';

const _esc = s => String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');

let _sendWorkFrame = null;
let _onHistoryPersist = null;

export function configure({ sendWorkFrame, onHistoryPersist } = {}) {
  _sendWorkFrame = sendWorkFrame || null;
  _onHistoryPersist = onHistoryPersist || null;
}

function _msgsEl() {
  return document.getElementById('msgs');
}

function _cardEl(workId) {
  return document.querySelector(`.work-card[data-work-id="${CSS.escape(workId)}"]`);
}

function _statusLabel(status) {
  const map = {
    detected: '已检测',
    pending_confirmation: '待确认',
    declined: '不执行',
    fallback_to_speak: '转对话',
    starting: '启动中',
    running: '执行中',
    finished: '已完成',
    failed: '失败',
    aborted: '已中止',
  };
  return map[status] || status;
}

function _ensureCard(item) {
  let el = _cardEl(item.workId);
  if (el) return el;
  const msgs = _msgsEl();
  if (!msgs) return null;
  document.getElementById('empty-hint')?.remove();
  el = document.createElement('div');
  el.className = 'msg work-msg';
  el.innerHTML = `
    <div class="work-card" data-work-id="${_esc(item.workId)}">
      <div class="work-card-hdr">
        <span class="work-card-icon">⚙</span>
        <span class="work-card-title">Worker 任务</span>
        <span class="work-card-status" data-role="status"></span>
      </div>
      <div class="work-card-question" data-role="question"></div>
      <div class="work-card-body" data-role="body"></div>
      <div class="work-card-actions" data-role="actions"></div>
    </div>`;
  msgs.appendChild(el);
  return el.querySelector('.work-card');
}

function _renderCard(item) {
  const card = _ensureCard(item);
  if (!card) return;
  card.dataset.status = item.status;
  const statusEl = card.querySelector('[data-role="status"]');
  const qEl = card.querySelector('[data-role="question"]');
  const bodyEl = card.querySelector('[data-role="body"]');
  const actionsEl = card.querySelector('[data-role="actions"]');
  if (statusEl) statusEl.textContent = _statusLabel(item.status);
  if (qEl) qEl.textContent = item.question || '';

  let body = item.message || '';
  if (item.status === 'pending_confirmation') {
    body = item.prompt || item.message || '要交给 Worker 执行吗？';
  } else if (item.status === 'declined' || item.status === 'failed' || item.status === 'aborted') {
    body = item.reason || item.message || '';
  } else if (item.status === 'finished') {
    body = item.answer || item.message || '任务完成';
  } else if (item.status === 'running' || item.status === 'starting') {
    const step = item.monitor?.step_index ?? item.monitor?.step_count;
    body = step != null ? `${item.message || '执行中'} · step ${step}` : (item.message || '执行中…');
  }
  if (bodyEl) bodyEl.textContent = body;

  if (actionsEl) {
    actionsEl.innerHTML = '';
    if (item.status === 'pending_confirmation' && !item.restored) {
      const approve = document.createElement('button');
      approve.className = 'work-btn work-btn-primary';
      approve.textContent = '开始执行';
      approve.addEventListener('click', () => {
        _sendWorkFrame?.({
          type: 'work_confirmation_response',
          work_id: item.workId,
          approved: true,
        });
      });
      const decline = document.createElement('button');
      decline.className = 'work-btn';
      decline.textContent = '不执行';
      decline.addEventListener('click', () => {
        _sendWorkFrame?.({
          type: 'work_confirmation_response',
          work_id: item.workId,
          approved: false,
          reason: '用户拒绝执行',
          reason_code: 'user_declined',
        });
      });
      actionsEl.append(approve, decline);
    } else if (item.status === 'running' || item.status === 'starting') {
      const abort = document.createElement('button');
      abort.className = 'work-btn work-btn-danger';
      abort.textContent = '中止';
      abort.addEventListener('click', () => {
        _sendWorkFrame?.({ type: 'work_abort', work_id: item.workId });
      });
      const mon = document.createElement('button');
      mon.className = 'work-btn';
      mon.textContent = '刷新监控';
      mon.addEventListener('click', () => {
        _sendWorkFrame?.({ type: 'work_monitor_request', work_id: item.workId });
        openMonitor(item.workId);
      });
      actionsEl.append(abort, mon);
    } else {
      const open = document.createElement('button');
      open.className = 'work-btn';
      open.textContent = '查看详情';
      open.addEventListener('click', () => openMonitor(item.workId));
      actionsEl.append(open);
    }
  }

  const msgs = _msgsEl();
  if (msgs) msgs.scrollTop = msgs.scrollHeight;
  renderMonitor(item.workId);
}

export function openMonitor(workId) {
  const panel = document.getElementById('work-monitor-panel');
  if (!panel) return;
  panel.classList.remove('hidden');
  panel.dataset.workId = workId || '';
  renderMonitor(workId);
}

export function closeMonitor() {
  document.getElementById('work-monitor-panel')?.classList.add('hidden');
}

export function renderMonitor(workId) {
  const panel = document.getElementById('work-monitor-panel');
  if (!panel || panel.classList.contains('hidden')) return;
  const id = workId || panel.dataset.workId;
  const item = id ? store.get(id) : null;
  const title = panel.querySelector('[data-role="mon-title"]');
  const body = panel.querySelector('[data-role="mon-body"]');
  if (!item) {
    if (title) title.textContent = '任务监控';
    if (body) body.innerHTML = '<div class="work-mon-empty">暂无任务</div>';
    return;
  }
  if (title) title.textContent = `任务 · ${_statusLabel(item.status)}`;
  const events = (item.events || []).slice(-12).map(ev =>
    `<div class="work-mon-line"><span class="work-mon-type">${_esc(ev.type)}</span> ${_esc(ev.message || ev.reason || '')}</div>`
  ).join('');
  if (body) {
    body.innerHTML = `
      <div class="work-mon-q">${_esc(item.question)}</div>
      <div class="work-mon-meta">status: ${_esc(item.status)}${item.reason ? ` · ${_esc(item.reason)}` : ''}</div>
      ${item.answer ? `<div class="work-mon-answer">${_esc(item.answer)}</div>` : ''}
      <div class="work-mon-events">${events || '<div class="work-mon-empty">暂无事件</div>'}</div>
    `;
  }
}

export function handleWorkEvent(event) {
  const item = store.ingest(event);
  if (!item) return;
  _renderCard(item);
  if (['work_confirmation_required', 'work_started', 'work_progress'].includes(event.type)) {
    openMonitor(item.workId);
  }
  if (_onHistoryPersist) _onHistoryPersist();
}

export function rebuildWorkCards(workItems) {
  store.restoreFromHistory(workItems);
  store.all().forEach(item => _renderCard(item));
}

export function bindMonitorPanel() {
  document.getElementById('btn-work-monitor-close')?.addEventListener('click', closeMonitor);
  document.getElementById('btn-open-work-monitor')?.addEventListener('click', () => {
    const active = store.all().find(i =>
      ['pending_confirmation', 'starting', 'running'].includes(i.status)
    ) || store.all().at(-1);
    openMonitor(active?.workId);
  });
}
