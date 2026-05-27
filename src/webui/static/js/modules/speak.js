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

export async function resetSession(sessionId = 'webui') {
  await http.post(PATHS.speak.reset, { session_id: sessionId });
  _cb.onToast('Speak session reset');
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
