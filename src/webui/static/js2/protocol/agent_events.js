/**
 * protocol/agent_events.js — 入站帧解析 → 类型化事件（纯函数，零依赖）。
 *
 * 服务端出站帧清单见 docs/webui/README.md。本层负责：
 * 1. gen_id 陈旧帧过滤（work_* 帧豁免 —— 可跨流到达）；
 * 2. 识别 work_* 帧；
 * 3. 提取 proactive 投递元数据（delivery_id / agent_initiated 等），
 *    供去重与 ack 使用；不出现在帧里时回退查 meta。
 *
 * 解析结果仅供 transport/agent_channel.js 消费，UI 不接触原始帧对象以外的
 * 未类型化结构。
 */

export const WORK_FRAME_PREFIX = 'work_';

export const WORK_EVENT_TYPES = Object.freeze([
  'work_intent_detected',
  'work_confirmation_required',
  'work_declined',
  'work_started',
  'work_progress',
  'work_monitor',
  'work_finished',
  'work_failed',
  'work_aborted',
  'work_fallback_to_speak',
]);

/** 已终态的 work 状态（对应后端 WorkStatus 状态机的终点）。 */
export const WORK_TERMINAL_STATUSES = Object.freeze([
  'finished', 'failed', 'aborted', 'declined', 'fallback_to_speak',
]);

/**
 * 帧是否陈旧（gen 不匹配且非 work 帧）。
 * @param {{type?: string, gen_id?: string}} msg
 * @param {string} expectedGenId
 */
export function isStaleFrame(msg, expectedGenId) {
  const gid = String(msg?.gen_id ?? '');
  if (!gid || gid === expectedGenId) return false;
  return !isWorkFrame(msg);
}

export function isWorkFrame(msg) {
  return String(msg?.type ?? '').startsWith(WORK_FRAME_PREFIX)
    && WORK_EVENT_TYPES.includes(String(msg?.type));
}

function _deliveryIdFromMeta(meta) {
  if (meta && typeof meta === 'object') {
    return String(meta.delivery_id ?? '').trim();
  }
  return '';
}

/** 从 turn_start / speak_event / turn_finish 帧提取 proactive delivery_id。 */
export function extractDeliveryId(msg) {
  if (!msg || typeof msg !== 'object') return '';
  const top = String(msg.delivery_id ?? '').trim();
  if (top) return top;
  return _deliveryIdFromMeta(msg.meta);
}

/**
 * 单帧 → 分类事件。返回 null 表示"连接层可忽略"（陈旧帧）。
 *
 * 返回形如：
 *   { kind: 'speak_event', event: {...原始帧} }
 *   { kind: 'turn_start', event, meta: { deliveryId } }
 *   { kind: 'turn_finish', event, meta: { deliveryId } }
 *   { kind: 'work', event: {type:'work_confirmation_required', workId, status, ...} }
 *   ...
 */
export function classifyAgentFrame(rawMsg, expectedGenId = '') {
  if (!rawMsg || typeof rawMsg !== 'object') return null;
  if (isStaleFrame(rawMsg, expectedGenId)) return null;

  const type = String(rawMsg.type ?? '');

  if (isWorkFrame(rawMsg)) {
    return {
      kind: 'work',
      event: {
        type,
        workId: String(rawMsg.work_id ?? ''),
        status: String(rawMsg.status ?? ''),
        message: String(rawMsg.message ?? ''),
        payload: (rawMsg.payload && typeof rawMsg.payload === 'object') ? rawMsg.payload : {},
        reason: String(rawMsg.reason ?? ''),
        reasonCode: String(rawMsg.reason_code ?? ''),
        seq: Number(rawMsg.seq || 0),
        createdAt: String(rawMsg.created_at ?? ''),
        sessionId: String(rawMsg.session_id ?? ''),
        raw: rawMsg,
      },
    };
  }

  switch (type) {
    case 'session_ready':
    case 'route_decision':
    case 'route_pierce_ok':
    case 'typing_ack':
    case 'typing_idle_ms':
    case 'pong':
    case 'aborted':
    case 'proactive_ack_ok':
    case 'session_end':
      return { kind: type, event: rawMsg };

    case 'error': {
      const event = { message: String(rawMsg.message ?? '') , raw: rawMsg };
      return { kind: 'error', event };
    }

    case 'turn_start': {
      const meta = { deliveryId: extractDeliveryId(rawMsg) };
      return { kind: 'turn_start', event: rawMsg, meta };
    }

    case 'speak_event': {
      const event = {
        kind: String(rawMsg.kind ?? ''),
        text: String(rawMsg.text ?? ''),
        final: Boolean(rawMsg.final),
        renderMeta: (rawMsg.meta && typeof rawMsg.meta === 'object') ? rawMsg.meta : {},
        deliveryId: extractDeliveryId(rawMsg),
        raw: rawMsg,
      };
      return { kind: 'speak_event', event };
    }

    case 'turn_finish': {
      const meta = { deliveryId: extractDeliveryId(rawMsg) };
      return { kind: 'turn_finish', event: rawMsg, meta };
    }

    default:
      // 未知帧：交上层记日志并忽略，不抛错（前后端版本错位时保持健壮）。
      return { kind: 'unknown', event: rawMsg };
  }
}
