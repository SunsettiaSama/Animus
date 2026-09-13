/**
 * transport/http.js — REST 封装 + SSE 助手 + WebSocket 工厂。
 *
 * 仅依赖 protocol/http_api.js 的路径表；调用方永远不接触 fetch/EventSource 细节。
 */

const _JSON_H = { 'Content-Type': 'application/json' };
export const WS_BASE = `${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}`;

import { API } from '../protocol/http_api.js';

async function _checkJson(r) {
  if (!r.ok) {
    let msg = `HTTP ${r.status}`;
    try { const d = await r.json(); msg = d.error || d.detail || msg; } catch { /* keep status text */ }
    throw new Error(msg);
  }
  return r.json();
}

/** 解析为 JSON 失败时返回原始文本（SSE 兼容端点等场景）。 */
async function _checkOk(r) {
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  const text = await r.text();
  try { return JSON.parse(text); } catch { return text; }
}

export const http = {
  get:   path => fetch(path).then(_checkJson),
  post:  (path, body = {}) => fetch(path, { method: 'POST', headers: _JSON_H, body: JSON.stringify(body) }).then(_checkJson),
  patch: (path, body = {}) => fetch(path, { method: 'PATCH', headers: _JSON_H, body: JSON.stringify(body) }).then(_checkJson),
  del:   path => fetch(path, { method: 'DELETE' }).then(_checkJson),

  /** 非 JSON 响应也接受（返回 parsed-JSON-or-text）。 */
  getRaw: path => fetch(path).then(_checkOk),

  /** POST with FormData（文件上传）— 不设置 Content-Type。 */
  upload: (path, formData) => fetch(path, { method: 'POST', body: formData }).then(_checkJson),
};

/**
 * 订阅一个 SSE 端点并统一错误/重连策略。
 *
 * @param {string} url
 * @param {{ onEvent?: (data:any)=>void, onOpen?: ()=>void,
 *          onError?: (err:Event|null)=>void }} handlers
 * @param {{ retryMs?: number }} [opts] 重连节流；EventSource 自身会自动重试，
 *        这里仅做错误回调与关闭包装。
 * @returns {{ close: ()=>void }}
 */
export function openSse(url, handlers = {}, opts = {}) {
  const es = new EventSource(url);
  let closed = false;
  let lastErrorAt = 0;
  const retryMs = opts.retryMs ?? 2000;

  es.onopen = () => {
    if (closed) return;
    handlers.onOpen?.();
  };

  es.onmessage = evt => {
    if (closed) return;
    let data = null;
    try { data = JSON.parse(evt.data); } catch { data = evt.data; }
    handlers.onEvent?.(data);
  };

  es.onerror = err => {
    if (closed) return;
    // EventSource 会自动重连；只把错误转发给上层，并用时间窗抑制告警风暴。
    const now = Date.now();
    if (now - lastErrorAt > retryMs) {
      lastErrorAt = now;
      handlers.onError?.(err);
    }
  };

  return {
    close() {
      closed = true;
      es.close();
    },
  };
}

export function wsFactory(path) {
  return new WebSocket(`${WS_BASE}${path}`);
}

/**
 * 就绪轮询：Soul/Speak readiness 为 WebUI 主就绪信号。
 */
export async function pollUntilSpeakReady(intervalMs = 500, timeoutMs = 120_000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const readiness = await http.get(API.soul.readiness).catch(() => null);
    if (readiness?.speak_ready) return readiness;
    await new Promise(r => setTimeout(r, intervalMs));
  }
  throw new Error('Soul/Speak ready check timed out');
}
