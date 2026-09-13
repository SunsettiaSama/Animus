/**
 * features/proactive.js — 主动消息通知通道（SSE 唤醒）。
 *
 * 订阅 /api/speak/notify；proactive_available / create_ui_request 经
 * 串行链依次交给 conversation 开窗，避免多个主动会话切换相互覆盖。
 */

import { API } from '../protocol/http_api.js';
import { openSse } from '../transport/http.js';
import { bus, EVENTS } from '../store/bus.js';

let _sse = null;
let _reconnectTimer = null;
let _channelId = '';

let _onProactiveAvailable = null;
let _onCreateUiRequest = null;

/** app 装配时注入开窗处理器（features/conversation 的两个入口）。 */
export function configure({ onProactiveAvailable, onCreateUiRequest } = {}) {
  if (typeof onProactiveAvailable === 'function') _onProactiveAvailable = onProactiveAvailable;
  if (typeof onCreateUiRequest === 'function') _onCreateUiRequest = onCreateUiRequest;
}

/**
 * 打开 SSE。channel 变化或断线时自动重连。
 */
export function connect(channelId = _channelId) {
  const nextChannel = String(channelId ?? '').trim();
  if (_sse && _channelId === nextChannel) return;
  if (_sse) {
    _sse.close();
    _sse = null;
  }
  _channelId = nextChannel;
  if (_reconnectTimer) {
    clearTimeout(_reconnectTimer);
    _reconnectTimer = null;
  }
  const query = _channelId ? `?channel_id=${encodeURIComponent(_channelId)}` : '';
  // EventSource 断线自动重试；此处仅做错误可见性，不需要手动重连循环。
  _sse = openSse(`${API.speak.notify}${query}`, {
    onEvent: msg => _handleMessage(msg),
  });
}

export function disconnect() {
  if (_reconnectTimer) {
    clearTimeout(_reconnectTimer);
    _reconnectTimer = null;
  }
  _sse?.close();
  _sse = null;
}

// ── Internal ────────────────────────────────────────────────────────────────

let _hideTimer = null;

function _handleMessage(msg) {
  if (!msg || typeof msg !== 'object') return;

  switch (msg.type) {
    case 'scheduled_reply':
      bus.emit('notify:scheduled_reply', msg);
      return;
    case 'agent_message':
      bus.emit('notify:agent_message', msg);
      return;
    case 'proactive_available': {
      const payload = { ...msg, ...(msg.metadata ?? {}) };
      bus.emit(EVENTS.proactiveNotify, payload);
      _onProactiveAvailable?.(payload);
      return;
    }
    case 'create_ui_request': {
      const payload = { ...msg, ...(msg.metadata ?? {}) };
      bus.emit(EVENTS.proactiveNotify, payload);
      _onCreateUiRequest?.(payload);
      return;
    }
    case 'notify': {
      bus.emit('notify:show', msg);
      return;
    }
    default:
      return;
  }
}
