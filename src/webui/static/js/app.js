/**
 * app.js — Application bootstrap (replaces main.js).
 *
 * Responsibilities (only):
 *   1. Import and wire all modules.
 *   2. Register module callbacks via eventBus.
 *   3. Bind all DOM events.
 *   4. Run the boot sequence.
 *
 * No business logic lives here. Each concern belongs to its module.
 */

import { S, set }                   from './state.js';
import { http, PATHS, pollUntilReady } from './api.js';
import * as settings                from './settings.js';
import { getChannelId, requireChannelId } from './channel.js';
import { ensureAccountReady, bindAccountGate } from './screens/account_gate.js';

// Feature modules
import * as llmMod                  from './modules/llm.js';
import * as reactMod                from './modules/react.js';
import * as speakMod                from './modules/speak.js';
import * as soulMod                 from './modules/soul.js';
import * as memoryMod               from './modules/memory.js';
import * as personaMod              from './modules/persona.js';
import * as schedulerMod            from './modules/scheduler.js';
import * as voiceMod                from './modules/voice.js';
import * as infraMod                from './modules/infra.js';
import * as benchMod                from './modules/benchmark.js';
import * as botMod                  from './modules/bot.js';
import * as knowledgeMod            from './modules/knowledge.js';
import * as notifyMod               from './modules/notify.js';

// Infrastructure
import { bus }                      from './eventBus.js';
import { navigate, goHome, goWorkspace,
         goPlan, goBenchmark, goScheduler } from './router.js';
import { Inspector }                from './components/Inspector.js';

// Screen modules
import { initToast, showToast }     from './shared/toast.js';
import { loadWorkstation, registerModules as regLanding,
         bindLanding }              from './screens/landing.js';
import * as history                     from './history.js';
import { startNew, handleSend, handleMicClick,
         updateReactBadge,
         initTTSHandler, initLifecycleListeners,
         initSidebar, initSpeakDeliverySync, openKBPanel,
         rebuildFromHistory, prepareConversationSwitch,
         openProactiveSession,
         registerModules as regWorkspace }
                                    from './screens/workspace.js';
import { setAgentAvatar }           from './render.js';
import { bindSpeakDeliverySetting } from './speak_delivery.js';

// ── Module dependency injection ───────────────────────────────────────────────

regLanding({ llmMod, reactMod, memoryMod, personaMod,
             voiceMod, schedulerMod, benchMod, botMod, infraMod });
regWorkspace({ voiceMod, knowledgeMod });

history.setCallbacks({
  onLoad: msgs => rebuildFromHistory(msgs),
  onToast: text => bus.emit('toast', text),
  onBeforeSwitch: () => prepareConversationSwitch(),
});

// ── Module callbacks (all toast → bus) ───────────────────────────────────────

const _toast = text => bus.emit('toast', text);

[llmMod, reactMod, speakMod, soulMod, memoryMod, personaMod, schedulerMod,
 voiceMod, infraMod, benchMod, botMod, knowledgeMod].forEach(m => {
  m.setCallbacks?.({ onToast: _toast });
});

reactMod.setCallbacks({
  onToast:        _toast,
  onReady:        () => {
    soulMod.fetchReadiness().then(() => updateReactBadge()).catch(() => {});
    speakMod.fetchStatus().then(() => updateReactBadge()).catch(() => {});
  },
  onError:        msg => { showToast(msg); },
  onStatusUpdate: () => {},
});

speakMod.setCallbacks({
  onToast:        _toast,
  onReady:        () => updateReactBadge(),
  onStatusUpdate: () => updateReactBadge(),
});

soulMod.setCallbacks({
  onToast:        _toast,
  onStatusUpdate: () => updateReactBadge(),
});

personaMod.setCallbacks({
  onToast:        _toast,
  onPersonaLoad:  data => {
    const name = data?.profile?.name;
    if (name) setAgentAvatar(name.charAt(0));
  },
});

notifyMod.setCallbacks({
  onShow: _toast,
  onHide: () => {},
  onAgentProactiveSession: payload => {
    openProactiveSession(payload).catch(e => showToast(String(e.message || e)));
  },
});
notifyMod.connect();

// ── Scheduler form helpers ────────────────────────────────────────────────────

function toggleSchedulerForm() {
  const overlay = document.getElementById('sched-nt-overlay');
  if (!overlay) return;
  overlay.classList.toggle('hidden');
  if (!overlay.classList.contains('hidden')) {
    document.getElementById('sched-name')?.focus();
  }
}

function onSchedTriggerChange() {
  const t = document.querySelector('input[name="sched-trigger-radio"]:checked')?.value ?? 'once';
  document.getElementById('sched-once-fields').style.display     = t === 'once'     ? '' : 'none';
  document.getElementById('sched-interval-fields').style.display = t === 'interval' ? '' : 'none';
}

async function createSchedulerTask() {
  const $ = id => document.getElementById(id);
  const triggerType = document.querySelector('input[name="sched-trigger-radio"]:checked')?.value ?? 'once';
  const delivery      = $('sched-delivery')?.value      ?? 'push';
  const replyChannel  = $('sched-reply-channel')?.value ?? '';
  const reply_target  = replyChannel ? { type: replyChannel } : null;
  const payload = {
    name:             $('sched-name')?.value ?? '',
    instruction:      $('sched-instruction')?.value ?? '',
    trigger_type:     triggerType,
    profile:          $('sched-profile')?.value ?? 'minimal',
    delivery,
    reply_target,
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

// ── Download model helper ─────────────────────────────────────────────────────

function doDownloadModel(type) {
  const url   = type === 'tts' ? PATHS.voice.tts.download : PATHS.voice.stt.download;
  const msgEl = document.getElementById(`${type}-dl-msg`);
  if (msgEl) msgEl.textContent = 'Starting download…';
  const src = new EventSource(url);
  src.onmessage = e => {
    const d = JSON.parse(e.data);
    if (msgEl) msgEl.textContent = d.status === 'done' ? `Done: ${d.path}` : `Downloading ${d.repo ?? ''}…`;
    if (d.status === 'done' || d.status === 'error') src.close();
  };
  src.onerror = () => { if (msgEl) msgEl.textContent = 'Download failed'; src.close(); };
}

// ── DOM event binding ─────────────────────────────────────────────────────────

function _bind() {
  const on = (id, ev, fn) => {
    document.getElementById(id)?.addEventListener(ev, fn);
  };

  // Workspace
  on('btn-send',   'click', handleSend);
  document.getElementById('msg-input')?.addEventListener('keydown', e => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleSend(); }
  });
  document.getElementById('msg-input')?.addEventListener('input', e => {
    e.target.style.height = 'auto';
    e.target.style.height = Math.min(e.target.scrollHeight, 120) + 'px';
  });
  on('btn-mic',    'click', handleMicClick);
  on('btn-open-kb','click', openKBPanel);

  // Navigation
  on('btn-go-home',     'click', () => {
    goHome();
    loadWorkstation();
    history.renderRecentLanding(document.getElementById('landing-recent')).catch(() => {});
  });
  on('plan-btn-home',   'click', () => { goHome(); loadWorkstation(); });
  on('bench-btn-home',  'click', () => { goHome(); loadWorkstation(); });
  on('sched-btn-home',  'click', () => { goHome(); loadWorkstation(); });
  // Quick-start landing cards (also wires start-plan/benchmark/scheduler/btn-refresh-ws)
  bindLanding({ onStartReact: startNew });

  // Benchmark screen
  on('bench-btn-run-all', 'click', () => benchMod.runAll());
  on('bench-btn-run-sel', 'click', () => benchMod.runSelected());
  on('bench-btn-clear',   'click', () => benchMod.clearReport());

  // Scheduler screen
  on('btn-sched-refresh',      'click', () => schedulerMod.init());
  on('btn-sched-add',          'click', toggleSchedulerForm);
  on('sched-side-newtask-btn', 'click', toggleSchedulerForm);
  on('btn-sched-create',       'click', createSchedulerTask);
  on('btn-sched-cancel',       'click', toggleSchedulerForm);
  on('sched-nt-close',         'click', toggleSchedulerForm);
  on('btn-sched-settings',     'click', () => settings.open('scheduler'));
  document.getElementById('sched-nt-overlay')?.addEventListener('click', e => {
    if (e.target === e.currentTarget) toggleSchedulerForm();
  });
  document.querySelectorAll('input[name="sched-trigger-radio"]').forEach(r => {
    r.addEventListener('change', onSchedTriggerChange);
  });

  // Settings modal
  on('overlay',               'click', e => settings.handleOverlayClick(e));
  on('btn-settings-top',      'click', () => settings.open());
  on('btn-settings-sidebar',  'click', () => settings.open());
  on('btn-settings-topbar',   'click', () => settings.open());
  on('btn-modal-save',        'click', () => settings.saveCurrentTab());
  on('btn-modal-close',       'click', () => settings.close());
  on('btn-modal-close-x',     'click', () => settings.close());
  ['model','memory','persona','soul','voice','sandbox','bot','scheduler'].forEach(tab => {
    on(`snav-btn-${tab}`, 'click', () => settings.setTab(tab));
  });
  on('s-tools-enabled', 'change', settings.onToggleTools);
  on('s-tts-provider',  'change', settings.onTTSProviderChange);
  on('s-stt-provider',  'change', settings.onSTTProviderChange);
  on('btn-consolidate',   'click', settings.doConsolidate);
  on('btn-clear-memory',  'click', settings.doClearMemory);
  on('btn-clear-persona', 'click', settings.doClearPersona);

  // Sandbox / Bot
  on('btn-sandbox-save', 'click', () => settings.saveSandboxTab());
  on('btn-bot-save',     'click', async () => {
    const msgEl = document.getElementById('bot-cfg-msg');
    if (msgEl) msgEl.textContent = 'Saving…';
    await settings.saveBotTab().catch(e => { if (msgEl) msgEl.textContent = e.message; return; });
    if (msgEl) { msgEl.textContent = 'Saved ✓'; setTimeout(() => { msgEl.textContent = ''; }, 2000); }
  });
  on('btn-sched-save',   'click', async () => {
    const msgEl = document.getElementById('sched-cfg-msg');
    if (msgEl) msgEl.textContent = 'Saving…';
    await settings.saveSchedulerTab().catch(e => { if (msgEl) msgEl.textContent = e.message; return; });
    if (msgEl) { msgEl.textContent = 'Saved ✓'; setTimeout(() => { msgEl.textContent = ''; }, 2000); }
  });
  on('btn-bark-test', 'click', () => settings.testBark());
  on('btn-ntfy-test', 'click', () => settings.testNtfy());
  on('btn-bot-start',   'click', () => infraMod.bot.start().catch(e => bus.emit('toast', e.message)));
  on('btn-bot-stop',    'click', () => infraMod.bot.stop().catch(e => bus.emit('toast', e.message)));
  on('btn-bot-refresh', 'click', () => settings.setTab('bot'));

  // Workstation cards → settings  (btn-refresh-ws already wired in bindLanding)
  document.querySelectorAll('.module-card[data-tab]').forEach(card => {
    const tab = card.dataset.tab;
    card.addEventListener('dblclick', () => settings.open(tab));
    card.querySelector('.mc-settings-btn')?.addEventListener('click', e => {
      e.stopPropagation();
      settings.open(tab);
    });
  });

  // Benchmark / Scheduler cards → double-click navigates to their screens
  document.getElementById('mc-benchmark')?.addEventListener('dblclick', () => {
    goBenchmark();
    benchMod.init();
  });
  document.getElementById('mc-scheduler')?.addEventListener('dblclick', () => {
    goScheduler();
    schedulerMod.init();
  });

  // Download helpers
  document.querySelector('[data-action="download-tts"]')?.addEventListener('click', () => doDownloadModel('tts'));
  document.querySelector('[data-action="download-stt"]')?.addEventListener('click', () => doDownloadModel('stt'));

  // Mode badge → settings
  document.getElementById('tb-mode-badge')?.addEventListener('click', () => settings.open('model'));

  // Expose for inline HTML oncall
  window.onBotTransportChange = () => settings.onBotTransportChange?.();
  window.onChannelChange      = () => settings.onChannelChange?.();
}

// ── Boot ──────────────────────────────────────────────────────────────────────

async function boot() {
  // Initialise toast + Inspector global key handler
  initToast();
  Inspector.initGlobalKeyHandler();

  // Wire all DOM events
  _bind();
  initTTSHandler();
  initLifecycleListeners();
  initSidebar();
  bindSpeakDeliverySetting();
  initSpeakDeliverySync();

  // Determine initial backend state
  const status = await llmMod.fetchStatus().catch(() => null);
  if (status?.initialized) set('llmModel', status.model);

  const reactStatus = await reactMod.fetchStatus().catch(() => null);
  if (reactStatus?.status === 'ready') {
    set('reactReady', true);
    await speakMod.fetchStatus().catch(() => {});
  } else if (reactStatus?.status === 'initializing') {
    bus.emit('toast', 'ReAct initializing…');
    pollUntilReady()
      .then(async () => {
        set('reactReady', true);
        updateReactBadge();
        bus.emit('toast', 'ReAct ready');
        speakMod.fetchStatus().then(() => updateReactBadge()).catch(() => {});
        const ready = await ensureAccountReady().catch(e => {
          showToast(e.message);
          return false;
        });
        if (ready) {
          set('channelId', requireChannelId());
          loadWorkstation();
        }
      })
      .catch(() => {});
  }

  await speakMod.fetchStatus().catch(() => {});
  await soulMod.fetchReadiness().catch(() => {});
  updateReactBadge();
  personaMod.loadConfig().then(p => {
    if (p?.enabled && p.profile?.name) setAgentAvatar(p.profile.name.charAt(0));
  }).catch(() => {});

  document.getElementById('mc-persona-body')?.addEventListener('soul:reinit', async () => {
    const settings = await import('./settings.js');
    settings.open('persona');
    const tab = await import('./settings/tabs/persona.js');
    await tab.save();
    await reactMod.init({});
  });
  document.getElementById('mc-persona-body')?.addEventListener('soul:build', async () => {
    await soulMod.rebuildPersona(false).catch(e => showToast(e.message));
    await personaMod.updateWorkstationCard();
  });

  bindAccountGate();
  bus.on('account:selected', async () => {
    set('channelId', requireChannelId());
    loadWorkstation();
    history.renderSidebar().catch(() => {});
    history.renderRecentLanding(document.getElementById('landing-recent')).catch(() => {});
  });

  if (S.reactReady) {
    const ready = await ensureAccountReady().catch(e => {
      showToast(e.message);
      return false;
    });
    if (ready) {
      set('channelId', requireChannelId());
      loadWorkstation();
      history.renderSidebar().catch(() => {});
      history.renderRecentLanding(document.getElementById('landing-recent')).catch(() => {});
    }
  } else {
    set('channelId', getChannelId());
    loadWorkstation();
    history.renderSidebar().catch(() => {});
    history.renderRecentLanding(document.getElementById('landing-recent')).catch(() => {});
  }

  void botMod.updateWorkstationCard();
}

document.addEventListener('DOMContentLoaded', boot);
