/**
 * modules/notify.js — Speak/WebUI notification channel.
 *
 * Subscribes to GET /api/speak/notify (SSE) and exposes onShow / onHide
 * callbacks so main.js can update the #notify-bar without this module
 * touching the DOM directly.
 *
 * Usage (main.js):
 *   import * as notifyMod from './modules/notify.js';
 *   notifyMod.setCallbacks({ onShow, onHide });
 *   notifyMod.connect();
 */

import { PATHS } from '../api.js';

const _cb = {
  onShow: (_message, _isDone) => {},
  onHide: () => {},
  onScheduledReply: (_taskName, _answer) => {},
  onAgentMessage: (_title, _message, _taskName) => {},
  onProactiveAvailable: (_payload) => {},
  onCreateUiRequest: (_payload) => {},
};

export function setCallbacks(cbs) { Object.assign(_cb, cbs); }

let _es = null;
let _reconnectTimer = null;
let _channelId = '';

/**
 * Open the SSE connection.  Safe to call multiple times — reconnects if the
 * previous connection was closed.
 */
export function connect(channelId = _channelId) {
  const nextChannel = String(channelId ?? '').trim();
  if (_es && _channelId === nextChannel && _es.readyState !== EventSource.CLOSED) return;
  if (_es && _channelId !== nextChannel) {
    _es.close();
    _es = null;
  }
  _channelId = nextChannel;
  if (_reconnectTimer) {
    clearTimeout(_reconnectTimer);
    _reconnectTimer = null;
  }
  const query = _channelId ? `?channel_id=${encodeURIComponent(_channelId)}` : '';
  _es = new EventSource(`${PATHS.speak.notify}${query}`);
  _es.onmessage = _handleMessage;
  _es.onerror   = () => {
    if (_es?.readyState !== EventSource.CLOSED || _reconnectTimer) return;
    _es = null;
    _reconnectTimer = setTimeout(connect, 1000);
  };
}

export function disconnect() {
  if (_reconnectTimer) {
    clearTimeout(_reconnectTimer);
    _reconnectTimer = null;
  }
  _es?.close();
  _es = null;
}

// ── Internal ──────────────────────────────────────────────────────────────────

let _hideTimer = null;

function _handleMessage(evt) {
  let msg;
  try { msg = JSON.parse(evt.data); } catch { return; }

  if (msg.type === 'scheduled_reply') {
    _cb.onScheduledReply(msg.task_name ?? '', msg.answer ?? '');
    return;
  }

  if (msg.type === 'agent_message') {
    _cb.onAgentMessage(msg.title ?? '', msg.message ?? '', msg.task_name ?? '');
    return;
  }

  if (msg.type === 'proactive_available') {
    _cb.onProactiveAvailable({ ...msg, ...(msg.metadata ?? {}) });
    return;
  }

  if (msg.type === 'create_ui_request') {
    _cb.onCreateUiRequest({ ...msg, ...(msg.metadata ?? {}) });
    return;
  }

  if (msg.type !== 'notify') return;

  clearTimeout(_hideTimer);

  if (msg.done) {
    _cb.onShow(msg.message, true);
    _hideTimer = setTimeout(() => _cb.onHide(), 1500);
  } else {
    _cb.onShow(msg.message, false);
  }
}
