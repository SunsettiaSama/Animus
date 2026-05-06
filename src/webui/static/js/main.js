/**
 * main.js — Application entry point.
 *
 * Responsibilities:
 *   1. Boot sequence: load status, render workstation, bind all DOM events.
 *   2. Lifecycle management: translate react:state events into UI changes.
 *   3. Toast notification: listen to react:toast and show the toast element.
 *   4. Send / abort button wiring.
 *   5. History persistence after each turn.
 *
 * Modules NEVER touch the DOM directly for shared UI elements.
 * They emit callbacks or CustomEvents which are handled here.
 */

import { S, setState, set, isBusy }      from './state.js';
import { http, PATHS, pollUntilReady }   from './api.js';
import * as render                        from './render.js';
import * as history                       from './history.js';
import * as streaming                     from './streaming.js';
import * as settings                      from './settings.js';
import * as llmMod                        from './modules/llm.js';
import * as reactMod                      from './modules/react.js';
import * as memoryMod                     from './modules/memory.js';
import * as personaMod                    from './modules/persona.js';
import * as schedulerMod                  from './modules/scheduler.js';
import * as voiceMod                      from './modules/voice.js';
import * as infraMod                      from './modules/infra.js';
import * as benchMod                      from './modules/benchmark.js';
import * as botMod                        from './modules/bot.js';
import { renderRecentLanding }            from './history.js';

// ── Module callback wiring ────────────────────────────────────────────────────

const _toast = text => _showToast(text);

[llmMod, reactMod, memoryMod, personaMod, schedulerMod, voiceMod, infraMod, benchMod, botMod].forEach(m => {
  if (m.setCallbacks) m.setCallbacks({ onToast: _toast });
});
reactMod.setCallbacks({
  onToast:       _toast,
  onReady:       () => _updateReactBadge(),
  onError:       msg => setState('error', { message: msg }),
  onStatusUpdate:() => {},
});
history.setCallbacks({
  onToast: _toast,
  onLoad:  (msgs) => { _rebuildFromHistory(msgs); },
});

// ── Toast ─────────────────────────────────────────────────────────────────────

let _toastTimer = null;
function _showToast(text) {
  const el = document.getElementById('toast');
  if (!el) return;
  el.textContent = text;
  el.classList.add('show');
  clearTimeout(_toastTimer);
  _toastTimer = setTimeout(() => el.classList.remove('show'), 2500);
}

window.addEventListener('react:toast', e => _showToast(e.detail));

// ── Lifecycle UI sync ─────────────────────────────────────────────────────────

window.addEventListener('react:state', e => {
  const { to } = e.detail;
  const sendBtn = document.getElementById('btn-send');
  const inputEl = document.getElementById('msg-input');

  if (to === 'streaming' || to === 'aborting' || to === 'initializing') {
    if (sendBtn) { sendBtn.textContent = '⊘'; sendBtn.title = 'Abort'; }
    if (inputEl) inputEl.disabled = true;
  } else {
    if (sendBtn) { sendBtn.textContent = '↑'; sendBtn.title = 'Send'; }
    if (inputEl) inputEl.disabled = false;
  }
});

// ── Screen navigation ─────────────────────────────────────────────────────────

function _showScreen(id) {
  ['s-landing', 's-workspace', 's-plan', 's-benchmark', 's-scheduler'].forEach(s => {
    document.getElementById(s)?.classList.toggle('hidden', s !== id);
  });
}

function goHome() {
  _showScreen('s-landing');
  loadWorkstation();
}

function goWorkspace() {
  _showScreen('s-workspace');
  history.renderSidebar();
}

function goPlan() {
  _showScreen('s-plan');
  import('/static/js/modules/plan.js').then(m => m.init());
}

function goBenchmark() {
  _showScreen('s-benchmark');
  benchMod.init();
}

function goScheduler() {
  _showScreen('s-scheduler');
  schedulerMod.init();
}

// ── New conversation ───────────────────────────────────────────────────────────

function startNew() {
  streaming.abortCurrent();   // D2: cancel any in-progress stream before resetting UI
  set('convId', null);
  set('convTitle', 'New Conversation');
  history.clearMessages();
  render.clearMsgs();
  render.showEmptyState();
  document.getElementById('tb-title')?.textContent && (document.getElementById('tb-title').textContent = 'New Conversation');
  _updateReactBadge();
  goWorkspace();
}

// ── Topbar badge ──────────────────────────────────────────────────────────────

function _updateReactBadge() {
  const el = document.getElementById('tb-react-status');
  if (!el) return;
  const ready = S.reactReady;
  el.textContent = ready ? '⚡ Ready' : '⚡ Not ready';
  el.style.color = ready ? 'var(--accent)' : 'var(--text3)';
}

// ── Send / abort ──────────────────────────────────────────────────────────────

async function handleSend() {
  if (S.lifecycle === 'streaming' || S.lifecycle === 'aborting') {
    streaming.abortCurrent();
    setState('aborting');
    return;
  }
  const inputEl  = document.getElementById('msg-input');
  const question = inputEl?.value.trim();
  if (!question) return;
  if (inputEl) inputEl.value = '';

  goWorkspace();
  render.appendUserMsg(question);
  history.pushMessage({ role: 'user', content: question });

  await _runReact(question);
}

// ── ReAct streaming ───────────────────────────────────────────────────────────

async function _runReact(question) {
  if (!S.reactReady) { _showToast('ReAct not initialized'); return; }

  const genId  = crypto.randomUUID();
  set('genId', genId);
  setState('streaming');

  const ctrl          = render.appendReactMsg();
  let   _stepI        = -1;
  const _stepHistory  = [];   // collect completed steps for persistence

  const session = new streaming.ReactSession(question, genId, {
    onPromptPreview: msgs => ctrl.showPrompt(msgs),
    onStepStart: i  => { _stepI = i; ctrl.showActivity(`Step ${i + 1}…`); },
    onChunk:    (i, chunk) => ctrl.appendChunk(i, chunk),
    onStep:      step  => { ctrl.addStep(step); _stepHistory.push(step); },
    onRetry:    (i, reason) => _showToast(`Retry ${i}: ${reason}`),
    onApprovalRequest: (reqId, tool, args) => _promptApproval(session, reqId, tool, args),
    onSubStart:  (action, instr) => ctrl.openSubAgent(action, instr),
    onSubChunk:  (i, chunk)      => ctrl.addSubChunk(i, chunk),
    onSubStep:   step            => ctrl.addSubStep(step),
    onSubFinish: answer          => ctrl.closeSubAgent(answer, false),
    onSubError:  error           => ctrl.closeSubAgent(error, true),
    onMaxSteps: n => _showToast(`⚠ 已达最大步数限制（${n} 步）`),
    onFinish:   (answer, aborted) => {
      ctrl.finalize(answer, aborted);
      if (!aborted && answer) {
        history.pushMessage({ role: 'assistant', content: answer, steps: _stepHistory });
        history.saveConversation();
        _updateTitle(answer);
      }
      streaming.clearCurrent();
      setState('idle');
    },
    onError: e => {
      _showToast('ReAct error: ' + e.message);
      ctrl.finalize('', true);
      streaming.clearCurrent();
      setState('idle');
    },
  });
  streaming.startSession(session);
  session.run().catch(e => {
    _showToast('Connection error: ' + e.message);
    streaming.clearCurrent();
    setState('idle');
  });
}

function _promptApproval(session, reqId, tool, args) {
  const ok = confirm(`Allow tool "${tool}"?\n\n${JSON.stringify(args, null, 2)}`);
  session.respond(reqId, ok);
}

// ── TTS play ─────────────────────────────────────────────────────────────────

document.addEventListener('click', async e => {
  const btn = e.target.closest('.msg-tts-btn');
  if (!btn) return;
  const text = btn.dataset.text;
  if (!text) return;
  if (voiceMod.isSpeaking()) {
    voiceMod.stopSpeaking();
    btn.classList.remove('playing');
    return;
  }
  btn.classList.add('playing');
  await voiceMod.speak(text);
  btn.classList.remove('playing');
});

// ── Mic recording ─────────────────────────────────────────────────────────────

async function handleMicClick() {
  const btn = document.getElementById('btn-mic');
  if (voiceMod.isRecording()) {
    btn?.classList.remove('recording');
    const text = await voiceMod.stopRecordingAndTranscribe();
    if (text) {
      const inp = document.getElementById('msg-input');
      if (inp) inp.value = (inp.value + ' ' + text).trim();
    }
  } else {
    await voiceMod.startRecording().catch(e => _showToast('Mic error: ' + e.message));
    btn?.classList.add('recording');
  }
}

// ── History rebuild ───────────────────────────────────────────────────────────

function _rebuildFromHistory(messages) {
  render.clearMsgs();
  messages.forEach(m => {
    if (m.role === 'user') {
      render.appendUserMsg(m.content);
    } else if (m.role === 'assistant') {
      if (m.steps && m.steps.length > 0) {
        // ReAct message — restore step cards then show final answer
        const ctrl = render.appendReactMsg();
        m.steps.forEach(step => ctrl.addStep(step));
        ctrl.finalize(m.content, false);
      } else {
        // Chat / old ReAct without step data
        const ctrl = render.appendAssistantMsg();
        ctrl.append(m.content);
        ctrl.finalize(false);
      }
    }
  });
  render.scrollBottom();
  goWorkspace();
}

// ── Title update ──────────────────────────────────────────────────────────────

function _updateTitle(answerOrQuestion) {
  if (S.convTitle && S.convTitle !== 'New Conversation') return;
  const msgs  = history.getMessages();
  const first = msgs.find(m => m.role === 'user');
  if (!first) return;
  const title = first.content.slice(0, 48) + (first.content.length > 48 ? '…' : '');
  set('convTitle', title);
  const tbEl = document.getElementById('tb-title');
  if (tbEl) tbEl.textContent = title;
}

// ── Workstation load ──────────────────────────────────────────────────────────

async function loadWorkstation() {
  await Promise.allSettled([
    llmMod.updateWorkstationCard(),
    reactMod.updateWorkstationCard(),
    memoryMod.updateWorkstationCard(),
    personaMod.updateWorkstationCard(),
    voiceMod.updateWorkstationCard(),
    schedulerMod.updateWorkstationCard(),
    benchMod.updateWorkstationCard(),
    botMod.updateWorkstationCard(),
    infraMod.updateServicesRow(),
    renderRecentLanding(document.getElementById('landing-recent')),
  ]);
}

// ── Scheduler form ────────────────────────────────────────────────────────────

function toggleSchedulerForm() {
  const el = document.getElementById('sched-form-wrap');
  if (!el) return;
  el.style.display = el.style.display === 'none' ? 'block' : 'none';
}

function onSchedTriggerChange() {
  const t = document.querySelector('input[name="sched-trigger-radio"]:checked')?.value ?? 'once';
  document.getElementById('sched-once-fields').style.display     = t === 'once'     ? '' : 'none';
  document.getElementById('sched-interval-fields').style.display = t === 'interval' ? '' : 'none';
}

async function createSchedulerTask() {
  const $ = id => document.getElementById(id);
  const triggerType = document.querySelector('input[name="sched-trigger-radio"]:checked')?.value ?? 'once';
  const payload = {
    name:             $('sched-name')?.value ?? '',
    instruction:      $('sched-instruction')?.value ?? '',
    trigger_type:     triggerType,
    profile:          $('sched-profile')?.value ?? 'minimal',
    at:               triggerType === 'once'     ? $('sched-at')?.value       : undefined,
    interval_seconds: triggerType === 'interval' ? parseInt($('sched-interval')?.value) : undefined,
  };
  const msgEl = $('sched-form-msg');
  if (msgEl) msgEl.textContent = 'Creating…';
  await schedulerMod.createTask(payload).catch(e => {
    if (msgEl) msgEl.textContent = e.message;
    return null;
  });
  if (msgEl) msgEl.textContent = '';
  toggleSchedulerForm();
  schedulerMod.renderTaskTable();
}

// ── KB panel ──────────────────────────────────────────────────────────────────

import * as knowledgeMod from './modules/knowledge.js';
knowledgeMod.setCallbacks({ onToast: _toast });

function openKBPanel() {
  const panel = document.getElementById('kb-panel');
  if (!panel) return;
  panel.classList.toggle('hidden');
  if (!panel.classList.contains('hidden')) {
    knowledgeMod.renderPanel(document.getElementById('kb-docs-list'));
  }
}

// ── Download model helper ─────────────────────────────────────────────────────

async function doDownloadModel(type) {
  const url    = type === 'tts' ? PATHS.voice.tts.download : PATHS.voice.stt.download;
  const msgEl  = document.getElementById(`${type}-dl-msg`);
  if (msgEl) msgEl.textContent = 'Starting download…';
  const src    = new EventSource(url);
  src.onmessage = e => {
    const d = JSON.parse(e.data);
    if (msgEl) msgEl.textContent = d.status === 'done'
      ? `Done: ${d.path}`
      : `Downloading ${d.repo ?? ''}…`;
    if (d.status === 'done' || d.status === 'error') src.close();
  };
  src.onerror = () => {
    if (msgEl) msgEl.textContent = 'Download failed';
    src.close();
  };
}

// ── DOM event bindings ────────────────────────────────────────────────────────

function _bind() {
  const on = (id, ev, fn) => document.getElementById(id)?.addEventListener(ev, fn);

  // Send / abort
  on('btn-send', 'click', handleSend);
  document.getElementById('msg-input')?.addEventListener('keydown', e => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleSend(); }
  });

  // Auto-resize textarea
  document.getElementById('msg-input')?.addEventListener('input', e => {
    e.target.style.height = 'auto';
    e.target.style.height = Math.min(e.target.scrollHeight, 120) + 'px';
  });

  // Mic
  on('btn-mic', 'click', handleMicClick);

  // Settings
  on('overlay',              'click', e => settings.handleOverlayClick(e));
  on('btn-settings-top',    'click', () => settings.open());
  on('btn-settings-sidebar','click', () => settings.open());
  on('btn-settings-topbar', 'click', () => settings.open());
  on('btn-modal-save',      'click', () => settings.saveCurrentTab());
  on('btn-modal-close',     'click', () => settings.close());
  on('btn-modal-close-x',   'click', () => settings.close());

  // Navigation
  on('btn-go-home',    'click', goHome);
  on('plan-btn-home',  'click', goHome);
  on('btn-new-conv',   'click', startNew);
  on('btn-clear-hist', 'click', () => {
    if (confirm('Clear ALL history?')) {
      history.clearAllHistory().then(() => _showToast('History cleared'));
    }
  });
  on('btn-open-kb',   'click', openKBPanel);
  on('btn-refresh-ws','click', loadWorkstation);

  // Landing quick-start cards
  document.querySelector('[data-action="start-react"]')?.addEventListener('click', () => startNew());
  document.querySelector('[data-action="start-plan"]')?.addEventListener('click', () => goPlan());
  document.querySelector('[data-action="start-benchmark"]')?.addEventListener('click', () => goBenchmark());
  document.querySelector('[data-action="start-scheduler"]')?.addEventListener('click', () => goScheduler());

  // Benchmark screen
  on('bench-btn-home',    'click', goHome);
  on('bench-btn-run-all', 'click', () => benchMod.runAll());
  on('bench-btn-run-sel', 'click', () => benchMod.runSelected());
  on('bench-btn-clear',   'click', () => benchMod.clearReport());

  // Scheduler screen
  on('sched-btn-home',    'click', goHome);
  on('btn-sched-refresh', 'click', () => schedulerMod.init());

  // Workstation module cards — ⚙ button or double-click opens settings tab
  document.querySelectorAll('.module-card[data-tab]').forEach(card => {
    const tab = card.dataset.tab;
    card.addEventListener('dblclick', () => settings.open(tab));
    card.querySelector('.mc-settings-btn')?.addEventListener('click', e => {
      e.stopPropagation();
      settings.open(tab);
    });
  });

  // Settings nav tab buttons
  ['model','memory','persona','voice','vllm','sandbox','bot'].forEach(tab => {
    document.getElementById(`snav-btn-${tab}`)?.addEventListener('click', () => settings.setTab(tab));
  });

  // Settings inline toggles
  on('s-tools-enabled',   'change', settings.onToggleTools);
  on('s-tts-provider',    'change', settings.onTTSProviderChange);
  on('s-stt-provider',    'change', settings.onSTTProviderChange);

  // Scheduler form
  on('btn-sched-add',    'click', toggleSchedulerForm);
  on('btn-sched-create', 'click', createSchedulerTask);
  on('btn-sched-cancel', 'click', toggleSchedulerForm);
  document.querySelectorAll('input[name="sched-trigger-radio"]').forEach(r => {
    r.addEventListener('change', onSchedTriggerChange);
  });

  // Memory consolidate / clear
  on('btn-consolidate',    'click', settings.doConsolidate);
  on('btn-clear-memory',   'click', settings.doClearMemory);
  on('btn-clear-persona',  'click', settings.doClearPersona);

  // vLLM quick start/stop/save buttons
  on('btn-vllm-start', 'click', () => infraMod.vllm.start().catch(e => _showToast(e.message)));
  on('btn-vllm-stop',  'click', () => infraMod.vllm.stop());
  on('btn-vllm-save',  'click', () => settings.saveVLLMTab());
  on('btn-sandbox-save','click',() => settings.saveSandboxTab());

  // Bot service buttons
  on('btn-bot-save',   'click', async () => {
    const msgEl = document.getElementById('bot-cfg-msg');
    if (msgEl) msgEl.textContent = 'Saving…';
    await settings.saveBotTab().catch(e => { if (msgEl) msgEl.textContent = e.message; return; });
    if (msgEl) { msgEl.textContent = 'Saved ✓'; setTimeout(() => { msgEl.textContent = ''; }, 2000); }
  });
  on('btn-bot-start',  'click', () => infraMod.bot.start().catch(e => _showToast(e.message)));
  on('btn-bot-stop',   'click', () => infraMod.bot.stop().catch(e => _showToast(e.message)));
  on('btn-bot-refresh','click', () => settings.setTab('bot'));

  // Model download
  document.querySelector('[data-action="download-tts"]')?.addEventListener('click', () => doDownloadModel('tts'));
  document.querySelector('[data-action="download-stt"]')?.addEventListener('click', () => doDownloadModel('stt'));

  // Sidebar history items — wired dynamically in history.js
  // Sidebar logo click
  on('sidebar-logo-btn', 'click', goHome);

  // Mode-badge click (in topbar) re-opens settings → model tab
  document.getElementById('tb-mode-badge')?.addEventListener('click', () => settings.open('model'));
}

// ── Boot ──────────────────────────────────────────────────────────────────────

async function boot() {
  _bind();

  // Determine initial state from backend
  const status = await llmMod.fetchStatus().catch(() => null);
  if (status?.initialized) {
    set('llmModel', status.model);
  }

  const reactStatus = await reactMod.fetchStatus().catch(() => null);
  if (reactStatus?.status === 'ready') {
    set('reactReady', true);
  } else if (reactStatus?.status === 'initializing') {
    _showToast('ReAct initializing…');
    pollUntilReady()
      .then(() => {
        set('reactReady', true);
        _updateReactBadge();
        _showToast('ReAct ready');
      })
      .catch(() => {});
  }

  _updateReactBadge();
  loadWorkstation();
}

document.addEventListener('DOMContentLoaded', boot);
