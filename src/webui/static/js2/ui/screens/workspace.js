/**
 * ui/screens/workspace.js — 工作区屏幕视图。
 *
 * 实现 features/conversation 的视图契约；自己不发起网络请求
 * （work 控制帧经 conversation.sendWorkFrame，历史数据来自 store）。
 */

import * as conversation from '../../features/conversation.js';
import { bus, EVENTS } from '../../store/bus.js';
import * as sessionStore from '../../store/session_store.js';
import * as chatStore from '../../store/chat_store.js';
import * as historyStore from '../../store/history_store.js';
import * as workStore from '../../store/work_store.js';
import {
  sortEventsByOrder,
} from '../../protocol/speak_fields.js';
import * as chat from '../chat/index.js';
import * as speakAdmin from '../../features/speak_admin.js';
import * as memoryRecall from '../../features/memory_recall.js';

const $id = id => document.getElementById(id);

// ── Speak 流式控制（view 契约内部状态） ──────────────────────────────────────

let _streamCtrl = null;
let _fallbackCtrl = null;

// ── 剧情卡片（single-stream R8）：card_id → 剧情 DOM，进度段就地刷新 ─────────
const _storyCards = new Map();

function _updateStoryCard(meta = {}) {
  const el = _storyCards.get(String(meta.card_id || ''));
  if (!el) return;
  let prog = el.querySelector('.thread-marker-progress');
  if (!prog) {
    prog = document.createElement('div');
    prog.className = 'thread-marker-progress';
    const body = el.querySelector('.thread-marker-body');
    (body || el).appendChild(prog);
  }
  const upcoming = Array.isArray(meta.upcoming) ? meta.upcoming.join(' → ') : '';
  prog.textContent = `${String(meta.current || '')}${upcoming ? `　｜　接下来：${upcoming}` : ''}`;
}

function _isOutlineUpgrade(kind, meta = {}) {
  return (
    kind === 'outline'
    && Boolean(meta?.upgrade || meta?.replace)
    && String(meta?.slot || '').trim()
  );
}

function _ensureFallbackCtrl() {
  if (_fallbackCtrl) return _fallbackCtrl;
  _fallbackCtrl = chat.appendSpeakStream({
    onSlotReplace: (slot, text, meta) => _patchHistoryOutlineSlot(slot, text, meta),
  });
  return _fallbackCtrl;
}

function _routeSpeakEvent(ev) {
  const { kind, text, renderMeta: meta } = ev;
  const upgrade = _isOutlineUpgrade(kind, meta);  // 剧情卡片帧（single-stream §8）：卡片建立落一条剧情线；进度段由
  // 专属卡片组件渲染（Phase 3 完整前端改造），在此静默容错不打扰对话流。
  if (kind === 'story_card') {
    const outline = String(meta?.outline || '').trim();
    const cardId = String(meta?.card_id || '');
    if (outline) {
      const el = chat.appendThreadMarker(`📖 ${outline}`, new Date().toISOString(), {
        story: true, card_id: cardId,
      });
      if (el && cardId) _storyCards.set(cardId, el);
    }
    return;
  }
  if (kind === 'story_progress') {
    _updateStoryCard(meta);
    return;
  }

  if (_streamCtrl && !_streamCtrl._finalized) {
    _streamCtrl.onEvent(kind, text, meta);
    return;
  }
  if (upgrade && _fallbackCtrl?.replaceSlot(String(meta.slot || ''), text, meta)) {
    return;
  }
  if (upgrade && chat.replaceOutlineSlot(String(meta.slot || '').trim(), text, meta)) {
    _patchHistoryOutlineSlot(meta.slot, text, meta);
    return;
  }
  // 无在流气泡（服务端主动推送 / fallback）：开一个新的兜底气泡。
  _streamCtrl = _ensureFallbackCtrl();
  _streamCtrl.onEvent(kind, text, meta);
}

function _patchHistoryOutlineSlot(slot, text, meta = {}) {
  const key = String(slot || '').trim();
  const body = String(text ?? '').trim();
  if (!key || !body) return;
  const msgs = [...chatStore.getMessages()];
  for (let i = msgs.length - 1; i >= 0; i -= 1) {
    const msg = msgs[i];
    if (msg?.role !== 'assistant') continue;
    const events = Array.isArray(msg.speak_events) ? [...msg.speak_events] : [];
    let hit = false;
    for (let j = events.length - 1; j >= 0; j -= 1) {
      const ev = events[j];
      if (String(ev?.meta?.slot || '').trim() !== key) continue;
      events[j] = {
        ...ev,
        text: body,
        meta: { ...ev.meta, ...meta, slot: key, upgrade: true, replace: true, placeholder: false },
      };
      hit = true;
      break;
    }
    if (!hit) continue;
    msgs[i] = { ...msg, speak_events: events, content: msg.content || body };
    chatStore.setMessages(msgs);
    historyStore.saveConversation().catch(() => {});
    return;
  }
}

// ── 视图契约实现 ─────────────────────────────────────────────────────────────

const view = {
  onTurnStart({ event }) {
    if (!_streamCtrl || _streamCtrl._finalized) {
      _streamCtrl = _ensureFallbackCtrl();
    }
    const stamp = String(event?.created_at ?? '').trim();
    if (stamp) _streamCtrl?.setCreatedAt?.(stamp);
    conversation.accumulateTurnMeta(event ?? {});
    // 主体性呈现：turn_start 不代表角色已开口——打字指示由 speak_stream
    // 在第一个可见内容包真正到达时才点亮（沉默/延迟轮全程不显示）。
  },

  onSpeakEvent(ev) {
    conversation.accumulateTurnMeta(ev.renderMeta ?? {});
    _routeSpeakEvent(ev);
  },

  async onFinalizeTurn(payload, turnMeta) {
    chat.setTitleBarTyping(false);
    const ctrl = _streamCtrl || _fallbackCtrl;
    const readout = await _finalizeStream(ctrl, payload, turnMeta);
    return readout;
  },

  onDiscardTurn() {
    (_streamCtrl || _fallbackCtrl)?.discardAgentTurn?.();
    chat.setTitleBarTyping(false);
    _streamCtrl = null;
    _fallbackCtrl = null;
  },

  onTyping(active) {
    chat.setTitleBarTyping(Boolean(active));
  },

  onLifecycle() {
    // 发送按钮文案统一 ↑（旧版行为）；busy 提示走 title。
    const sendBtn = $id('btn-send');
    if (!sendBtn) return;
    const busy = sessionStore.isBusy();
    sendBtn.textContent = '↑';
    sendBtn.title = busy
      ? '发送（Agent 回复中可继续输入）；空内容点击为中止'
      : '发送';
  },

  onUserMessageSent(text, createdAt) {
    chat.appendUserMsg(text, { created_at: createdAt });
  },

  onClearMessages() {
    chat.clearMsgs();
    chat.showEmptyState('speak');
    _syncProactiveUrgeDot();
  },

  onTimelineRestore(entries) {
    _restoreTimelineTail(entries);
  },

  onRebuild(messages, workItems) {
    rebuildFromHistory(messages, workItems);
  },

  onCloseMonitor() {
    closeWorkMonitor();
  },

  onRouteDecision(msg) {
    _renderRouteCard(msg);
  },
};

// ── 流式收尾：由 view.onFinalizeTurn 调用 ───────────────────────────────────

async function _finalizeStream(streamCtrl, payload, turnMeta = {}) {
  const aborted = Boolean(payload.aborted);
  if (payload.hide_agent || payload.silence_policy === 'hidden') {
    streamCtrl?.discardAgentTurn?.();
    _streamCtrl = null;
    _fallbackCtrl = null;
    return { events: [], speakText: '' };
  }
  const answer = payload.answer ?? streamCtrl?.speakText ?? '';
  const createdAt = String(
    payload.created_at || turnMeta.created_at || streamCtrl?.createdAt || '',
  ).trim();
  if (createdAt) streamCtrl?.setCreatedAt?.(createdAt);
  const replay = streamCtrl?.hasLiveInput ? null : (payload.speak_events ?? null);
  await streamCtrl?.finalize(answer, aborted, replay);

  const events = streamCtrl?.events ?? [];
  _streamCtrl = null;
  _fallbackCtrl = null;
  return { events, speakText: streamCtrl?.speakText ?? '', createdAt };
}

// ── 路由决策卡 ───────────────────────────────────────────────────────────────

function _renderRouteCard(msg) {
  const route = String(msg?.route || '').trim();
  if (!route) return;
  const msgs = $id('msgs');
  if (!msgs) return;
  $id('empty-hint')?.remove();
  const el = document.createElement('div');
  el.className = 'msg route-msg';
  const target = route === 'work' ? 'speak' : 'work';
  const label = route === 'work' ? '任务型' : '对话型';
  const fixLabel = route === 'work' ? '这应是对话' : '这应是任务';
  const card = document.createElement('div');
  card.className = 'route-card';
  card.dataset.sampleId = String(msg.sample_id || '');
  const title = document.createElement('div');
  title.className = 'route-card-title';
  title.textContent = `首轮路由：${label}`;
  const meta = document.createElement('div');
  meta.className = 'route-card-meta';
  meta.textContent = `source: ${String(msg.source || '')}`;
  const actions = document.createElement('div');
  actions.className = 'route-card-actions';
  const btn = document.createElement('button');
  btn.className = 'work-btn';
  btn.textContent = fixLabel;
  btn.addEventListener('click', () => {
    const ok = conversation.sendRoutePierce(
      target,
      route === 'work' ? String(msg.sample_id || '') : '',
    );
    if (ok) {
      btn.disabled = true;
      btn.textContent = '已提交纠错';
    }
  });
  actions.append(btn);
  card.append(title, meta, actions);
  el.append(card);
  msgs.appendChild(el);
  msgs.scrollTop = msgs.scrollHeight;
}

// ── 历史重建 ────────────────────────────────────────────────────────────────

/**
 * 时间轴尾巴回填（boot/新窗后）：timeline 流水条目按时间升序渲染——
 * story 条目是时间轴一等公民（剧情事件条），轮次走纯文本气泡
 * （流水无 speak_events，回放不可用）。
 */
function _restoreTimelineTail(entries) {
  const list = Array.isArray(entries) ? entries : [];
  if (!list.length) return;
  for (const entry of list) {
    const kind = String(entry.kind);
    if (kind === 'story' || kind === 'story_intent') {
      chat.appendStoryEvent(entry);
      continue;
    }
    const userText = String(entry.user_text || '');
    const agentText = String(entry.agent_text || '');
    if (!userText && !agentText) continue;
    if (userText) chat.appendUserMsg(userText, { created_at: entry.at });
    if (agentText) {
      const ctrl = chat.appendAssistantMsg({ created_at: entry.at });
      ctrl.append(agentText);
      ctrl.finalize();
    }
  }
}

export function rebuildFromHistory(messages, workItems) {
  chat.clearMsgs();
  _syncProactiveUrgeDot();
  const msgs = Array.isArray(messages) ? messages : [];
  if (!msgs.length && !(workItems || []).length) {
    chat.showEmptyState('speak');
  }
  // 旧历史用 thread_marker + created_at 区分同名 title
  msgs.forEach(m => {
    if (m.role === 'thread_marker') {
      chat.appendThreadMarker(m.title || m.content || '对话', m.created_at, {
        title_key: m.title_key,
      });
      return;
    }
    if (m.role === 'user') {
      chat.appendUserMsg(m.content, {
        created_at: m.created_at,
        title_key: m.title_key,
      });
    } else if (m.role === 'assistant') {
      if (m.speak_events?.length) {
        const ctrl = chat.appendSpeakStream({ created_at: m.created_at, instant: true });
        for (const ev of sortEventsByOrder(m.speak_events)) {
          ctrl.onEvent(ev.kind, ev.text ?? '', ev.meta ?? {});
        }
        void ctrl.finalize(m.content, false);
      } else {
        const ctrl = chat.appendAssistantMsg({ created_at: m.created_at });
        ctrl.append(m.content);
        ctrl.finalize();
      }
    }
  });
  rebuildWorkCards(workItems ?? workStore.summariesForHistory());
  chat.scrollBottom();
}

// ── Work 确认卡 / 监控面板（迁移自 work/ui.js） ──────────────────────────────

const _esc = s => String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');

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

function _cardEl(workId) {
  return document.querySelector(`.work-card[data-work-id="${CSS.escape(workId)}"]`);
}

function _ensureCard(item) {
  let el = _cardEl(item.workId);
  if (el) return el;
  const msgs = $id('msgs');
  if (!msgs) return null;
  $id('empty-hint')?.remove();
  const wrap = document.createElement('div');
  wrap.className = 'msg work-msg';
  wrap.innerHTML = `
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
  msgs.appendChild(wrap);
  return wrap.querySelector('.work-card');
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
        conversation.sendWorkFrame({
          type: 'work_confirmation_response',
          work_id: item.workId,
          approved: true,
        });
      });
      const decline = document.createElement('button');
      decline.className = 'work-btn';
      decline.textContent = '不执行';
      decline.addEventListener('click', () => {
        conversation.sendWorkFrame({
          type: 'work_confirmation_response',
          work_id: item.workId,
          approved: false,
          reason: '用户拒绝执行',
          reason_code: 'user_declined',
        });
      });
      actionsEl.append(approve, decline);
    } else if (item.status === 'running' || item.status === 'starting') {
      const abortBtn = document.createElement('button');
      abortBtn.className = 'work-btn work-btn-danger';
      abortBtn.textContent = '中止';
      abortBtn.addEventListener('click', () => {
        conversation.sendWorkFrame({ type: 'work_abort', work_id: item.workId });
      });
      const mon = document.createElement('button');
      mon.className = 'work-btn';
      mon.textContent = '刷新监控';
      mon.addEventListener('click', () => {
        conversation.sendWorkFrame({ type: 'work_monitor_request', work_id: item.workId });
        openWorkMonitor(item.workId);
      });
      actionsEl.append(abortBtn, mon);
    } else {
      const open = document.createElement('button');
      open.className = 'work-btn';
      open.textContent = '查看详情';
      open.addEventListener('click', () => openWorkMonitor(item.workId));
      actionsEl.append(open);
    }
  }

  const msgs = $id('msgs');
  if (msgs) msgs.scrollTop = msgs.scrollHeight;
  renderWorkMonitor(item.workId);
}

export function openWorkMonitor(workId) {
  const panel = $id('work-monitor-panel');
  if (!panel) return;
  panel.classList.remove('hidden');
  panel.dataset.workId = workId || '';
  renderWorkMonitor(workId);
}

export function closeWorkMonitor() {
  $id('work-monitor-panel')?.classList.add('hidden');
}

export function renderWorkMonitor(workId) {
  const panel = $id('work-monitor-panel');
  if (!panel || panel.classList.contains('hidden')) return;
  const id = workId || panel.dataset.workId;
  const item = id ? workStore.get(id) : null;
  const title = panel.querySelector('[data-role="mon-title"]');
  const body = panel.querySelector('[data-role="mon-body"]');
  if (!item) {
    if (title) title.textContent = '任务监控';
    if (body) body.innerHTML = '<div class="work-mon-empty">暂无任务</div>';
    return;
  }
  if (title) title.textContent = `任务 · ${_statusLabel(item.status)}`;
  const events = (item.events || []).slice(-12).map(ev =>
    `<div class="work-mon-line"><span class="work-mon-type">${_esc(ev.type)}</span> ${_esc(ev.message || ev.reason || '')}</div>`,
  ).join('');
  if (body) {
    body.innerHTML = `
      <div class="work-mon-q">${_esc(item.question)}</div>
      <div class="work-mon-meta">status: ${_esc(item.status)}${item.reason ? ` · ${_esc(item.reason)}` : ''}</div>
      ${item.answer ? `<div class="work-mon-answer">${_esc(item.answer)}</div>` : ''}
      <div class="work-mon-events">${events || '<div class="work-mon-empty">暂无事件</div>'}</div>`;
  }
}

function rebuildWorkCards(workItems) {
  workStore.restoreFromHistory(workItems);
  workStore.all().forEach(item => _renderCard(item));
}

// ── 侧栏 / 顶栏杂项 ─────────────────────────────────────────────────────────

export function setSidebarCollapsed(collapsed) {
  const sidebar = $id('sidebar');
  const toggleBtn = $id('btn-sidebar-toggle');
  if (!sidebar) return;
  sidebar.classList.toggle('collapsed', collapsed);
  if (toggleBtn) {
    toggleBtn.textContent = collapsed ? '▶' : '◀';
    toggleBtn.title = collapsed ? '展开侧栏' : '收起侧栏';
  }
}

export function toggleSidebar(forceOpen) {
  const sidebar = $id('sidebar');
  if (!sidebar) return;
  if (forceOpen === true) {
    setSidebarCollapsed(false);
    return;
  }
  setSidebarCollapsed(!sidebar.classList.contains('collapsed'));
}

export function _syncProactiveUrgeDot() {
  const dot = $id('tb-proactive-dot');
  if (!dot) return;
  const st = sessionStore.state();
  dot.classList.toggle('active', Boolean(st.proactiveUrge || st.proactiveUnread));
}

// ── Trace 按钮 ──────────────────────────────────────────────────────────────

let _traceEnabled = false;

async function syncTraceButton() {
  const btn = $id('btn-speak-trace');
  const sid = sessionStore.state().sessionId;
  if (!btn || !sid) {
    if (btn) btn.classList.remove('active');
    return;
  }
  const data = await speakAdmin.getSessionTrace(sid).catch(() => ({ enabled: false }));
  _traceEnabled = Boolean(data.enabled);
  btn.classList.toggle('active', _traceEnabled);
  btn.title = _traceEnabled
    ? '已开启：下一轮起主进程打印提示词（点按关闭）'
    : '主进程打印本 session 提示词与记忆缓存（点按开启）';
}

// ── 装配 ────────────────────────────────────────────────────────────────────

/** app 启动时调用一次。 */
export function initWorkspace() {
  conversation.registerChatView(view);

  // work 卡片与持久化联动
  workStore.subscribe((item, event) => {
    if (event) _renderCard(item);
    if (['work_confirmation_required', 'work_started', 'work_progress'].includes(event?.type)) {
      openWorkMonitor(item.workId);
    }
    historyStore.saveConversation().catch(() => {});
  });

  bindMonitorPanel();
  bindSidebar();
  bindComposer();

  bus.on(EVENTS.planInitSubpanel, () => {
    import('../../features/plan_bridge.js')
      .then(m => m.initSubPanel?.())
      .catch(() => {});
  });

  sessionStore.subscribe((_snap, changed) => {
    if ('sessionId' in changed) syncTraceButton().catch(() => {});
    if ('proactiveUrge' in changed || 'proactiveUnread' in changed) _syncProactiveUrgeDot();
  });

  syncTraceButton().catch(() => {});
  _syncProactiveUrgeDot();
}

function bindMonitorPanel() {
  $id('btn-work-monitor-close')?.addEventListener('click', closeWorkMonitor);
  $id('btn-open-work-monitor')?.addEventListener('click', () => {
    const active = workStore.all().find(i =>
      ['pending_confirmation', 'starting', 'running'].includes(i.status),
    ) || workStore.all().at(-1);
    openWorkMonitor(active?.workId);
  });
}

function bindSidebar() {
  // 单窗口（single-stream R1）：无新对话、无会话排序——侧栏即回忆面板。
  memoryRecall.mountSidebar();

  $id('btn-sidebar-open')?.addEventListener('click', () => toggleSidebar(true));
  $id('btn-sidebar-toggle')?.addEventListener('click', () => toggleSidebar());

  $id('btn-speak-trace')?.addEventListener('click', async () => {
    const sid = sessionStore.state().sessionId;
    if (!sid) {
      showToastText('请先发送一条消息以建立 session');
      return;
    }
    const next = !_traceEnabled;
    await speakAdmin.setSessionTrace(sid, next);
    _traceEnabled = next;
    await syncTraceButton();
    showToastText(next ? '已开启 Speak 提示词追踪（见运行 Soul 的终端）' : '已关闭 Speak 提示词追踪');
    if (next) {
      const dbg = await speakAdmin.fetchSessionDebug(sid).catch(() => null);
      if (dbg) {
        console.info('[speak debug] 本地缓存', dbg.cache);
        console.info('[speak debug] 说明', dbg.module_trace_hint);
      }
    }
  });
}

function bindComposer() {
  const input = $id('msg-input');
  $id('btn-send')?.addEventListener('click', handleSend);
  input?.addEventListener('keydown', e => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  });
  input?.addEventListener('input', e => {
    e.target.style.height = 'auto';
    e.target.style.height = Math.min(e.target.scrollHeight, 120) + 'px';
  });

  // mic / TTS / KB 由 voice 与 knowledge 功能绑定（见 features/voice.js、app.js）
}

export async function handleSend() {
  const inputEl = $id('msg-input');
  const question = inputEl?.value.trim() ?? '';
  const st = sessionStore.state();

  if (st.lifecycle === 'streaming' || st.lifecycle === 'aborting') {
    if (!question) {
      conversation.abortStream();
      view.onLifecycle();
      return;
    }
    if (inputEl) inputEl.value = '';
    await conversation.send(question);
    return;
  }

  if (!question) return;
  if (inputEl) inputEl.value = '';
  await conversation.send(question);
}

function showToastErr(err, prefix) {
  import('../components/toast.js').then(m => m.showToast(`${prefix}: ${err?.message ?? err}`));
}
function showToastText(text) {
  import('../components/toast.js').then(m => m.showToast(text));
}

/** mic / TTS 按钮的延迟绑定入口（app.js 在 voice feature 就绪后调用）。 */
export function bindVoiceButtons(voice) {
  $id('btn-mic')?.addEventListener('click', async () => {
    const btn = $id('btn-mic');
    if (voice.isRecording()) {
      btn?.classList.remove('recording');
      const text = await voice.stopRecordingAndTranscribe();
      if (text) {
        const inp = $id('msg-input');
        if (inp) inp.value = `${inp.value} ${text}`.trim();
      }
    } else {
      await voice.startRecording().catch(e => showToastText('Mic error: ' + e.message));
      btn?.classList.add('recording');
    }
  });

  document.addEventListener('click', async e => {
    const btn = e.target.closest('.msg-tts-btn');
    if (!btn) return;
    const text = btn.dataset.text;
    if (!text) return;
    if (voice.isSpeaking()) {
      voice.stopSpeaking();
      btn.classList.remove('playing');
      return;
    }
    btn.classList.add('playing');
    await voice.speak(text);
    btn.classList.remove('playing');
  });
}
