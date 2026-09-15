/**
 * app.js — js2 应用入口：装配 + 启动序列。
 *
 * 职责仅限：import 各层、绑定 DOM 事件、按序启动（账号 → readiness → 工作区
 * → 通知 SSE）。业务在 features，状态在 store，渲染在 ui。
 */

import { bus, EVENTS } from './store/bus.js';
import * as sessionStore from './store/session_store.js';
import { initToast, showToast } from './ui/components/toast.js';
import {
  bindNavigationRequests, goHome, goWorkspace,
  goPlan, goBenchmark, goScheduler,
} from './ui/router.js';
import { http } from './transport/http.js';
import { API } from './protocol/http_api.js';

// features
import * as conversation from './features/conversation.js';
import * as proactive from './features/proactive.js';
import * as speakAdmin from './features/speak_admin.js';
import * as accounts from './features/accounts.js';
import * as voice from './features/voice.js';
import * as basics from './features/basics.js';

// screens / ui
import * as workspaceView from './ui/screens/workspace.js';
import * as landing from './ui/screens/landing.js';
import * as accountGate from './ui/screens/account_gate.js';
import * as cards from './ui/screens/workstation_cards.js';

// settings（设置弹窗；tabs 已迁入 ui/settings_ui/tabs）
import * as settings from './ui/settings_ui/modal.js';

let _proactiveOpenChain = Promise.resolve();

function _bind() {
  const on = (id, ev, fn) => document.getElementById(id)?.addEventListener(ev, fn);

  // 导航
  on('btn-go-home', 'click', () => {
    goHome();
    cards.refreshAll();
  });
  on('plan-btn-home', 'click', () => { goHome(); cards.refreshAll(); });
  on('bench-btn-home', 'click', () => { goHome(); cards.refreshAll(); });
  on('sched-btn-home', 'click', () => { goHome(); cards.refreshAll(); });

  // KB 面板开关
  on('btn-open-kb', 'click', openKBPanel);

  // Benchmark 屏按钮
  on('bench-btn-run-all', 'click', () => import('./features/bench_bridge.js').then(m => m.runAll()).catch(() => {}));
  on('bench-btn-run-sel', 'click', () => import('./features/bench_bridge.js').then(m => m.runSelected()).catch(() => {}));
  on('bench-btn-clear', 'click', () => import('./features/bench_bridge.js').then(m => m.clearReport()).catch(() => {}));

  // Scheduler 屏按钮 + 新建任务弹层
  on('btn-sched-refresh', 'click', () => import('./features/scheduler_bridge.js').then(m => m.init()).catch(() => {}));
  on('btn-sched-add', 'click', toggleSchedulerForm);
  on('sched-side-newtask-btn', 'click', toggleSchedulerForm);
  on('btn-sched-create', 'click', createSchedulerTask);
  on('btn-sched-cancel', 'click', toggleSchedulerForm);
  on('sched-nt-close', 'click', toggleSchedulerForm);
  on('btn-sched-settings', 'click', () => settings.open('scheduler'));
  document.getElementById('sched-nt-overlay')?.addEventListener('click', e => {
    if (e.target === e.currentTarget) toggleSchedulerForm();
  });
  document.querySelectorAll('input[name="sched-trigger-radio"]').forEach(r => {
    r.addEventListener('change', onSchedTriggerChange);
  });

  // 设置弹窗
  on('overlay', 'click', e => settings.handleOverlayClick(e));
  on('btn-settings-top', 'click', () => settings.open());
  on('btn-settings-sidebar', 'click', () => settings.open());
  on('btn-settings-topbar', 'click', () => settings.open());
  on('btn-modal-save', 'click', () => settings.saveCurrentTab());
  on('btn-modal-close', 'click', () => settings.close());
  on('btn-modal-close-x', 'click', () => settings.close());
  ['model', 'memory', 'persona', 'soul', 'voice', 'sandbox', 'bot', 'scheduler'].forEach(tab => {
    on(`snav-btn-${tab}`, 'click', () => settings.setTab(tab));
  });
  on('s-tools-enabled', 'change', settings.onToggleTools);
  on('s-tts-provider', 'change', settings.onTTSProviderChange);
  on('s-stt-provider', 'change', settings.onSTTProviderChange);
  on('btn-consolidate', 'click', settings.doConsolidate);
  on('btn-clear-memory', 'click', settings.doClearMemory);
  on('btn-clear-persona', 'click', settings.doClearPersona);

  // Sandbox / Bot / Scheduler 专用保存与测试
  on('btn-sandbox-save', 'click', () => settings.saveSandboxTab());
  on('btn-bot-save', 'click', async () => {
    const msgEl = document.getElementById('bot-cfg-msg');
    if (msgEl) msgEl.textContent = 'Saving…';
    await settings.saveBotTab().catch(e => { if (msgEl) msgEl.textContent = e.message; return; });
    if (msgEl) { msgEl.textContent = 'Saved ✓'; setTimeout(() => { msgEl.textContent = ''; }, 2000); }
  });
  on('btn-sched-save', 'click', async () => {
    const msgEl = document.getElementById('sched-cfg-msg');
    if (msgEl) msgEl.textContent = 'Saving…';
    await settings.saveSchedulerTab().catch(e => { if (msgEl) msgEl.textContent = e.message; return; });
    if (msgEl) { msgEl.textContent = 'Saved ✓'; setTimeout(() => { msgEl.textContent = ''; }, 2000); }
  });
  on('btn-bark-test', 'click', () => settings.testBark());
  on('btn-ntfy-test', 'click', () => settings.testNtfy());
  on('btn-bot-start', 'click', () => basics.botMod.start().catch(e => bus.emit(EVENTS.toastShow, e.message)));
  on('btn-bot-stop', 'click', () => basics.botMod.stop().catch(e => bus.emit(EVENTS.toastShow, e.message)));
  on('btn-bot-refresh', 'click', () => settings.setTab('bot'));

  // 工作站卡片 → 设置 tab
  document.querySelectorAll('.module-card[data-tab]').forEach(cardEl => {
    const tab = cardEl.dataset.tab;
    cardEl.addEventListener('dblclick', () => settings.open(tab));
    cardEl.querySelector('.mc-settings-btn')?.addEventListener('click', e => {
      e.stopPropagation();
      settings.open(tab);
    });
  });

  // 基准/调度卡片双击进屏
  document.getElementById('mc-benchmark')?.addEventListener('dblclick', () => {
    goBenchmark();
    import('./features/bench_bridge.js').then(m => m.init()).catch(() => {});
  });
  document.getElementById('mc-scheduler')?.addEventListener('dblclick', () => {
    goScheduler();
    import('./features/scheduler_bridge.js').then(m => m.init()).catch(() => {});
  });

  // 模型下载（SSE）
  document.querySelector('[data-action="download-tts"]')?.addEventListener('click', () => downloadModel('tts'));
  document.querySelector('[data-action="download-stt"]')?.addEventListener('click', () => downloadModel('stt'));

  // 模式徽标 → 模型设置
  document.getElementById('tb-mode-badge')?.addEventListener('click', () => settings.open('model'));

  // inline HTML 回调兼容
  window.onBotTransportChange = () => settings.onBotTransportChange?.();
  window.onChannelChange = () => settings.onChannelChange?.();

  // Landing 快速入口（单窗口：无新对话 CTA） + soul 卡动作
  landing.bindLanding();
  bus.on('workstation:soul_action', async ({ action }) => {
    if (action === 'settings') {
      settings.open('persona');
    } else if (action === 'reinit') {
      settings.open('persona');
      const tab = await import('./ui/settings_ui/tabs/persona.js');
      await tab.save();
      showToast('Persona 已保存；请重启 WebUI 以重新 bootstrap Soul');
    } else if (action === 'build') {
      await basics.soulMod.rebuildPersona(false).catch(e => showToast(e.message));
      await cards.updatePersonaCard();
    }
  });
}

// ── Scheduler 表单辅助 ──────────────────────────────────────────────────────

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
  document.getElementById('sched-once-fields').style.display = t === 'once' ? '' : 'none';
  document.getElementById('sched-interval-fields').style.display = t === 'interval' ? '' : 'none';
}

async function createSchedulerTask() {
  const $ = id => document.getElementById(id);
  const st = sessionStore.state();
  const triggerType = document.querySelector('input[name="sched-trigger-radio"]:checked')?.value ?? 'once';
  const delivery = $('sched-delivery')?.value ?? 'push';
  const replyChannel = $('sched-reply-channel')?.value ?? '';
  const reply_target = replyChannel
    ? {
        type: replyChannel,
        ...(replyChannel === 'webui'
          ? { channel_id: st.channelId ?? '', session_id: st.sessionId ?? '' }
          : {}),
      }
    : null;
  const payload = {
    name: $('sched-name')?.value ?? '',
    instruction: $('sched-instruction')?.value ?? '',
    trigger_type: triggerType,
    profile: $('sched-profile')?.value ?? 'minimal',
    delivery,
    reply_target,
    at: triggerType === 'once' ? $('sched-at')?.value : undefined,
    interval_seconds: triggerType === 'interval' ? parseInt($('sched-interval')?.value) : undefined,
  };
  const msgEl = $('sched-form-msg');
  if (msgEl) msgEl.textContent = 'Creating…';
  try {
    const schedMod = await import('./features/scheduler_bridge.js');
    await schedMod.createTask(payload);
  } catch (e) {
    if (msgEl) msgEl.textContent = e.message;
    return;
  }
  if (msgEl) msgEl.textContent = '';
  toggleSchedulerForm();
}

// ── 模型下载 SSE ────────────────────────────────────────────────────────────

function downloadModel(type) {
  const url = type === 'tts' ? API.voice.tts.download : API.voice.stt.download;
  const msgEl = document.getElementById(`${type}-dl-msg`);
  if (msgEl) msgEl.textContent = 'Starting download…';
  const src = new EventSource(url);
  src.onmessage = e => {
    let d;
    try { d = JSON.parse(e.data); } catch { return; }
    if (msgEl) msgEl.textContent = d.status === 'done' ? `Done: ${d.path}` : `Downloading ${d.repo ?? ''}…`;
    if (d.status === 'done' || d.status === 'error') src.close();
  };
  src.onerror = () => {
    if (msgEl) msgEl.textContent = 'Download failed';
    src.close();
  };
}

// ── KB 面板 ─────────────────────────────────────────────────────────────────

async function openKBPanel() {
  const panel = document.getElementById('kb-panel');
  if (!panel) return;
  panel.classList.toggle('hidden');
  if (!panel.classList.contains('hidden')) {
    const kb = await import('./features/knowledge_panel.js');
    kb.renderPanel(document.getElementById('kb-docs-list'));
  }
}

// ── Boot ────────────────────────────────────────────────────────────────────

async function _enterDefaultWorkspace() {
  const interactorId = accounts.getCurrentInteractorId();
  sessionStore.update({ channelId: sessionStore.getChannelId(interactorId) });
  conversation.setInteractorIdProvider(() => accounts.getCurrentInteractorId());
  proactive.connect(interactorId);
  await conversation.startNew();
}

async function boot() {
  window.__js2Boot = 'started';
  document.body?.setAttribute('data-js2-boot', 'main-v3');
  initToast();
  bindNavigationRequests();
  _bind();

  // 视图装配（单窗口：侧栏即回忆面板，无会话列表）
  workspaceView.initWorkspace();
  workspaceView.bindVoiceButtons(voice);
  conversation.setInteractorIdProvider(() => accounts.getCurrentInteractorId());

  // 人格头像
  basics.personaMod.loadConfig()
    .then(p => {
      if (p?.enabled && p.profile?.name) {
        import('./ui/chat/index.js').then(m => m.setAgentAvatar(p.profile.name.charAt(0)));
      }
    })
    .catch(() => {});

  // 后端就绪态
  await basics.llmMod.fetchStatus().catch(() => null);
  await speakAdmin.fetchStatus()
    .then(data => sessionStore.update({ speakReady: Boolean(data.ready) }))
    .catch(() => {});
  await http.get(API.soul.readiness)
    .then(r => sessionStore.update({
      soulReady: Boolean(r.ready || r.soul_running),
      speakReady: Boolean(r.speak_ready),
    }))
    .catch(() => {});

  // 主动消息链（串行开窗）
  proactive.configure({
    onProactiveAvailable: payload => {
      _proactiveOpenChain = _proactiveOpenChain
        .then(() => conversation.openProactiveSession(payload))
        .catch(e => showToast(String(e.message || e)));
    },
    onCreateUiRequest: payload => {
      _proactiveOpenChain = _proactiveOpenChain
        .then(() => conversation.handleCreateUiRequest(payload))
        .catch(e => showToast(String(e.message || e)));
    },
  });

  accountGate.bindAccountGate();
  bus.on(EVENTS.accountSelected, async () => {
    await _enterDefaultWorkspace();
    refreshHistoryLists();
  });

  async function ensureAndEnter() {
    const ready = await accountGate.ensureAccountReady().catch(e => {
      showToast(e.message);
      return false;
    });
    if (ready) {
      await _enterDefaultWorkspace();
      refreshHistoryLists();
    }
    return ready;
  }

  function refreshHistoryLists() {
    import('./store/history_store.js')
      .then(m => m.refreshList())
      .catch(() => {});
  }

  if (!sessionStore.state().speakReady) {
    showToast('Soul Speak initializing…');
    speakAdmin.pollUntilSpeakReady()
      .then(async () => {
        await speakAdmin.fetchStatus().catch(() => {});
        sessionStore.update({ speakReady: true });
        showToast('Speak ready');
        await ensureAndEnter();
      })
      .catch(e => showToast('Soul Speak init failed: ' + (e.message || e)));
  } else {
    await ensureAndEnter();
  }

  void cards.refreshAll();
  window.__js2Boot = 'done';
}

// 本模块经加载器动态导入，可能在 DOMContentLoaded 之后才求值；
// 两种时机都要保证 boot 恰好执行一次。
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', boot, { once: true });
} else {
  void boot();
}
