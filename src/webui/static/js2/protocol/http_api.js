/**
 * protocol/http_api.js — 全站唯一端点注册表。
 *
 * 规则：任何模块禁止硬编码 `/api/*`、`/ws/*` 字符串，一律 import 本表。
 * 端点与后端 routers 一一对应；修改端点时同步后端与本表。
 */

// ── WebSocket paths ──────────────────────────────────────────────────────────

export const WS_PATHS = Object.freeze({
  agentRun: '/ws/agent/run',
  speakRun: '/ws/speak/run',   // legacy：纯 Speak 直连（正常前端不使用）
  reactRun: '/ws/react/run',   // legacy
  chatRun:  '/ws/chat/run',
  tts:      '/ws/tts',
  stt:      '/ws/stt',
});

// ── HTTP paths ───────────────────────────────────────────────────────────────

const llm = Object.freeze({
  config: '/api/config',
  save:   '/api/config/save',
  init:   '/api/init',
  patch:  '/api/llm',
  status: '/api/status',
  aux:    '/api/llm/aux',
  auxSave:'/api/llm/aux/save',
});

const react = Object.freeze({
  init:    '/api/react/init',
  reinit:  '/api/react/reinit',
  status:  '/api/react/status',
  restore: '/api/react/restore',
  reset:   '/api/react/reset',
  abort:   '/api/react/abort',
  tools:   '/api/react/tools',
  toolSearch: '/api/react/tools/search',
  notify:  '/api/react/notify',
  sessions:'/api/react/sessions',
  memoryClear:   '/api/react/memory/clear',
  personaClear:  '/api/react/persona/clear',
});

const speak = Object.freeze({
  status:        '/api/speak/status',
  notify:        '/api/speak/notify',
  reset:         '/api/speak/reset',
  pageEnter:     '/api/speak/page_enter',
  createUi:      '/api/speak/create_ui',
  proactiveAck:  '/api/speak/proactive_ack',
  traceSet:      '/api/speak/session/trace',
  trace:         sid => `/api/speak/session/${encodeURIComponent(sid)}/trace`,
  debug:         sid => `/api/speak/session/${encodeURIComponent(sid)}/debug`,
});

const agent = Object.freeze({
  run: WS_PATHS.agentRun,
});

const memory = Object.freeze({
  get:         '/api/memory',
  save:        '/api/memory/save',
  consolidate: '/api/memory/consolidate',
});

const accounts = Object.freeze({
  list:  '/api/accounts',
  create:'/api/accounts',
  get:   id => `/api/accounts/${encodeURIComponent(id)}`,
});

const soul = Object.freeze({
  config:           '/api/soul/config',
  configSave:       '/api/soul/config/save',
  status:           '/api/soul/status',
  readiness:        '/api/soul/readiness',
  heartbeatLog:     '/api/soul/heartbeat-log',
  heartbeatTick:    '/api/soul/heartbeat/tick',
  persona:          '/api/soul/persona',
  personaRebuild:   '/api/soul/persona/rebuild',
  personaReload:    '/api/soul/persona/reload',
  memoryConfig:     '/api/soul/memory/config',
  memoryConfigSave: '/api/soul/memory/config/save',
  memoryInfra:      '/api/soul/memory/infra',
  memoryInfraSave:  '/api/soul/memory/infra/save',
  memorySearch:     '/api/soul/memory/search',
  lifeChronicle:    '/api/soul/life/chronicle',
  lifeHot:          '/api/soul/life/hot',
  visitorBind:      '/api/soul/visitor/bind',
});

const persona = Object.freeze({
  get:  '/api/persona',
  save: '/api/persona/save',
});

const scheduler = Object.freeze({
  tasks:          '/api/scheduler/tasks',
  task:           id => `/api/scheduler/tasks/${id}`,
  axis:           '/api/scheduler/axis',
  proactive:      '/api/scheduler/proactive',
  config:         '/api/scheduler/config',
  status:         '/api/scheduler/status',
  control:        '/api/scheduler/control',
  journal:        (date = '') => date ? `/api/scheduler/journal?date=${date}` : '/api/scheduler/journal',
  heartbeatLog:   (n = 50) => `/api/scheduler/heartbeat-log?n=${n}`,
  webhookTrigger: '/api/scheduler/webhook/heartbeat',
});

const knowledge = Object.freeze({
  docs:    '/api/kb/documents',
  doc:     id => `/api/kb/documents/${id}`,
  search:  '/api/kb/search',
  ingest:  '/api/kb/ingest',
  repair:  '/api/kb/repair',
  fixIndex:'/api/kb/fix-index',
});

const infraVllm = Object.freeze({
  config: '/api/vllm/config',
  save:   '/api/vllm/config/save',
  start:  '/api/vllm/start',
  stop:   '/api/vllm/stop',
  status: '/api/vllm/status',
  logs:   '/api/vllm/logs',
});

const infraSandbox = Object.freeze({
  config: '/api/sandbox/config',
  save:   '/api/sandbox/config/save',
});

const infraBot = Object.freeze({
  config:   '/api/bot/config',
  save:     '/api/bot/config/save',
  status:   '/api/bot/status',
  sessions: '/api/bot/sessions',
  start:    '/api/bot/start',
  stop:     '/api/bot/stop',
  publicIp: '/api/bot/public-ip',
});

const infraNotify = Object.freeze({
  barkConfig: '/api/notify/bark/config',
  barkTest:   '/api/notify/bark/test',
  ntfyConfig: '/api/notify/ntfy/config',
  ntfyTest:   '/api/notify/ntfy/test',
});

const infraServices = Object.freeze({
  status: '/api/services/status',
  one:    n => `/api/services/${n}/status`,
  logs:   n => `/api/services/${n}/logs`,
  start:  n => `/api/services/${n}/start`,
  stop:   n => `/api/services/${n}/stop`,
});

const infraEmbedding = Object.freeze({
  config: '/api/embedding/config',
  save:   '/api/embedding/config/save',
});

const voiceTts = Object.freeze({
  config:    '/api/tts/config',
  save:      '/api/tts/config/save',
  synth:     '/api/tts/synthesize',
  download:  '/api/tts/download',
  ws:        WS_PATHS.tts,
});

const voiceStt = Object.freeze({
  config:     '/api/stt/config',
  save:       '/api/stt/config/save',
  transcribe: '/api/stt/transcribe',
  download:   '/api/stt/download',
  ws:         WS_PATHS.stt,
});

const history = Object.freeze({
  list:  '/api/history',
  item:  id => `/api/history/${encodeURIComponent(id)}`,
  clear: '/api/history',
});

const plan = Object.freeze({
  run:          '/api/plan/run',
  status:       '/api/plan/status',
  stream:       '/api/plan/stream',          // SSE
  snapshots:    '/api/plan/snapshots',
  rollback:     '/api/plan/rollback',
  logs:         '/api/plan/logs',
  pause:        '/api/plan/pause',
  resume:       '/api/plan/resume',
  taskSteps:    tid => `/api/plan/task/${tid}/steps`,
  skip:         tid => `/api/plan/skip/${tid}`,
  taskPatch:    tid => `/api/plan/tasks/${tid}`,
  humanRequest: '/api/plan/human-request',
  history:      '/api/plan/history',
  historyDel:   pid => `/api/plan/history/${pid}`,
});

const benchmark = Object.freeze({
  scenarios:      '/api/benchmark/scenarios',
  scenarioDetail: name => `/api/benchmark/scenarios/${encodeURIComponent(name)}`,
  report:         '/api/benchmark/report',
  historyList:    '/api/benchmark/history',
  run:            '/api/benchmark/run',
  runSuite:       '/api/benchmark/run-suite',
  trend:          (metric, scenario) => {
    const q = scenario ? `?metric=${metric}&scenario=${encodeURIComponent(scenario)}` : `?metric=${metric}`;
    return `/api/benchmark/metrics/trend${q}`;
  },
  obsStats:       '/api/benchmark/obs/stats',
  obsSessions:    '/api/benchmark/obs/sessions',
  obsSession:     sid => `/api/benchmark/obs/session/${encodeURIComponent(sid)}`,
});

const probe = Object.freeze({
  runs:  (limit = 100, tag = '', name = '') => {
    const q = new URLSearchParams();
    if (limit !== 100) q.set('limit', limit);
    if (tag) q.set('tag', tag);
    if (name) q.set('name', name);
    const qs = q.toString();
    return `/api/probe/runs${qs ? '?' + qs : ''}`;
  },
  run:   id => `/api/probe/runs/${encodeURIComponent(id)}`,
  clear: () => '/api/probe/runs',
  tags:  () => '/api/probe/tags',
});

/** 兼容旧 react 命名域内的杂项读取端点。 */
const misc = Object.freeze({
  timeline: '/api/timeline',
});

export const API = Object.freeze({
  llm, react, speak, agent, memory, accounts, soul, persona, scheduler,
  knowledge, voice: { tts: voiceTts, stt: voiceStt }, history, plan,
  benchmark, probe, misc,
  vllm: infraVllm,
  sandbox: infraSandbox,
  bot: infraBot,
  notify: infraNotify,
  services: infraServices,
  embedding: infraEmbedding,
});

/** 旧名兼容别名 —— 迁移期保留，切流完成后移除。 */
export const PATHS = {
  ...API,
  voiceTts, voiceStt, infraVllm, infraSandbox, infraBot, infraNotify, infraServices,
};
