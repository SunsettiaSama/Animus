/**
 * api.js — Centralised HTTP / WebSocket gateway.
 *
 * All modules must import PATHS from here and NEVER hard-code endpoint strings.
 */

const _JSON_H  = { 'Content-Type': 'application/json' };
const _WS_BASE = `${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}`;

// ── Endpoint registry ─────────────────────────────────────────────────────────

export const PATHS = {
  llm: {
    config: '/api/config',
    save:   '/api/config/save',
    init:   '/api/init',
    patch:  '/api/llm',
    status: '/api/status',
  },
  react: {
    init:    '/api/react/init',
    reinit:  '/api/react/reinit',
    status:  '/api/react/status',
    run:     '/ws/react/run',
    restore: '/api/react/restore',
    reset:   '/api/react/reset',
    abort:   '/api/react/abort',
    tools:   '/api/react/tools',
    notify:  '/api/react/notify',
  },
  memory: {
    get:         '/api/memory',
    save:        '/api/memory/save',
    consolidate: '/api/memory/consolidate',
    clearMem:    '/api/react/memory/clear',
    clearPersona:'/api/react/persona/clear',
  },
  persona:   { get: '/api/persona', save: '/api/persona/save' },
  scheduler: {
    tasks:          '/api/scheduler/tasks',
    task:           id => `/api/scheduler/tasks/${id}`,
    axis:           '/api/scheduler/axis',
    proactive:      '/api/scheduler/proactive',
    config:         '/api/scheduler/config',
    status:         '/api/scheduler/status',
    control:        '/api/scheduler/control',
    journal:        '/api/scheduler/journal',
    heartbeatLog:   (n = 50) => `/api/scheduler/heartbeat-log?n=${n}`,
    webhookTrigger: '/api/scheduler/webhook/heartbeat',
  },
  knowledge: {
    docs:    '/api/kb/documents',
    doc:     id => `/api/kb/documents/${id}`,
    search:  '/api/kb/search',
    ingest:  '/api/kb/ingest',
    repair:  '/api/kb/fix-index',
  },
  infra: {
    vllm: {
      config: '/api/vllm/config',
      save:   '/api/vllm/config/save',
      start:  '/api/vllm/start',
      stop:   '/api/vllm/stop',
      status: '/api/vllm/status',
      logs:   '/api/vllm/logs',
    },
    sandbox: { config: '/api/sandbox/config', save: '/api/sandbox/config/save' },
    bot: {
      config:   '/api/bot/config',
      save:     '/api/bot/config/save',
      status:   '/api/bot/status',
      sessions: '/api/bot/sessions',
      start:    '/api/bot/start',
      stop:     '/api/bot/stop',
      publicIp: '/api/bot/public-ip',
    },
    services:{
      status:  '/api/services/status',
      one:     n => `/api/services/${n}/status`,
      start:   n => `/api/services/${n}/start`,
      stop:    n => `/api/services/${n}/stop`,
      logs:    n => `/api/services/${n}/logs`,
    },
  },
  voice: {
    tts: {
      config:    '/api/tts/config',
      save:      '/api/tts/config/save',
      synth:     '/api/tts/synthesize',
      download:  '/api/tts/download',
      ws:        '/ws/tts',
    },
    stt: {
      config:    '/api/stt/config',
      save:      '/api/stt/config/save',
      transcribe:'/api/stt/transcribe',
      download:  '/api/stt/download',
      ws:        '/ws/stt',
    },
  },
  history: {
    list: '/api/history',
    item: id => `/api/history/${id}`,
  },
  timeline: '/api/timeline',
  probe: {
    runs:   (limit = 100, tag = '', name = '') => {
      const q = new URLSearchParams();
      if (limit !== 100) q.set('limit', limit);
      if (tag)           q.set('tag', tag);
      if (name)          q.set('name', name);
      const qs = q.toString();
      return `/api/probe/runs${qs ? '?' + qs : ''}`;
    },
    run:    id   => `/api/probe/runs/${encodeURIComponent(id)}`,
    clear:  ()   => '/api/probe/runs',
    tags:   ()   => '/api/probe/tags',
  },
  benchmark: {
    scenarios:      '/api/benchmark/scenarios',
    scenarioDetail: name => `/api/benchmark/scenarios/${encodeURIComponent(name)}`,
    report:         '/api/benchmark/report',
    history:        '/api/benchmark/history',
    run:            '/api/benchmark/run',
    runSuite:       '/api/benchmark/run-suite',
    trend:          (metric, scenario) => {
      const q = scenario ? `?metric=${metric}&scenario=${encodeURIComponent(scenario)}` : `?metric=${metric}`;
      return `/api/benchmark/metrics/trend${q}`;
    },
    clear:          '/api/benchmark/report',
  },
};

// ── HTTP utilities ────────────────────────────────────────────────────────────

async function _checkJson(r) {
  if (!r.ok) {
    let msg = `HTTP ${r.status}`;
    try { const d = await r.json(); msg = d.error || d.detail || msg; } catch {}
    throw new Error(msg);
  }
  return r.json();
}

export const http = {
  get:   path       => fetch(path).then(_checkJson),
  post:  (path, b)  => fetch(path, { method: 'POST',   headers: _JSON_H, body: JSON.stringify(b) }).then(_checkJson),
  patch: (path, b)  => fetch(path, { method: 'PATCH',  headers: _JSON_H, body: JSON.stringify(b) }).then(_checkJson),
  del:   path       => fetch(path, { method: 'DELETE' }).then(_checkJson),

  /** POST with FormData (file upload) — no Content-Type header. */
  upload: (path, formData) => fetch(path, { method: 'POST', body: formData }).then(_checkJson),
};

// ── WebSocket factory ─────────────────────────────────────────────────────────

export function wsFactory(path) {
  return new WebSocket(`${_WS_BASE}${path}`);
}

// ── Poll helper ───────────────────────────────────────────────────────────────

/**
 * Poll GET /api/react/status until status === 'ready' or 'error'.
 * Rejects on timeout or backend error.
 */
export async function pollUntilReady(intervalMs = 500, timeoutMs = 120_000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const { status, detail } = await http.get(PATHS.react.status);
    if (status === 'ready') return;
    if (status === 'error') throw new Error(detail ?? 'ReAct init failed');
    if (status === 'not_initialized') throw new Error('ReAct not initialized — configure LLM first');
    await new Promise(r => setTimeout(r, intervalMs));
  }
  throw new Error('ReAct init timed out');
}
