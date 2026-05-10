/**
 * modules/notify.js — Background task notification channel.
 *
 * Subscribes to GET /api/react/notify (SSE) and exposes onShow / onHide
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
};

export function setCallbacks(cbs) { Object.assign(_cb, cbs); }

let _es = null;

/**
 * Open the SSE connection.  Safe to call multiple times — reconnects if the
 * previous connection was closed.
 */
export function connect() {
  if (_es && _es.readyState !== EventSource.CLOSED) return;
  _es = new EventSource(PATHS.react.notify);
  _es.onmessage = _handleMessage;
  _es.onerror   = () => {
    _es?.close();
    _es = null;
  };
}

export function disconnect() {
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

  if (msg.type !== 'notify') return;

  clearTimeout(_hideTimer);

  if (msg.done) {
    _cb.onShow(msg.message, true);
    _hideTimer = setTimeout(() => _cb.onHide(), 1500);
  } else {
    _cb.onShow(msg.message, false);
  }
}
