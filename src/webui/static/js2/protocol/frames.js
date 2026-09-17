/**
 * protocol/frames.js — 出站帧构造器（纯函数，零依赖）。
 *
 * 帧信封约定（与后端 routers/agent.py 读取的字段一致）：
 * - gen_id      流代际令牌（必填；服务端一次只允许一个流）
 * - session_id  会话身份 / 粘性路由键
 * - channel_id  浏览器通道身份（hub 投递匹配键），session_open 时携带
 * - delivery_mode / pipeline 在 session_open 声明后由服务端记住
 *
 * 业务代码不得手工拼帧：所有 client→server 帧从这里构造。
 */

export const DELIVERY_MODES = Object.freeze(['stream', 'simulated']);
export const DEFAULT_PIPELINE = 'request_driven';
export const ROUTE_SPEAK = 'speak';
export const ROUTE_WORK = 'work';

/**
 * 会话信封。AgentChannel 持有一份并向本层函数传递。
 * @typedef {Object} Envelope
 * @property {string} genId
 * @property {string} sessionId
 * @property {string} [channelId]
 * @property {string} [deliveryMode]
 * @property {string} [pipeline]
 */
function _env(env) {
  return {
    gen_id: String(env?.genId ?? ''),
    session_id: String(env?.sessionId ?? ''),
  };
}

/** 首帧。必须是连接上的第一帧，否则服务端关闭连接。 */
export function sessionOpen(env) {
  return {
    type: 'session_open',
    ..._env(env),
    channel_id: String(env?.channelId || env?.sessionId || ''),
    delivery_mode: DELIVERY_MODES.includes(env?.deliveryMode) ? env.deliveryMode : 'stream',
    pipeline: String(env?.pipeline || DEFAULT_PIPELINE),
  };
}

export function userMessage(question, env) {
  return {
    type: 'user_message',
    question: String(question ?? '').trim(),
    ..._env(env),
  };
}

/** 会话中途切换 pipeline（request_driven | direct）；服务端复检收敛门。 */
export function setPipeline(pipeline, env) {
  return {
    type: 'pipeline',
    ..._env(env),
    pipeline: String(pipeline || ''),
  };
}

export function typingPulse(typing, draft, env) {
  return {
    type: 'typing_pulse',
    typing: Boolean(typing),
    draft: String(draft ?? ''),
    ..._env(env),
  };
}

export function setTypingIdleMs(ms, env) {
  const n = Number(ms);
  return {
    type: 'set_typing_idle_ms',
    typing_idle_ms: Number.isFinite(n) ? n : 3000,
    ..._env(env),
  };
}

export function ping(env) {
  return { type: 'ping', ..._env(env) };
}

export function abort(env) {
  // 服务端校验 abort.gen_id 必须等于连接的 gen_id —— 不带其余信封字段。
  return { type: 'abort', gen_id: String(env?.genId ?? '') };
}

export function proactiveAck(deliveryId, env) {
  const id = String(deliveryId ?? '').trim();
  if (!id) throw new Error('proactive_ack requires delivery_id');
  return { type: 'proactive_ack', delivery_id: id, ..._env(env) };
}

export function workConfirmationResponse({ workId, approved, reason = '', reasonCode = '' }, env) {
  const id = String(workId ?? '').trim();
  if (!id) throw new Error('work_confirmation_response requires work_id');
  return {
    type: 'work_confirmation_response',
    work_id: id,
    approved: Boolean(approved),
    reason: String(reason ?? ''),
    reason_code: String(reasonCode ?? ''),
    ..._env(env),
  };
}

export function workAbort(workId, env, reason = '') {
  const id = String(workId ?? '').trim();
  if (!id) throw new Error('work_abort requires work_id');
  const frame = { type: 'work_abort', work_id: id, ..._env(env) };
  if (reason) frame.reason = String(reason);
  return frame;
}

export function workMonitorRequest(workId, env) {
  const id = String(workId ?? '').trim();
  if (!id) throw new Error('work_monitor_request requires work_id');
  return { type: 'work_monitor_request', work_id: id, ..._env(env) };
}

export function routePierce(trueRoute, env, extra = {}) {
  const route = String(trueRoute ?? '').trim();
  if (!route) throw new Error('route_pierce requires true_route');
  return {
    type: 'route_pierce',
    true_route: route,
    ...extra,
    ..._env(env),
  };
}

/** 从 Envelope 提取最小信封字段（gen_id + session_id），供动态 payload 帧使用。 */
export function briefEnv(env) {
  return _env(env);
}

/** 客户端主动断开时发送（尽力而为，连接可能已死）。 */
export function close(env) {
  return { type: 'close', gen_id: String(env?.genId ?? '') };
}
