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

import { Inspector } from '../components/Inspector.js';

// ── Constants ─────────────────────────────────────────────────────────────────

const API = {
  run:           '/api/plan/run',
  status:        '/api/plan/status',
  stream:        '/api/plan/stream',
  snapshots:     '/api/plan/snapshots',
  rollback:      '/api/plan/rollback',
  logs:          '/api/plan/logs',
  pause:         '/api/plan/pause',
  resume:        '/api/plan/resume',
  skip:          (tid) => `/api/plan/skip/${tid}`,
  taskPatch:     (tid) => `/api/plan/tasks/${tid}`,
  humanRequest:  '/api/plan/human-request',
  history:       '/api/plan/history',
  historyDel:    (pid) => `/api/plan/history/${pid}`,
};

const NODE_W  = 164;
const NODE_H  = 54;
const COL_GAP = 80;
const ROW_GAP = 20;
const PAD     = 28;

const STATUS_ICONS = { running: '⟳', done: '✓', failed: '✗', skipped: '—' };

const API_TASK_STEPS = (tid) => `/api/plan/task/${tid}/steps`;

// ── State ─────────────────────────────────────────────────────────────────────

let _sse = null;             // EventSource
let _tasks = [];             // last-known task list
let _planId = null;
let _logPollInterval = null; // setInterval handle for log polling
let _thinkingCollapsed = false;

// ── Inspector state ───────────────────────────────────────────────────────────

let _inspectorTaskId = null;   // currently inspected task_id
let _inspectorSse    = null;   // SSE source for live step streaming

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

/**
 * Render a DAG of tasks into an SVG element.
 * @param {Array}  tasks          - Task array from plan doc.
 * @param {string} [svgSelector]  - Optional CSS selector or element-id for the target SVG.
 *                                  Defaults to '#plan-dag-svg'.
 * @param {boolean} [enableInspector] - If false, suppress dblclick inspector binding.
 */
export function renderDAG(tasks, svgSelector, enableInspector = true) {
  _tasks = tasks;
  const svg = svgSelector
    ? (svgSelector.startsWith('#') ? document.querySelector(svgSelector) : document.getElementById(svgSelector))
    : $('plan-dag-svg');
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

  // Edges (drawn before nodes so nodes render on top)
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
      // Orthogonal path: same row → straight; different row → elbow
      const d = (Math.abs(y1 - y2) < 4)
        ? `M${x1},${y1} L${x2},${y2}`
        : `M${x1},${y1} H${mx} V${y2} H${x2}`;
      const p = _svgEl('path', {
        d,
        fill: 'none',
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
      rx: '7', ry: '7', 'stroke-width': '1.5',
    });

    // Primary label: task_id (truncated)
    const label = task.task_id.length > 18 ? task.task_id.slice(0, 16) + '…' : task.task_id;
    const idText = _svgEl('text', {
      x: NODE_W / 2, y: 20,
      'text-anchor': 'middle', class: 'dag-node-id',
    });
    idText.textContent = label;

    // Secondary label: description or module (truncated)
    const rawDesc = (task.description || task.module || '').trim();
    const descLabel = rawDesc.length > 24 ? rawDesc.slice(0, 22) + '…' : rawDesc;
    const descText = _svgEl('text', {
      x: NODE_W / 2, y: 37,
      'text-anchor': 'middle', class: 'dag-node-desc',
    });
    descText.textContent = descLabel;

    // Status icon (top-right corner)
    const iconChar = STATUS_ICONS[status] || '';
    if (iconChar) {
      const iconEl = _svgEl('text', {
        x: NODE_W - 7, y: 15,
        'text-anchor': 'end', class: 'dag-node-icon',
      });
      iconEl.textContent = iconChar;
      g.appendChild(iconEl);
    }

    // Tooltip (native SVG title — shown on hover)
    const title = _svgEl('title');
    title.textContent = [
      `${task.task_id} [${status}]`,
      task.description || '',
      task.depends_on?.length ? `depends: ${task.depends_on.join(', ')}` : '',
      task.result  ? `result: ${task.result.slice(0, 160)}`  : '',
      task.error   ? `error: ${task.error.slice(0, 160)}`    : '',
    ].filter(Boolean).join('\n');

    g.appendChild(rect);
    g.appendChild(idText);
    g.appendChild(descText);
    g.appendChild(title);
    svg.appendChild(g);

    // Double-click opens the inspector for this node
    if (enableInspector) {
      g.addEventListener('dblclick', () => openNodeInspector(task));
    }
  }
}

// ── Node Inspector ────────────────────────────────────────────────────────────

function _escHtml(s) {
  return String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

// ── Thinking panel helpers ────────────────────────────────────────────────────

function _thinkingShow(title) {
  const panel = $('plan-thinking-panel');
  const titleEl = $('plan-thinking-title');
  if (panel) panel.classList.remove('hidden');
  if (titleEl) titleEl.textContent = title;
  _thinkingCollapsed = false;
  const body = $('plan-thinking-body');
  if (body) body.parentElement?.classList.remove('thinking-collapsed');
  const toggle = $('plan-thinking-toggle');
  if (toggle) toggle.textContent = '▾';
}

function _thinkingClear() {
  const body = $('plan-thinking-body');
  if (body) body.textContent = '';
}

function _thinkingCollapse() {
  _thinkingCollapsed = true;
  const body = $('plan-thinking-body');
  if (body) body.parentElement?.classList.add('thinking-collapsed');
  const toggle = $('plan-thinking-toggle');
  if (toggle) toggle.textContent = '▸';
}

function _thinkingAppend(stepIndex, thought, action, obs) {
  const body = $('plan-thinking-body');
  if (!body) return;
  let text = `\n[Step ${stepIndex + 1}]`;
  if (thought) text += `\n💭 ${thought}`;
  if (action)  text += `\n🔧 ${action}`;
  if (obs)     text += `\n👁 ${obs.slice(0, 300)}`;
  text += '\n';
  body.textContent += text;
  body.scrollTop = body.scrollHeight;
}

function _thinkingAppendRaw(text) {
  const body = $('plan-thinking-body');
  if (!body) return;
  body.textContent += '\n' + text + '\n';
  body.scrollTop = body.scrollHeight;
}

function _bindThinkingToggle() {
  $('plan-thinking-toggle')?.addEventListener('click', () => {
    _thinkingCollapsed = !_thinkingCollapsed;
    const body = $('plan-thinking-body');
    const toggle = $('plan-thinking-toggle');
    if (_thinkingCollapsed) {
      body?.parentElement?.classList.add('thinking-collapsed');
      if (toggle) toggle.textContent = '▸';
    } else {
      body?.parentElement?.classList.remove('thinking-collapsed');
      if (toggle) toggle.textContent = '▾';
    }
  });
}

// ── History helpers ───────────────────────────────────────────────────────────

function _renderStepCard(step, index) {
  const isSub = step.type === 'sub_agent';
  const cls   = isSub ? 'tao-step tao-step-sub' : 'tao-step';
  const lbl   = isSub ? `SubAgent #${index + 1}` : `Step ${index + 1}`;
  const thought = step.thought      ? `<div class="tao-row"><span class="tao-lbl">💭</span><span class="tao-val">${_escHtml(step.thought)}</span></div>` : '';
  const action  = step.action       ? `<div class="tao-row"><span class="tao-lbl">🔧 ${_escHtml(step.action)}</span></div>` : '';
  const ainput  = step.action_input ? `<div class="tao-row"><span class="tao-lbl">   Input</span><span class="tao-val tao-code">${_escHtml(typeof step.action_input === 'object' ? JSON.stringify(step.action_input, null, 2) : step.action_input)}</span></div>` : '';
  const obs     = step.observation  ? `<div class="tao-row"><span class="tao-lbl">👁</span><span class="tao-val">${_escHtml(String(step.observation).slice(0, 400))}</span></div>` : '';
  return `<div class="${cls}">
    <div class="tao-step-hdr">${_escHtml(lbl)}</div>
    ${thought}${action}${ainput}${obs}
  </div>`;
}

function _renderInspectorSteps(steps) {
  const container = document.getElementById('pi-steps');
  if (!container) return;
  if (!steps.length) {
    container.innerHTML = '<div class="pi-empty">No steps recorded yet.</div>';
    return;
  }
  container.innerHTML = steps.map((s, i) => _renderStepCard(s, i)).join('');
}

function _appendInspectorStep(step) {
  const idx = document.getElementById('pi-steps')?.children.length ?? 0;
  Inspector.appendStep(_renderStepCard(step, idx));
}

export async function openNodeInspector(task) {
  // Close any existing SSE stream for inspector
  if (_inspectorSse) { _inspectorSse.close(); _inspectorSse = null; }
  _inspectorTaskId = task.task_id;

  const isPending = task.status === 'pending';

  Inspector.open({
    title:       task.task_id,
    badge:       task.status || 'pending',
    description: task.description || '',
  });

  // Inject edit controls for pending tasks (T5)
  if (isPending) {
    const descEl = document.getElementById('pi-description');
    if (descEl) {
      const editBtn = document.createElement('button');
      editBtn.textContent = '编辑';
      editBtn.className = 'pi-edit-btn';
      editBtn.style.cssText = 'margin-left:8px;font-size:12px;padding:2px 8px;cursor:pointer;';
      descEl.after(editBtn);

      editBtn.addEventListener('click', () => {
        const isEditing = editBtn.dataset.editing === '1';
        if (!isEditing) {
          // Enter edit mode
          const textarea = document.createElement('textarea');
          textarea.id = 'pi-desc-edit';
          textarea.value = task.description || '';
          textarea.style.cssText = 'width:100%;min-height:80px;margin-top:6px;font-size:13px;';
          descEl.after(textarea);
          editBtn.textContent = '保存';
          editBtn.dataset.editing = '1';
        } else {
          // Save
          const textarea = document.getElementById('pi-desc-edit');
          const newDesc = textarea?.value?.trim() || '';
          textarea?.remove();
          editBtn.textContent = '编辑';
          editBtn.dataset.editing = '0';
          if (newDesc && newDesc !== task.description) {
            fetch(API.taskPatch(task.task_id), {
              method: 'PATCH',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ description: newDesc }),
            }).then(r => r.json()).then(() => {
              task.description = newDesc;
              if (descEl) descEl.textContent = newDesc;
              refreshStatus();
            }).catch(() => {});
          }
        }
      });
    }
  }

  // Register SSE cleanup when user closes inspector
  Inspector.onClose(() => {
    if (_inspectorSse) { _inspectorSse.close(); _inspectorSse = null; }
    _inspectorTaskId = null;
  });

  // Show loading state then fetch historical steps
  const steps = document.getElementById('pi-steps');
  if (steps) steps.innerHTML = '<div class="pi-empty">Loading…</div>';

  const data = await fetch(API_TASK_STEPS(task.task_id)).then(r => r.json()).catch(() => ({ steps: [] }));
  _renderInspectorSteps(data.steps || []);

  // If running, listen to SSE for live steps
  if (task.status === 'running' || task.status === 'pending') {
    _inspectorSse = new EventSource(API.stream);
    _inspectorSse.onmessage = (e) => {
      if (!e.data || e.data === '{}') return;
      const ev = JSON.parse(e.data);
      if (ev.type === 'task_step' && ev.task_id === _inspectorTaskId) {
        _appendInspectorStep(ev.step);
      }
      if (ev.type === 'task_complete' && ev.task_id === _inspectorTaskId) {
        const stEl = document.getElementById('pi-status');
        if (stEl) { stEl.textContent = 'done'; stEl.className = 'pi-badge pi-badge-done'; }
        Inspector.setResult(`<div class="pi-result-text">${_escHtml(ev.result_preview || '')}</div>`);
        if (_inspectorSse) { _inspectorSse.close(); _inspectorSse = null; }
      }
      if (ev.type === 'task_failed' && ev.task_id === _inspectorTaskId) {
        const stEl = document.getElementById('pi-status');
        if (stEl) { stEl.textContent = 'failed'; stEl.className = 'pi-badge pi-badge-failed'; }
        if (_inspectorSse) { _inspectorSse.close(); _inspectorSse = null; }
      }
    };
    _inspectorSse.onerror = () => { if (_inspectorSse) { _inspectorSse.close(); _inspectorSse = null; } };
  }
}

export function closeNodeInspector() {
  Inspector.close();
  if (_inspectorSse) { _inspectorSse.close(); _inspectorSse = null; }
  _inspectorTaskId = null;
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

function _startLogPolling() {
  if (_logPollInterval) return;
  _logPollInterval = setInterval(() => refreshLogs(), 2000);
}

function _stopLogPolling() {
  if (_logPollInterval) {
    clearInterval(_logPollInterval);
    _logPollInterval = null;
  }
}

function _appendLogLine(record) {
  const container = $('plan-logs-container');
  if (!container) return;
  const empty = container.querySelector('.plan-empty-msg');
  if (empty) empty.remove();
  const lvl = record.level || 'debug';
  const ts = new Date((record.ts || Date.now() / 1000) * 1000).toLocaleTimeString();
  const msg = `[${ts}] [${lvl.toUpperCase()}] ${record.event || ''}${record.task_id ? ' task=' + record.task_id : ''}`;
  const span = document.createElement('span');
  span.className = `plan-log-line log-${lvl}`;
  span.textContent = msg;
  container.appendChild(span);
  container.appendChild(document.createTextNode('\n'));
  container.scrollTop = container.scrollHeight;
}

function _connectSSE() {
  if (_sse) { _sse.close(); _sse = null; }
  _sse = new EventSource(API.stream);
  // No polling — logs arrive via log_line SSE events (T3)

  _sse.onmessage = (e) => {
    let ev;
    if (!e.data || e.data === '{}') return;
    ev = JSON.parse(e.data);

    switch (ev.type) {
      case 'lifecycle_state':
        // Full state mapping (T9)
        switch (ev.state) {
          case 'planning':
            _thinkingShow('规划中…');
            _thinkingClear();
            _setBadge('planning');
            break;
          case 'running':
            _setBadge('running');
            _thinkingCollapse();
            break;
          case 'replanning':
            _setBadge('replanning');
            break;
          case 'done':
            _setBadge('done');
            break;
          case 'failed':
            _setBadge('failed');
            break;
          case 'aborted':
            _setBadge('aborted');
            break;
        }
        break;

      case 'plan_start':
        _planId = ev.plan_id;
        _tasks = [];
        renderDAG([]);
        _setText('plan-title', ev.title || 'Plan Mode');
        _setBadge('running');
        _thinkingCollapse();
        // Planning is done — fetch full doc with depends_on populated
        setTimeout(refreshStatus, 600);
        break;

      case 'task_start': {
        // cluster: emitted at register time (has module/profile) → status pending
        // DagOrchestrator: emitted when node STARTS RUNNING (no module) → status running
        const fromDag = !ev.module;
        const initStatus = fromDag ? 'running' : 'pending';
        if (!_tasks.find(t => t.task_id === ev.task_id)) {
          _tasks.push({
            task_id:     ev.task_id,
            status:      initStatus,
            module:      ev.module  || '',
            profile:     ev.profile || '',
            depends_on:  [],
            description: '',
          });
          renderDAG(_tasks);
        } else if (fromDag) {
          _updateNode(ev.task_id, 'running');
        }
        break;
      }

      case 'task_running':
        _updateNode(ev.task_id, 'running');
        break;

      // DagOrchestrator flat-expand: parent node split into sibling sub-nodes
      case 'task_flat_expand': {
        const parent = _tasks.find(t => t.task_id === ev.task_id);
        // Reload full DAG once sub-nodes are registered on the backend
        setTimeout(refreshStatus, 300);
        _appendLogLine({ level: 'info', event: `节点 ${ev.task_id} 平铺展开 (${ev.sub_count} 子节点)`, ts: Date.now() / 1000 });
        break;
      }

      // DagOrchestrator nested-run: parent spawns a child orchestrator
      case 'task_nested_run': {
        _updateNode(ev.task_id, 'running');
        _appendLogLine({ level: 'info', event: `节点 ${ev.task_id} 嵌套执行 (${ev.sub_count} 子节点)`, ts: Date.now() / 1000 });
        break;
      }

      case 'task_complete': {
        _updateNode(ev.task_id, 'done');
        const t = _tasks.find(x => x.task_id === ev.task_id);
        if (t) t.result = ev.result_preview;
        break;
      }

      case 'task_failed': {
        _updateNode(ev.task_id, 'failed');
        const tf = _tasks.find(x => x.task_id === ev.task_id);
        if (tf) tf.error = ev.error;
        break;
      }

      case 'task_skipped':
        _updateNode(ev.task_id, 'skipped');
        break;

      case 'task_updated':
        // Patch applied to a pending task — reload full DAG
        refreshStatus();
        break;

      case 'replan':
        // Reload full plan after replanning (task list may change)
        refreshStatus();
        break;

      case 'human_patch': {
        // T9: user-applied patch — show in log area and refresh DAG
        const note = ev.patch_ops ? `操作: ${ev.patch_ops.join(', ')}` : '';
        _appendLogLine({ level: 'info', event: `用户干预 (${ev.patches_count} patches) ${note}`, ts: Date.now() / 1000 });
        refreshStatus();
        break;
      }

      case 'human_request_received': {
        _appendLogLine({ level: 'info', event: `用户提问已发送给 Replanner: ${(ev.message || '').slice(0, 80)}`, ts: Date.now() / 1000 });
        break;
      }

      case 'node_expansion_request': {
        _appendLogLine({ level: 'info', event: `节点扩展请求: task=${ev.task_id}  reason=${(ev.reason || '').slice(0, 80)}`, ts: Date.now() / 1000 });
        break;
      }

      case 'log_line':
        // T3: real-time log push
        _appendLogLine(ev);
        break;

      case 'planner_step':
        _thinkingAppend(ev.step_index, ev.thought, ev.action, ev.observation);
        break;

      case 'replan_start':      // DagOrchestrator: replan.start
      case 'replanner_start':  // cluster: ReplannerStartEvent
        _thinkingShow(`重规划中 (${ev.trigger}, cycle ${ev.cycle})…`);
        _thinkingClear();
        break;

      case 'replanner_thinking': {
        // T4: show replanner stages in thinking panel
        const stageLabel = { building_prompt: '构建上下文…', calling_llm: '调用 LLM…', parsing: '解析决策…' }[ev.stage] || ev.stage;
        _thinkingAppendRaw(`[Replanner] ${stageLabel}`);
        break;
      }

      case 'replan_complete':     // DagOrchestrator: replan.complete (no patches_count)
      case 'replanner_complete': { // cluster: ReplannerCompleteEvent
        const patches = ev.patches_count != null ? `  patches: ${ev.patches_count}` : '';
        const summary = `决策: ${ev.decision}${patches}\n${ev.reason || ''}`;
        _thinkingAppendRaw(summary);
        setTimeout(() => _thinkingCollapse(), 3000);
        break;
      }

      case 'plan_complete':
      case 'done':
        _setBadge('done');
        if (_sse) { _sse.close(); _sse = null; }
        refreshSnapshots();
        refreshLogs();
        refreshHistory();
        break;

      case 'plan_abort':
        _setBadge('failed');
        if (_sse) { _sse.close(); _sse = null; }
        refreshHistory();
        break;

      case 'snapshot':
        refreshSnapshots();
        break;

      case 'task_step':
        // Live step streaming for the inspector (if inspector SSE is not active)
        if (!_inspectorSse && _inspectorTaskId === ev.task_id) {
          _appendInspectorStep(ev.step);
        }
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
  if (!res || !res.doc) return res?.status || 'idle';

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
  return res.status;
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

// ── History ────────────────────────────────────────────────────────────────────

async function refreshHistory() {
  const records = await fetch(API.history).then(r => r.json()).catch(() => []);
  const container = $('plan-history-list');
  if (!container) return;

  if (!records.length) {
    container.innerHTML = '<span class="plan-empty-msg">暂无历史记录。</span>';
    return;
  }

  container.innerHTML = records.map(r => {
    const ts = new Date((r.completed_at || 0) * 1000).toLocaleString();
    const statusCls = r.status === 'done' ? 'badge-done' : (r.status === 'failed' ? 'badge-failed' : 'badge-aborted');
    const qPreview = _escapeHtml((r.question || '').slice(0, 60));
    const ansPreview = _escapeHtml((r.answer || '').slice(0, 200));
    return `<div class="plan-hist-item" data-pid="${r.plan_id}">
      <div class="plan-hist-summary">
        <span class="plan-hist-ts">${ts}</span>
        <span class="plan-hist-badge ${statusCls}">${r.status}</span>
        <span class="plan-hist-q">${qPreview}</span>
        <div class="plan-hist-actions">
          <button class="hist-btn-expand" data-pid="${r.plan_id}" title="展开详情">▾</button>
          <button class="hist-btn-rerun" data-q="${_escapeHtml(r.question || '')}" title="重新运行">↺</button>
          <button class="hist-btn-del" data-pid="${r.plan_id}" title="删除">✕</button>
        </div>
      </div>
      <div class="plan-hist-detail hidden" id="plan-hist-detail-${r.plan_id}">
        <div class="hist-detail-row"><b>Task count:</b> ${r.task_count || 0}  |  <b>Elapsed:</b> ${r.elapsed_sec || '?'}s</div>
        <div class="hist-detail-row"><b>Question:</b> ${_escapeHtml(r.question || '')}</div>
        <div class="hist-detail-row"><b>Answer:</b><br>${ansPreview}</div>
      </div>
    </div>`;
  }).join('');

  container.querySelectorAll('.hist-btn-expand').forEach(btn => {
    btn.addEventListener('click', () => {
      const detail = $(`plan-hist-detail-${btn.dataset.pid}`);
      const isHidden = detail?.classList.contains('hidden');
      detail?.classList.toggle('hidden');
      btn.textContent = isHidden ? '▴' : '▾';
    });
  });

  container.querySelectorAll('.hist-btn-rerun').forEach(btn => {
    btn.addEventListener('click', () => {
      const qEl = $('plan-question');
      if (qEl) {
        qEl.value = btn.dataset.q;
        qEl.focus();
      }
    });
  });

  container.querySelectorAll('.hist-btn-del').forEach(btn => {
    btn.addEventListener('click', async () => {
      await fetch(API.historyDel(btn.dataset.pid), { method: 'DELETE' }).catch(() => null);
      refreshHistory();
    });
  });
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
  _thinkingClear();
  const thinkPanel = $('plan-thinking-panel');
  if (thinkPanel) thinkPanel.classList.add('hidden');

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

  // Connect SSE for live updates — DAG will populate via plan_start + task_start events
  _connectSSE();
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

// ── Human request (T6) ─────────────────────────────────────────────────────────

async function sendHumanRequest() {
  const inputEl = $('plan-human-input');
  if (!inputEl) return;
  const message = inputEl.value.trim();
  if (!message) return;

  inputEl.value = '';
  inputEl.disabled = true;
  const statusEl = $('plan-human-status');
  if (statusEl) statusEl.textContent = '发送中…';

  await fetch(API.humanRequest, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message }),
  }).then(r => r.json()).catch(() => null);

  if (statusEl) {
    statusEl.textContent = '已发送，等待重规划…';
    setTimeout(() => { if (statusEl) statusEl.textContent = ''; }, 5000);
  }
  inputEl.disabled = false;
}

// ── Bind events ───────────────────────────────────────────────────────────────

function _bind() {
  $('plan-btn-run')?.addEventListener('click', runPlan);
  $('plan-btn-pause')?.addEventListener('click', togglePause);
  $('plan-btn-resume')?.addEventListener('click', togglePause);
  $('plan-btn-snapshot')?.addEventListener('click', takeSnapshot);
  $('plan-btn-refresh-logs')?.addEventListener('click', () => refreshLogs());
  $('plan-btn-refresh-history')?.addEventListener('click', () => refreshHistory());
  $('plan-btn-human-send')?.addEventListener('click', sendHumanRequest);
  $('plan-human-input')?.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendHumanRequest(); }
  });
  _bindThinkingToggle();
  // pi-close is handled by Inspector.initGlobalKeyHandler() in app.js
}

// ── Public init ───────────────────────────────────────────────────────────────

let _initialized = false;

export function init() {
  if (_initialized) {
    // Re-entering the plan screen — refresh existing state
    refreshStatus().then(status => {
      // If a plan is actively running and no SSE is connected, reconnect
      if (!_sse && status === 'running') {
        _connectSSE();
      }
    });
    refreshSnapshots();
    refreshLogs();
    refreshHistory();
    return;
  }
  _initialized = true;
  _bind();
  refreshStatus();
  refreshSnapshots();
  refreshLogs();
  refreshHistory();
}

// ── Sub-panel (embedded in chat area) ─────────────────────────────────────────

let _subSse = null;           // EventSource for sub-panel
let _subTasks = {};           // task_id → { status, profile, module }
let _subPlanId = null;
let _subCollapsed = false;
let _subPanelInitialized = false;

const TASK_ICONS = {
  pending:  '○',
  running:  '⟳',
  done:     '✓',
  failed:   '✗',
  skipped:  '—',
};

function _subEl(id) { return document.getElementById(id); }

function _showSubPanel() {
  const panel = _subEl('plan-subpanel');
  if (panel) panel.classList.remove('hidden');
}

function _hideSubPanel() {
  const panel = _subEl('plan-subpanel');
  if (panel) panel.classList.add('hidden');
}

function _updateSubBadge(state) {
  const badge = _subEl('plan-subpanel-state-badge');
  if (!badge) return;
  badge.textContent = state.toUpperCase();
  badge.className = `plan-state-badge ${state}`;
}

function _updateSubProgress() {
  const el = _subEl('plan-subpanel-progress');
  if (!el) return;
  const total = Object.keys(_subTasks).length;
  const done  = Object.values(_subTasks).filter(t => ['done', 'failed', 'skipped'].includes(t.status)).length;
  el.textContent = total ? `${done}/${total}` : '';
}

function _renderTaskRow(taskId, info) {
  const status  = info.status || 'pending';
  const icon    = TASK_ICONS[status] || '○';
  const profile = info.profile ? ` (${info.profile})` : '';
  const module  = info.module  ? `[${info.module}] ` : '';
  return `<div class="plan-task-row ${status}" id="sp-task-${taskId}">
    <span class="plan-task-icon">${icon}</span>
    <span class="plan-task-id">${taskId}</span>
    <span class="plan-task-module">${module}</span>
    <span class="plan-task-profile">${profile}</span>
  </div>`;
}

function _refreshTaskList() {
  const list = _subEl('plan-task-list');
  if (!list) return;
  // Sort: running first, then pending, then done/failed/skipped
  const order = { running: 0, pending: 1, done: 2, skipped: 2, failed: 2 };
  const sorted = Object.entries(_subTasks).sort(([, a], [, b]) =>
    (order[a.status] ?? 3) - (order[b.status] ?? 3)
  );
  list.innerHTML = sorted.map(([tid, info]) => _renderTaskRow(tid, info)).join('');
}

function _updateTaskStatus(taskId, status, extra = {}) {
  if (!_subTasks[taskId]) _subTasks[taskId] = {};
  Object.assign(_subTasks[taskId], { status, ...extra });
  _refreshTaskList();
  _updateSubProgress();
}

function _connectSubSSE() {
  if (_subSse) { _subSse.close(); _subSse = null; }
  _subSse = new EventSource(API.stream);

  _subSse.onmessage = (e) => {
    if (!e.data || e.data === '{}') return;
    let ev;
    ev = JSON.parse(e.data);

    switch (ev.type) {
      case 'plan_start':
        _subPlanId = ev.plan_id;
        _subTasks = {};
        const titleEl = _subEl('plan-subpanel-title');
        if (titleEl) titleEl.textContent = `计划: ${ev.plan_id.slice(0, 8)}…  (${ev.task_count} 任务)`;
        _updateSubBadge('planning');
        _showSubPanel();
        // Link detail button to plan tab
        const detailBtn = _subEl('plan-btn-detail');
        if (detailBtn) {
          detailBtn.setAttribute('href', '#');
          detailBtn.onclick = (e) => {
            e.preventDefault();
            // Switch to plan tab if available
            const planTab = document.querySelector('[data-tab="plan"]');
            if (planTab) planTab.click();
          };
        }
        break;

      case 'lifecycle_state':
        _updateSubBadge(ev.state);
        if (ev.state === 'running') {
          const replanNotice = _subEl('plan-replan-notice');
          if (replanNotice) replanNotice.classList.add('hidden');
        }
        break;

      case 'task_start':
        _updateTaskStatus(ev.task_id, 'pending', { profile: ev.profile, module: ev.module });
        break;

      case 'task_running':
        _updateTaskStatus(ev.task_id, 'running');
        _updateSubBadge('running');
        break;

      case 'task_complete':
        _updateTaskStatus(ev.task_id, 'done');
        break;

      case 'task_failed':
        _updateTaskStatus(ev.task_id, 'failed');
        break;

      case 'task_skipped':
        _updateTaskStatus(ev.task_id, 'skipped');
        break;

      case 'replan':         // cluster: ReplanEvent
      case 'replan_start':  // DagOrchestrator: replan.start
        _updateSubBadge('replanning');
        const notice = _subEl('plan-replan-notice');
        if (notice) {
          notice.classList.remove('hidden');
          setTimeout(() => notice.classList.add('hidden'), 3000);
        }
        break;

      case 'plan_complete':
      case 'done':
        _updateSubBadge('done');
        _subEl('subpanel-btn-pause')?.classList.add('hidden');
        _subEl('subpanel-btn-resume')?.classList.add('hidden');
        if (_subSse) { _subSse.close(); _subSse = null; }
        break;

      case 'plan_abort':
        _updateSubBadge('aborted');
        _subEl('subpanel-btn-pause')?.classList.add('hidden');
        _subEl('subpanel-btn-resume')?.classList.add('hidden');
        if (_subSse) { _subSse.close(); _subSse = null; }
        break;
    }
  };

  _subSse.onerror = () => {
    if (_subSse) { _subSse.close(); _subSse = null; }
  };
}

async function _subTogglePause() {
  const res = await fetch(API.status).then(r => r.json()).catch(() => null);
  const paused = res?.doc?.metadata?.paused;
  await fetch(paused ? API.resume : API.pause, { method: 'POST' });
  const btnPause  = _subEl('subpanel-btn-pause');
  const btnResume = _subEl('subpanel-btn-resume');
  if (paused) {
    _updateSubBadge('running');
    btnPause?.classList.remove('hidden');
    btnResume?.classList.add('hidden');
  } else {
    _updateSubBadge('paused');
    btnPause?.classList.add('hidden');
    btnResume?.classList.remove('hidden');
  }
}

function _bindSubPanel() {
  const header = _subEl('plan-subpanel-header');
  const toggleBtn = _subEl('plan-subpanel-toggle');
  if (header) {
    header.addEventListener('click', (e) => {
      // Don't collapse when clicking buttons
      if (e.target.closest('.plan-subpanel-controls') || e.target.closest('.plan-subpanel-toggle')) return;
      _subCollapsed = !_subCollapsed;
      const panel = _subEl('plan-subpanel');
      panel?.classList.toggle('collapsed', _subCollapsed);
      if (toggleBtn) toggleBtn.textContent = _subCollapsed ? '▸' : '▾';
    });
  }
  if (toggleBtn) {
    toggleBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      _subCollapsed = !_subCollapsed;
      const panel = _subEl('plan-subpanel');
      panel?.classList.toggle('collapsed', _subCollapsed);
      toggleBtn.textContent = _subCollapsed ? '▸' : '▾';
    });
  }
  _subEl('subpanel-btn-pause')?.addEventListener('click', (e) => { e.stopPropagation(); _subTogglePause(); });
  _subEl('subpanel-btn-resume')?.addEventListener('click', (e) => { e.stopPropagation(); _subTogglePause(); });
}

/**
 * Initialize the embedded plan sub-panel in the chat area.
 * Called once from main.js after the workspace screen is shown.
 */
export function initSubPanel() {
  if (_subPanelInitialized) return;
  _subPanelInitialized = true;
  _bindSubPanel();
  _connectSubSSE();
}
