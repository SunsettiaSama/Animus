/**
 * modules/speak.js — Soul Speak 就绪状态（WebUI 主对话通道）。
 */

import { http, PATHS } from '../api.js';
import { S, set } from '../state.js';

const _cb = {
  onToast: () => {},
  onReady: () => {},
  onError: () => {},
  onStatusUpdate: () => {},
};

export function setCallbacks(cbs) {
  Object.assign(_cb, cbs);
}

export async function fetchStatus() {
  const data = await http.get(PATHS.speak.status);
  const ready = Boolean(data.ready);
  set('speakReady', ready);
  _cb.onStatusUpdate(data);
  return data;
}

export async function getSessionTrace(sessionId) {
  const sid = String(sessionId ?? '').trim();
  if (!sid) return { enabled: false };
  return http.get(PATHS.speak.trace(sid));
}

export async function setSessionTrace(sessionId, enabled) {
  const sid = String(sessionId ?? '').trim();
  if (!sid) throw new Error('missing session_id');
  return http.post(PATHS.speak.traceSet, { session_id: sid, enabled: Boolean(enabled) });
}

export async function fetchSessionDebug(sessionId) {
  const sid = String(sessionId ?? '').trim();
  if (!sid) throw new Error('missing session_id');
  return http.get(PATHS.speak.debug(sid));
}

export async function resetSession(sessionId) {
  const sid = String(sessionId ?? '').trim();
  if (!sid) {
    throw new Error('missing session_id');
  }
  const data = await http.post(PATHS.speak.reset, { session_id: sid });
  if (data?.ok) _cb.onToast('对话已重置');
  return data;
}

export async function pollUntilReady(timeoutMs = 120_000, intervalMs = 800) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const data = await fetchStatus().catch(() => ({ ready: false }));
    if (data.ready) return data;
    await new Promise(r => setTimeout(r, intervalMs));
  }
  throw new Error('Speak backend not ready');
}
