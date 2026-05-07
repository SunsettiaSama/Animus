/**
 * eventBus.js — Centralised pub/sub hub for cross-module communication.
 *
 * Replaces the mixed pattern of:
 *   - module.setCallbacks({ onToast, ... })
 *   - document.dispatchEvent(new CustomEvent('react:state', ...))
 *
 * Usage:
 *   import { bus } from './eventBus.js';
 *   bus.on('toast',      msg => showToast(msg));
 *   bus.emit('toast',    'Hello!');
 *   bus.off('toast',     fn);
 *
 * Built-in event names (convention — not enforced):
 *   'toast'          payload: string
 *   'react:state'    payload: { busy, step, phase }
 *   'react:update'   payload: { convId, title }
 *   'navigate'       payload: screenId string
 *   'screen:enter'   payload: screenId string
 */

const _listeners = new Map();

function on(event, fn) {
  if (!_listeners.has(event)) _listeners.set(event, new Set());
  _listeners.get(event).add(fn);
}

function off(event, fn) {
  _listeners.get(event)?.delete(fn);
}

function emit(event, payload) {
  _listeners.get(event)?.forEach(fn => {
    fn(payload);
  });
}

function once(event, fn) {
  const wrapper = (payload) => { fn(payload); off(event, wrapper); };
  on(event, wrapper);
}

export const bus = { on, off, emit, once };
