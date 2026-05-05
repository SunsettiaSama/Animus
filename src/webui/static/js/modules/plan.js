/**
 * plan.js — Plan Mode frontend module
 *
 * Responsibilities:
 *   - Render a live SVG DAG from task data
 *   - Connect to /api/plan/stream (SSE) for live node status updates
 *   - Submit new plan questions via /api/plan/run
 *   - Load/display snapshots and allow rollback
 *   - Refresh and display log tail
 *   - Shadow editor (read-only display of current plan markdown)
 */

// ── Constants ─────────────────────────────────────────────────────────────────

const API = {
  run:       '/api/plan/run',
  status:    '/api/plan/status',
  stream:    '/api/plan/stream',
  snapshots: '/api/plan/snapshots',
  rollback:  '/api/plan/rollback',
  logs:      '/api/plan/logs',
  pause:     '/api/plan/pause',
  resume:    '/api/plan/resume',
  skip:      (tid) => `/api/plan/skip/${tid}`,
};

const NODE_W  = 130;
const NODE_H  = 36;
const COL_GAP = 60;
const ROW_GAP = 18;
const PAD     = 24;

// ── State ─────────────────────────────────────────────────────────────────────

let _sse = null;       // EventSource
let _tasks = [];       // last-known task list
let _planId = null;

// ── DOM helpers ───────────────────────────────────────────────────────────────

const $ = (id) => document.getElementById(id);

function _setText(id, text) {
  const el = $(id);
  if (el) el.textContent = text;
}

function _setBadge(status) {
  const el = $('plan-status-badge');
  if (!el) return;
  el.textContent = status;
  el.className = `plan-badge ${status}`;
}

// ── BFS DAG layout ────────────────────────────────────────────────────────────

/**
 * Assign BFS depth (column) to each task, then stack tasks in the same column.
 * Returns an array of { task_id, cx, cy, col, row } layout objects.
 */
function dagLayout(tasks) {
  if (!tasks.length) return [];

  const idToTask = {};
  for (const t of tasks) idToTask[t.task_id] = t;

  // Compute depth via BFS from roots (tasks with no depends_on in current set)
  const depth = {};
  const allIds = new Set(tasks.map(t => t.task_id));

  // Initialise: tasks with no in-set dependencies start at depth 0
  const queue = [];
  for (const t of tasks) {
    const hasDep = t.depends_on && t.depends_on.some(d => allIds.has(d));
    if (!hasDep) {
      depth[t.task_id] = 0;
      queue.push(t.task_id);
    }
  }

  // Propagate depths
  let head = 0;
  while (head < queue.length) {
    const id = queue[head++];
    const d = depth[id];
    for (const t of tasks) {
      if (t.depends_on && t.depends_on.includes(id)) {
        const newD = d + 1;
        if (depth[t.task_id] === undefined || depth[t.task_id] < newD) {
          depth[t.task_id] = newD;
          queue.push(t.task_id);
        }
      }
    }
  }

  // Tasks not reached (isolated or orphaned) go to col 0
  for (const t of tasks) {
    if (depth[t.task_id] === undefined) depth[t.task_id] = 0;
  }

  // Group by column
  const cols = {};
  for (const t of tasks) {
    const c = depth[t.task_id];
    if (!cols[c]) cols[c] = [];
    cols[c].push(t.task_id);
  }

  // Assign (cx, cy)
  const layout = {};
  const colKeys = Object.keys(cols).map(Number).sort((a, b) => a - b);
  for (const col of colKeys) {
    const ids = cols[col];
    for (let row = 0; row < ids.length; row++) {
      const cx = PAD + col * (NODE_W + COL_GAP) + NODE_W / 2;
      const cy = PAD + row * (NODE_H + ROW_GAP) + NODE_H / 2;
      layout[ids[row]] = { col, row, cx, cy };
    }
  }

  return tasks.map(t => ({ ...t, ...(layout[t.task_id] || { cx: PAD, cy: PAD, col: 0, row: 0 }) }));
}

// ── SVG helpers ───────────────────────────────────────────────────────────────

function _svgEl(tag, attrs = {}) {
  const el = document.createElementNS('http://www.w3.org/2000/svg', tag);
  for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, v);
  return el;
}

// ── Full DAG render (called on initial load and replan) ───────────────────────

export function renderDAG(tasks) {
  _tasks = tasks;
  const svg = $('plan-dag-svg');
  if (!svg) return;

  // Clear previous
  while (svg.firstChild) svg.removeChild(svg.firstChild);

  if (!tasks.length) {
    const t = _svgEl('text', { x: 20, y: 30, fill: '#9ca3af', 'font-size': '13' });
    t.textContent = 'No tasks yet.';
    svg.appendChild(t);
    return;
  }

  const layed = dagLayout(tasks);
  const idToLayout = {};
  for (const l of layed) idToLayout[l.task_id] = l;

  // Compute canvas size
  const maxX = Math.max(...layed.map(l => l.cx + NODE_W / 2)) + PAD;
  const maxY = Math.max(...layed.map(l => l.cy + NODE_H / 2)) + PAD;
  svg.setAttribute('width',  maxX);
  svg.setAttribute('height', maxY);
  svg.setAttribute('viewBox', `0 0 ${maxX} ${maxY}`);

  // Arrowhead marker
  const defs = _svgEl('defs');
  const marker = _svgEl('marker', {
    id: 'arrow', markerWidth: '8', markerHeight: '8',
    refX: '8', refY: '3', orient: 'auto',
  });
  const path = _svgEl('path', { d: 'M0,0 L0,6 L8,3 z', fill: '#9ca3af' });
  marker.appendChild(path);
  defs.appendChild(marker);
  svg.appendChild(defs);

  // Edges
  for (const task of layed) {
    for (const dep of (task.depends_on || [])) {
      const src = idToLayout[dep];
      if (!src) continue;
      const x1 = src.cx + NODE_W / 2;
      const y1 = src.cy;
      const x2 = task.cx - NODE_W / 2;
      const y2 = task.cy;
      const mx = (x1 + x2) / 2;

      const g = _svgEl('g', { class: 'dag-edge' });
      // Bezier for curved edges when same row, straight otherwise
      const p = _svgEl('path', {
        d: `M${x1},${y1} C${mx},${y1} ${mx},${y2} ${x2},${y2}`,
        fill: 'none', stroke: '#9ca3af', 'stroke-width': '1.5',
        'marker-end': 'url(#arrow)',
      });
      g.appendChild(p);
      svg.appendChild(g);
    }
  }

  // Nodes
  for (const task of layed) {
    const status = task.status || 'pending';
    const g = _svgEl('g', {
      class: `dag-node dag-${status}`,
      id: `dag-node-${task.task_id}`,
      transform: `translate(${task.cx - NODE_W / 2},${task.cy - NODE_H / 2})`,
    });

    const rect = _svgEl('rect', {
      width: NODE_W, height: NODE_H,
      rx: '6', ry: '6', 'stroke-width': '1.5',
    });

    const label = task.task_id.length > 15
      ? task.task_id.slice(0, 13) + '…'
      : task.task_id;

    const text = _svgEl('text', {
      x: NODE_W / 2, y: NODE_H / 2 + 4,
      'text-anchor': 'middle',
    });
    text.textContent = label;

    // Tooltip
    const title = _svgEl('title');
    title.textContent = `${task.task_id} [${status}]\n${task.description || ''}\n${task.result ? 'Result: ' + task.result.slice(0, 120) : ''}${task.error ? 'Error: ' + task.error.slice(0, 120) : ''}`;

    g.appendChild(rect);
    g.appendChild(text);
    g.appendChild(title);
    svg.appendChild(g);
  }
}

// ── Incremental node update (no full re-render) ────────────────────────────────

function _updateNode(taskId, status) {
  const node = document.getElementById(`dag-node-${taskId}`);
  if (!node) return;
  // Remove old status classes and apply new
  node.className.baseVal = node.className.baseVal.replace(/dag-\w+/g, '').trim();
  node.className.baseVal += ` dag-node dag-${status}`;

  // Update tooltip
  const title = node.querySelector('title');
  const task = _tasks.find(t => t.task_id === taskId);
  if (title && task) {
    task.status = status;
    title.textContent = `${task.task_id} [${status}]\n${task.description || ''}\n${task.result ? 'Result: ' + task.result.slice(0, 120) : ''}${task.error ? 'Error: ' + task.error.slice(0, 120) : ''}`;
  }
}

// ── SSE connection ─────────────────────────────────────────────────────────────

function _connectSSE() {
  if (_sse) { _sse.close(); _sse = null; }
  _sse = new EventSource(API.stream);

  _sse.onmessage = (e) => {
    let ev;
    if (!e.data || e.data === '{}') return;
    ev = JSON.parse(e.data);

    switch (ev.type) {
      case 'plan_start':
        _planId = ev.plan_id;
        _setText('plan-title', ev.title || 'Plan Mode');
        _setBadge('running');
        _setBadge('running');
        break;

      case 'task_running':
        _updateNode(ev.task_id, 'running');
        break;

      case 'task_complete':
        _updateNode(ev.task_id, 'done');
        // Update task result for tooltip
        const t = _tasks.find(x => x.task_id === ev.task_id);
        if (t) t.result = ev.result_preview;
        break;

      case 'task_failed':
        _updateNode(ev.task_id, 'failed');
        const tf = _tasks.find(x => x.task_id === ev.task_id);
        if (tf) tf.error = ev.error;
        break;

      case 'task_skipped':
        _updateNode(ev.task_id, 'skipped');
        break;

      case 'replan':
        // Reload full plan after replanning (task list may change)
        refreshStatus();
        break;

      case 'plan_complete':
      case 'done':
        _setBadge('done');
        if (_sse) { _sse.close(); _sse = null; }
        refreshSnapshots();
        refreshLogs();
        break;

      case 'plan_abort':
        _setBadge('failed');
        if (_sse) { _sse.close(); _sse = null; }
        break;

      case 'snapshot':
        refreshSnapshots();
        break;
    }
  };

  _sse.onerror = () => {
    if (_sse) { _sse.close(); _sse = null; }
  };
}

// ── Load current plan status ───────────────────────────────────────────────────

async function refreshStatus() {
  const res = await fetch(API.status).then(r => r.json()).catch(() => null);
  if (!res || !res.doc) return;

  const doc = res.doc;
  _planId = doc.plan_id;
  _setText('plan-title', doc.title || 'Plan Mode');

  // Collect all tasks
  const tasks = (doc.modules || []).flatMap(m => m.tasks || []);
  renderDAG(tasks);

  // Populate shadow editor
  const editor = $('plan-shadow-editor');
  if (editor) {
    editor.value = _docToMarkdown(doc);
    editor.removeAttribute('readonly');
  }

  // Update status badge
  const allDone = tasks.every(t => ['done', 'skipped', 'failed'].includes(t.status));
  _setBadge(allDone ? 'done' : (doc.metadata?.paused ? 'paused' : 'running'));
}

// ── Minimal doc→markdown for shadow editor ────────────────────────────────────

function _docToMarkdown(doc) {
  const lines = [`# Plan: ${doc.title || ''}`, '', `## Objective`, doc.objective || '', ''];
  lines.push('## Tasks', '');
  for (const mod of (doc.modules || [])) {
    lines.push(`### Module: ${mod.name}`);
    for (const t of (mod.tasks || [])) {
      const mark = { pending: '[ ]', running: '[>]', done: '[x]', failed: '[!]', skipped: '[-]', paused: '[~]' }[t.status] || '[ ]';
      const ann = [`\`profile:${t.profile || 'minimal'}\``];
      if (t.depends_on?.length) ann.push(`\`depends_on:${t.depends_on.join(',')}\``);
      if (t.writes?.length) ann.push(`\`writes:${t.writes.join(',')}\``);
      lines.push(`- ${mark} **${t.task_id}** ${ann.join(' ')}`);
      lines.push(`  ${t.description || ''}`);
    }
    lines.push('');
  }
  return lines.join('\n');
}

// ── Snapshots ──────────────────────────────────────────────────────────────────

async function refreshSnapshots() {
  const snaps = await fetch(API.snapshots).then(r => r.json()).catch(() => []);
  const list = $('plan-snaps-list');
  if (!list) return;

  if (!snaps.length) {
    list.innerHTML = '<span class="plan-empty-msg">No snapshots yet.</span>';
    return;
  }

  list.innerHTML = snaps.map(s => {
    const ts = new Date(s.timestamp * 1000).toLocaleTimeString();
    return `<div class="plan-snap-item">
      <span class="plan-snap-info">${ts} — ${s.trigger} (cycle ${s.cycle})</span>
      <span class="plan-snap-rollback" data-sid="${s.snapshot_id}">Rollback</span>
    </div>`;
  }).join('');

  list.querySelectorAll('[data-sid]').forEach(el => {
    el.addEventListener('click', () => doRollback(el.dataset.sid));
  });
}

async function doRollback(snapshot_id) {
  if (!confirm(`Rollback to snapshot ${snapshot_id.slice(0, 8)}…?`)) return;
  const res = await fetch(API.rollback, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ snapshot_id }),
  }).then(r => r.json()).catch(() => null);

  if (res?.status === 'ok') {
    refreshStatus();
  }
}

// ── Logs ───────────────────────────────────────────────────────────────────────

async function refreshLogs(n = 100) {
  const records = await fetch(`${API.logs}?n=${n}`).then(r => r.json()).catch(() => []);
  const container = $('plan-logs-container');
  if (!container) return;

  if (!records.length) {
    container.innerHTML = '<span class="plan-empty-msg">No logs yet.</span>';
    return;
  }

  container.innerHTML = records.map(r => {
    const lvl = r.level || 'debug';
    const ts = new Date((r.ts || 0) * 1000).toLocaleTimeString();
    const msg = `[${ts}] [${lvl.toUpperCase()}] ${r.event}${r.task_id ? ' task=' + r.task_id : ''}`;
    return `<span class="plan-log-line log-${lvl}">${_escapeHtml(msg)}</span>`;
  }).join('\n');

  container.scrollTop = container.scrollHeight;
}

function _escapeHtml(s) {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

// ── Run plan ───────────────────────────────────────────────────────────────────

async function runPlan() {
  const questionEl = $('plan-question');
  if (!questionEl) return;
  const question = questionEl.value.trim();
  if (!question) return;

  _setBadge('running');
  _setText('plan-title', 'Planning…');
  renderDAG([]);

  const body = {
    question,
    plan_dir: '.cache/plans',
    llm_cfg_path: '',
  };

  await fetch(API.run, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });

  // Connect SSE for live updates
  _connectSSE();

  // Poll status once after a short delay to get initial DAG
  setTimeout(refreshStatus, 1500);
}

// ── Pause / Resume ─────────────────────────────────────────────────────────────

async function togglePause() {
  const doc = await fetch(API.status).then(r => r.json()).catch(() => null);
  const paused = doc?.doc?.metadata?.paused;
  await fetch(paused ? API.resume : API.pause, { method: 'POST' });
  const btnPause  = $('plan-btn-pause');
  const btnResume = $('plan-btn-resume');
  if (paused) {
    _setBadge('running');
    btnPause?.classList.remove('hidden');
    btnResume?.classList.add('hidden');
  } else {
    _setBadge('paused');
    btnPause?.classList.add('hidden');
    btnResume?.classList.remove('hidden');
  }
}

// ── Manual snapshot ────────────────────────────────────────────────────────────

async function takeSnapshot() {
  // The orchestrator snapshot is triggered via plan_pause/plan_snapshot tools;
  // here we just refresh the list as a convenience.
  await refreshSnapshots();
}

// ── Bind events ───────────────────────────────────────────────────────────────

function _bind() {
  $('plan-btn-run')?.addEventListener('click', runPlan);
  $('plan-btn-pause')?.addEventListener('click', togglePause);
  $('plan-btn-resume')?.addEventListener('click', togglePause);
  $('plan-btn-snapshot')?.addEventListener('click', takeSnapshot);
  $('plan-btn-refresh-logs')?.addEventListener('click', () => refreshLogs());
}

// ── Public init ───────────────────────────────────────────────────────────────

let _initialized = false;

export function init() {
  if (_initialized) {
    // Re-entering the plan screen — refresh existing state
    refreshStatus();
    refreshSnapshots();
    refreshLogs();
    return;
  }
  _initialized = true;
  _bind();
  refreshStatus();
  refreshSnapshots();
  refreshLogs();
}
