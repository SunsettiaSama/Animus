/**
 * ui/chat/speak_stream.js — Soul Speak 流式消息渲染。
 *
 * 按协议字段（thought/speak/body/wait/silence/typing/finish/observe/outline）
 * 分块分色渲染；支持 delta/end 两相位、outline slot 升级替换、simulated
 * 打字回放的播放队列。字段语义见 protocol/speak_fields.js —— 本文件只做
 * 渲染，不解析 character 原始标签。
 */

import {
  META_ORDER,
  META_PHASE,
  META_RENDER_TIME_MS,
  META_SESSION_STATE,
  META_WAIT_MS,
  fieldLabel,
  resolveRenderField,
  resolveRenderOrder,
  sortEventsByOrder,
} from '../../protocol/speak_fields.js';
import { ts, scrollBottom, msgsEl } from './markdown.js';
import { agentAvatar } from './bubbles.js';
import { setTitleBarTyping } from './typing.js';
import { ensureDayDivider } from './timeline.js';

const _SPEAK_FIELD_LABEL = Object.freeze({
  thought: 'think',
  speak: 'speak',
  body: 'body',
  wait: 'wait',
  silence: 'silence',
  typing: 'typing',
  finish: 'finish',
  observe: 'narrative',
  outline: 'outline',
  anchor: 'anchor',
  session: 'state',
});

function _isHollowSpeakMsg(node) {
  return Boolean(
    node?.classList?.contains('speak-msg')
    && !node.querySelector('.speak-field, .speak-render-spinner, .speak-abort-note'),
  );
}

/**
 * Soul Speak 流式消息：每个协议字段一块，带标签与独立配色。
 * @param {{created_at?:string, instant?:boolean, onSlotReplace?:(slot:string,text:string,meta:object)=>void}} [opts]
 * @returns {SpeakStreamCtrl|null}
 */
export function appendSpeakStream(opts = {}) {
  const el = msgsEl();
  if (!el) return null;
  ensureDayDivider(opts.created_at);
  el.querySelector('.empty-state')?.remove();
  while (_isHollowSpeakMsg(el.lastElementChild)) {
    el.lastElementChild.remove();
  }

  const div = document.createElement('div');
  div.className = 'message assistant speak-msg';

  const avatar = document.createElement('div');
  avatar.className = 'msg-avatar';
  avatar.textContent = agentAvatar();

  const body = document.createElement('div');
  body.className = 'msg-body';

  const streamCol = document.createElement('div');
  streamCol.className = 'speak-stream';

  let _createdAt = String(opts.created_at ?? '').trim();
  const timeEl = document.createElement('span');
  timeEl.className = 'msg-time';
  timeEl.textContent = ts(_createdAt || undefined);

  const ttsBtn = document.createElement('button');
  ttsBtn.className = 'msg-tts-btn hidden';
  ttsBtn.title = 'Play';
  ttsBtn.innerHTML = `<span class="sound-wave"><b></b><b></b><b></b><b></b><b></b></span>`;

  body.append(streamCol, timeEl, ttsBtn);
  div.append(avatar, body);
  el.appendChild(div);
  scrollBottom();

  let _speakParts = [];
  let _events = [];
  let _openBlock = null; // { wrap, content, field, kind, meta }
  let _thinkPending = null;
  let _finalized = false;
  let _renderSpinner = null;
  const _playQueue = [];
  // 单包最大渲染等待：防止某条超长文本把后续消息憋住
  const _PACE_CAP_MS = 1600;
  let _acceptedLive = false;
  let _pumping = false;
  let _stopped = false;
  let _idleWaiters = [];

  function _showTypingIndicator() {
    setTitleBarTyping(true);
  }

  function _hideTypingIndicator() {
    setTitleBarTyping(false);
  }

  function _spinnerTarget(meta = {}) {
    const target = String(meta.render_target || meta.role_op || '').trim().toLowerCase();
    if (target === 'body' || target === 'action') return 'body';
    return 'speak';
  }

  function _showRenderSpinner(meta = {}) {
    const target = _spinnerTarget(meta);
    if (_renderSpinner) {
      const current = _renderSpinner.className.includes('spinner-body') ? 'body' : 'speak';
      if (current === target) return;
      _hideRenderSpinner();
    }
    const wrap = document.createElement('div');
    wrap.className = `speak-render-spinner speak-render-spinner-${target}`;
    wrap.innerHTML = '<span class="speak-render-spinner-icon"></span>';
    const order = resolveRenderOrder(meta?.[META_ORDER]);
    if (order != null) wrap.dataset.order = String(order);
    _insertFieldWrap(wrap, order);
    _renderSpinner = wrap;
    scrollBottom();
  }

  function _hideRenderSpinner() {
    _renderSpinner?.remove();
    _renderSpinner = null;
  }

  function _fieldKey(kind, meta = {}) {
    return resolveRenderField(kind, meta)
      || (kind === 'action' ? 'body' : null)
      || (kind === 'thought' ? 'thought' : null)
      || (kind === 'speak' || kind === 'segment' ? 'speak' : null)
      || (kind === 'observe' ? 'observe' : null)
      || (kind === 'outline' ? 'outline' : null)
      || (kind === 'anchor' ? 'anchor' : null)
      || 'speak';
  }

  function _closeOpenBlock() {
    if (!_openBlock) return;
    const { wrap, content, field, kind, meta } = _openBlock;
    wrap.classList.remove('streaming');
    const text = String(content.textContent || '').trim();
    if (!text) {
      wrap.remove();
    } else {
      if (field === 'speak') _speakParts.push(text);
      _events.push({
        kind: kind === 'segment' ? 'speak' : kind,
        text,
        meta: { ...meta, field },
      });
    }
    _openBlock = null;
  }

  function _insertFieldWrap(wrap, order) {
    if (order == null) {
      if (_renderSpinner && wrap !== _renderSpinner) {
        streamCol.insertBefore(wrap, _renderSpinner);
      } else {
        streamCol.appendChild(wrap);
      }
      return;
    }
    const kids = [...streamCol.children].filter(
      (node) => node.classList && (
        node.classList.contains('speak-field')
        || node.classList.contains('speak-render-spinner')
      ),
    );
    for (const kid of kids) {
      if (kid === wrap) continue;
      const ko = resolveRenderOrder(kid.dataset.order);
      if (ko != null && ko > order) {
        streamCol.insertBefore(wrap, kid);
        return;
      }
    }
    streamCol.appendChild(wrap);
  }

  function _ensureFieldBlock(field, kind, meta = {}) {
    if (_openBlock && _openBlock.field === field) {
      const openOrder = resolveRenderOrder(_openBlock.meta?.[META_ORDER]);
      const nextOrder = resolveRenderOrder(meta?.[META_ORDER]);
      // 同 field 但索引不同：拆成新块，避免交叉演出被合并
      if (openOrder == null || nextOrder == null || openOrder === nextOrder) {
        _openBlock.meta = { ...meta, field };
        return _openBlock;
      }
    }
    _closeOpenBlock();
    if (_thinkPending) {
      _thinkPending.wrap.remove();
      _thinkPending = null;
    }

    const wrap = document.createElement('div');
    wrap.className = `speak-field speak-field-${field} streaming`;
    wrap.dataset.field = field;
    const order = resolveRenderOrder(meta?.[META_ORDER]);
    if (order != null) wrap.dataset.order = String(order);
    const slot = String(meta?.slot ?? '').trim();
    if (slot) wrap.dataset.slot = slot;

    const label = document.createElement('span');
    label.className = 'speak-field-label';
    label.textContent = _SPEAK_FIELD_LABEL[field] || fieldLabel(field) || field;

    const content = document.createElement('div');
    content.className = 'speak-field-content';

    wrap.append(label, content);
    _insertFieldWrap(wrap, order);
    _openBlock = { wrap, content, field, kind, meta: { ...meta, field } };
    scrollBottom();
    return _openBlock;
  }

  function _appendFieldChunk(field, kind, chunk, meta = {}) {
    const piece = String(chunk ?? '');
    if (!piece) return;
    const block = _ensureFieldBlock(field, kind, meta);
    block.content.textContent += piece;
    scrollBottom();
  }

  function _lastCommittedText(field) {
    for (let i = _events.length - 1; i >= 0; i -= 1) {
      if (String(_events[i]?.meta?.field || '') === field) {
        return String(_events[i].text || '').trim();
      }
    }
    return '';
  }

  function _sameFieldTextOrder(field, text, meta, otherField, otherText, otherMeta) {
    if (field !== otherField) return false;
    if (String(text ?? '').trim() !== String(otherText ?? '').trim()) return false;
    const order = resolveRenderOrder(meta?.[META_ORDER]);
    const other = resolveRenderOrder(otherMeta?.[META_ORDER]);
    if (order != null && other != null) return order === other;
    return true;
  }

  function _isDuplicateContent(field, text, meta = {}) {
    const body = String(text ?? '').trim();
    if (!body || (field !== 'body' && field !== 'speak')) return false;
    for (const ev of _events) {
      if (_sameFieldTextOrder(field, body, meta, ev?.meta?.field, ev.text, ev.meta)) return true;
    }
    for (const item of _playQueue) {
      if (_sameFieldTextOrder(field, body, meta, item.field, item.text, item.meta)) return true;
    }
    if (_lastCommittedText(field) === body) return true;
    const wraps = streamCol.querySelectorAll(`.speak-field-${field} .speak-field-content`);
    const last = wraps.length ? String(wraps[wraps.length - 1].textContent || '').trim() : '';
    return last === body;
  }

  function _commitField(field, kind, text, meta = {}) {
    // wait / think 不对用户展示
    if (field === 'wait' || field === 'thought' || field === 'silence') return;
    const body = String(text ?? '').trim();
    if (!body && field !== 'silence' && field !== 'finish') return;
    if (_isDuplicateContent(field, body, meta)) return;
    _closeOpenBlock();
    if (_thinkPending) {
      _thinkPending.wrap.remove();
      _thinkPending = null;
    }

    const wrap = document.createElement('div');
    wrap.className = `speak-field speak-field-${field}`;
    wrap.dataset.field = field;
    const order = resolveRenderOrder(meta?.[META_ORDER]);
    if (order != null) wrap.dataset.order = String(order);
    const slot = String(meta?.slot ?? '').trim();
    if (slot) wrap.dataset.slot = slot;

    const label = document.createElement('span');
    label.className = 'speak-field-label';
    label.textContent = _SPEAK_FIELD_LABEL[field] || fieldLabel(field) || field;

    const content = document.createElement('div');
    content.className = 'speak-field-content';

    if (field === 'silence') {
      const seconds = meta.seconds ?? (meta.wait_ms != null ? Number(meta.wait_ms) / 1000 : null);
      content.textContent = seconds != null && !Number.isNaN(seconds)
        ? `${field} ${seconds}s`
        : (body || field);
    } else if (field === 'finish' || field === 'session') {
      content.textContent = body || String(meta[META_SESSION_STATE] || field);
    } else {
      content.textContent = body;
    }

    wrap.append(label, content);
    _insertFieldWrap(wrap, order);

    if (field === 'speak' && body) _speakParts.push(body);
    if (meta?.placeholder) wrap.classList.add('speak-outline-placeholder');
    _events.push({
      kind: kind === 'segment' ? 'speak' : kind,
      text: content.textContent,
      meta: { ...meta, field },
    });
    scrollBottom();
  }

  function _handleStreamChunk(kind, text, meta = {}) {
    const field = _fieldKey(kind, meta);
    const phase = String(meta[META_PHASE] ?? meta.phase ?? '').trim();
    const chunk = String(text ?? '');

    if (phase === 'delta') {
      _appendFieldChunk(field, kind, chunk, meta);
      return;
    }
    if (phase === 'end') {
      if (chunk) {
        if (_openBlock && _openBlock.field === field) {
          if (!_openBlock.content.textContent) _openBlock.content.textContent = chunk;
          else if (!_openBlock.content.textContent.endsWith(chunk)) {
            _openBlock.content.textContent += chunk;
          }
        } else {
          _appendFieldChunk(field, kind, chunk, meta);
        }
      }
      _closeOpenBlock();
      scrollBottom();
      return;
    }
    _commitField(field, kind, chunk, meta);
  }

  function _renderByField(kind, text, meta = {}) {
    const field = _fieldKey(kind, meta);
    if (!field || field === 'finish' || field === 'typing') {
      // finish 一律空文案；有正文也不渲染成可见字段
      return;
    }
    if (field === 'speak' || field === 'body' || field === 'outline') _hideRenderSpinner();
    _handleStreamChunk(kind, text, { ...meta, field });
  }

  function _replaceSlotContent(slot, text, meta = {}) {
    const key = String(slot || '').trim();
    const body = String(text ?? '').trim();
    if (!key || !body) return false;
    const wrap = streamCol.querySelector(`.speak-field[data-slot="${CSS.escape(key)}"]`)
      || document.querySelector(`.speak-field[data-slot="${CSS.escape(key)}"]`);
    if (!wrap) return false;
    const content = wrap.querySelector('.speak-field-content');
    if (!content) return false;
    content.textContent = body;
    wrap.classList.remove('streaming', 'speak-outline-placeholder');
    if (meta?.placeholder) wrap.classList.add('speak-outline-placeholder');
    else wrap.classList.remove('speak-outline-placeholder');
    const field = String(wrap.dataset.field || meta?.field || 'outline').trim() || 'outline';
    let patched = false;
    for (let i = _events.length - 1; i >= 0; i -= 1) {
      const ev = _events[i];
      if (String(ev?.meta?.slot || '').trim() !== key) continue;
      _events[i] = {
        ...ev,
        text: body,
        meta: { ...ev.meta, ...meta, field, slot: key, upgrade: true, replace: true },
      };
      patched = true;
      break;
    }
    if (!patched) {
      _events.push({
        kind: 'outline',
        text: body,
        meta: { ...meta, field, slot: key, upgrade: true, replace: true },
      });
    }
    if (typeof opts.onSlotReplace === 'function') {
      opts.onSlotReplace(key, body, { ...meta, field, slot: key });
    }
    scrollBottom();
    return true;
  }

  function _dispatchEvent(kind, text, meta = {}) {
    const isSlotUpgrade = (
      (kind === 'outline' || resolveRenderField(kind, meta) === 'outline')
      && Boolean(meta?.upgrade || meta?.replace)
      && String(meta?.slot || '').trim()
    );
    if (_finalized && !isSlotUpgrade) return;
    if (isSlotUpgrade && _replaceSlotContent(meta.slot, text, meta)) return;
    if (_finalized) return;
    const eventStamp = String(meta?.created_at ?? '').trim();
    if (eventStamp && !_createdAt) ctrl.setCreatedAt(eventStamp);
    const field = resolveRenderField(kind, meta);
    switch (kind) {
      case 'agent_typing':
        if (Number(meta.render_time_ms) > 0 || Number(meta.wait_ms) > 0) _showRenderSpinner(meta);
        else if (meta.active === false || meta.active === 'false') _hideTypingIndicator();
        else _showTypingIndicator();
        break;
      case 'tag':
        if (meta.tag === 'think' || field === 'thought') {
          // think 隐藏
          break;
        } else if (meta.tag === 'speak' || field === 'speak') {
          _ensureFieldBlock('speak', 'speak', meta);
        } else if (meta.tag === 'action' || field === 'body') {
          _ensureFieldBlock('body', 'action', meta);
        }
        break;
      case 'chunk':
        // 旧 chunk=think 流；隐藏后不再建占位
        break;
      case 'thought':
        break;
      case 'action':
      case 'state':
      case 'observe':
      case 'outline':
      case 'anchor':
      case 'speak':
      case 'segment':
      case 'finish':
        _renderByField(kind, text, meta);
        break;
      case 'error':
        _commitField('body', 'action', text || 'error', { field: 'body' });
        break;
      default:
        if (field) _renderByField(kind, text, meta);
        break;
    }
  }

  function _packetWaitMs(meta = {}) {
    const renderMs = Number(meta[META_RENDER_TIME_MS] ?? meta.render_time_ms);
    const waitMs = Number(meta[META_WAIT_MS] ?? meta.wait_ms);
    const a = Number.isFinite(renderMs) && renderMs > 0 ? renderMs : 0;
    const b = Number.isFinite(waitMs) && waitMs > 0 ? waitMs : 0;
    return Math.max(a, b);
  }

  function _notifyIdle() {
    if (_pumping || _playQueue.length) return;
    const waiters = _idleWaiters;
    _idleWaiters = [];
    for (const resolve of waiters) resolve();
  }

  function _waitUntilIdle() {
    if (!_pumping && !_playQueue.length) return Promise.resolve();
    return new Promise((resolve) => {
      _idleWaiters.push(resolve);
    });
  }

  async function _playPacket(pkt) {
    if (_stopped) return;
    const field = pkt.field;
    if (field === 'thought' || field === 'finish') return;

    if (field === 'typing') {
      _showRenderSpinner(pkt.meta);
      return;
    }

    if (_isDuplicateContent(field, pkt.text, pkt.meta)) return;
    _hideRenderSpinner();
    // 内容驱动打字指示：第一个可见内容包真正到达才点亮"对方正在输入"，
    // 沉默/延迟的回合全程不显示（finalize/discard 时由 _hideTypingIndicator 熄灭）。
    _showTypingIndicator();
    _dispatchEvent(pkt.kind, pkt.text, pkt.meta);
  }

  async function _pumpQueue() {
    if (_pumping || _stopped) return;
    _pumping = true;
    while (_playQueue.length && !_stopped) {
      const pkt = _playQueue.shift();
      await _playPacket(pkt);
      // 逐条渲染节奏：按服务端给定的渲染时长等待后再放下一包。
      // 没有这一步，批量到达的 speak 会在同一瞬间全部弹出。
      const pace = Math.min(Math.max(Number(pkt.waitMs) || 0, 0), _PACE_CAP_MS);
      if (pace > 0) {
        await new Promise((resolve) => setTimeout(resolve, pace));
      }
    }
    _pumping = false;
    if (_playQueue.length && !_stopped) {
      _pumpQueue();
      return;
    }
    _notifyIdle();
  }

  function _enqueuePacket(kind, text, meta = {}) {
    if (kind === 'tag' || kind === 'chunk') return;
    if (kind === 'error') {
      _acceptedLive = true;
      _playQueue.push({ kind, text, meta, field: 'body', waitMs: 0 });
      _pumpQueue();
      return;
    }
    const field = resolveRenderField(kind, meta) || _fieldKey(kind, meta);
    if (!field || field === 'thought' || field === 'finish' || field === 'silence' || field === 'wait') return;
    const body = String(text ?? '').trim();
    if ((field === 'speak' || field === 'body' || field === 'observe' || field === 'outline') && !body) return;
    if ((field === 'speak' || field === 'body') && _isDuplicateContent(field, body, meta)) return;
    _acceptedLive = true;
    _playQueue.push({
      kind,
      text,
      meta,
      field,
      waitMs: (field === 'body' || field === 'speak' || field === 'outline' || field === 'observe')
        ? _packetWaitMs(meta)
        : 0,
    });
    _pumpQueue();
  }

  const ctrl = {
    el,
    get _finalized() { return _finalized; },
    setCreatedAt(iso) {
      const stamp = String(iso ?? '').trim();
      if (!stamp) return;
      _createdAt = stamp;
      timeEl.textContent = ts(stamp);
    },
    get createdAt() { return _createdAt; },
    get hasLiveInput() {
      return _acceptedLive || _events.length > 0 || _playQueue.length > 0;
    },
    onEvent(kind, text, meta = {}) {
      const isSlotUpgrade = (
        kind === 'outline'
        && Boolean(meta?.upgrade || meta?.replace)
        && String(meta?.slot || '').trim()
      );
      if (_stopped && !isSlotUpgrade) return;
      if (_finalized && !isSlotUpgrade) return;
      const eventStamp = String(meta?.created_at ?? '').trim();
      if (eventStamp && !_createdAt) ctrl.setCreatedAt(eventStamp);
      _enqueuePacket(kind, text, meta);
    },
    async finalize(answer, aborted = false, replayEvents = null) {
      _hideTypingIndicator();
      if (aborted) {
        _stopped = true;
        _playQueue.length = 0;
      }

      if (
        !_acceptedLive
        && !_events.length
        && !_playQueue.length
        && Array.isArray(replayEvents)
        && replayEvents.length
      ) {
        for (const ev of sortEventsByOrder(replayEvents)) {
          ctrl.onEvent(ev.kind, ev.text ?? '', ev.meta ?? {});
        }
      }

      await _waitUntilIdle();
      _hideRenderSpinner();

      if (_thinkPending) {
        _thinkPending.wrap.remove();
        _thinkPending = null;
      }
      _closeOpenBlock();

      const finalText = (_speakParts.join('') || String(answer ?? '')).trim();
      // 已有分字段事件时绝不再整段 dump answer
      if (!_events.length && finalText && !aborted) {
        _commitField('speak', 'speak', finalText, { field: 'speak' });
      }

      if (_createdAt) timeEl.textContent = ts(_createdAt);

      if (aborted) {
        const note = document.createElement('div');
        note.className = 'speak-abort-note';
        note.textContent = '⊘ aborted';
        streamCol.appendChild(note);
      } else if (finalText) {
        ttsBtn.classList.remove('hidden');
        ttsBtn.dataset.text = finalText;
      }
      _finalized = true;
      if (_isHollowSpeakMsg(div)) {
        div.remove();
        return;
      }
      scrollBottom();
    },
    discardAgentTurn() {
      _stopped = true;
      _finalized = true;
      _playQueue.length = 0;
      _notifyIdle();
      _hideTypingIndicator();
      _hideRenderSpinner();
      div.remove();
      _openBlock = null;
      _thinkPending = null;
      _speakParts = [];
      _events = [];
    },
    get speakText() { return _speakParts.join(''); },
    get events() { return _events; },
    replaceSlot(slot, text, meta = {}) {
      return _replaceSlotContent(slot, text, meta);
    },
  };
  return ctrl;
}

/** 就地替换已渲染的 outline 占位（可跨回合、已 finalize）。 */
export function replaceOutlineSlot(slot, text, meta = {}) {
  const key = String(slot || '').trim();
  const body = String(text ?? '').trim();
  if (!key || !body) return false;
  const wrap = document.querySelector(`.speak-field[data-slot="${CSS.escape(key)}"]`);
  if (!wrap) return false;
  const content = wrap.querySelector('.speak-field-content');
  if (!content) return false;
  content.textContent = body;
  wrap.classList.remove('streaming', 'speak-outline-placeholder');
  if (meta?.placeholder) wrap.classList.add('speak-outline-placeholder');
  return true;
}
