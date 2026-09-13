/**
 * features/speak_admin.js — Speak 会话管理与诊断（trace / debug / reset / status）。
 */

import { API } from '../protocol/http_api.js';
import { http } from '../transport/http.js';
import * as sessionStore from '../store/session_store.js';

export async function fetchStatus() {
  return http.get(API.speak.status);
}

export async function getSessionTrace(sessionId) {
  const sid = String(sessionId ?? '').trim();
  if (!sid) return { enabled: false };
  return http.get(API.speak.trace(sid));
}

export async function setSessionTrace(sessionId, enabled) {
  const sid = String(sessionId ?? '').trim();
  if (!sid) throw new Error('missing session_id');
  return http.post(API.speak.traceSet, { session_id: sid, enabled: Boolean(enabled) });
}

export async function fetchSessionDebug(sessionId) {
  const sid = String(sessionId ?? '').trim();
  if (!sid) throw new Error('missing session_id');
  return http.get(API.speak.debug(sid));
}

/** 重置指定后端 Speak session（不影响其它历史线程）。 */
export async function resetSession(sessionId) {
  const sid = String(sessionId ?? '').trim();
  if (!sid) throw new Error('missing session_id');
  return http.post(API.speak.reset, { session_id: sid });
}

/** 就绪轮询：Soul/Speak readiness 为 WebUI 主就绪信号。 */
export async function pollUntilSpeakReady(timeoutMs = 120_000, intervalMs = 800) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const data = await fetchStatus().catch(() => ({ ready: false }));
    const ready = Boolean(data.ready);
    sessionStore.update({ speakReady: ready });
    if (ready) return data;
    await new Promise(r => setTimeout(r, intervalMs));
  }
  throw new Error('Speak backend not ready');
}
