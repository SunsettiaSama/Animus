/**
 * transport/agent_channel.js — Agent 会话通道（实例级，可并发持有多个）。
 *
 * 对上（features/store）暴露「回合与事件」的语义接口；对下把帧收发交给
 * WsConnection，把构造与解析分别委托给 protocol/frames.js 与 agent_events.js。
 *
 * 并发约定：gen_id / 重连 epoch / turn waiter 队列全部是实例状态。
 * 第二个会话应 new 另一个 AgentChannel，而不是复用单例。
 */

import { WS_PATHS } from '../protocol/http_api.js';
import * as frames from '../protocol/frames.js';
import {
  classifyAgentFrame,
  WORK_TERMINAL_STATUSES,
} from '../protocol/agent_events.js';
import { WsConnection, TypingPulseDriver } from './ws_session.js';

export const SPEAK_TYPING_PULSE_MS = 500;
const ALLOWED_TYPING_IDLE_MS = Object.freeze([3000, 5000]);

function _noop() {}

/**
 * @typedef {Object} AgentChannelOptions
 * @property {string} sessionId   会话身份（粘性路由键）
 * @property {string} [channelId] 浏览器通道身份；默认取 sessionId
 * @property {'stream'|'simulated'} [deliveryMode]
 * @property {string} [pipeline]
 * @property {number} [typingIdleMs] 3000 或 5000
 * @property {()=>string} [getDraft] 输入草稿读取器（供 typing_pulse）
 */

export class AgentChannel {
  /** @param {string} genId 流代际令牌 */
  constructor(genId, opts = {}) {
    this._env = {
      genId: String(genId),
      sessionId: String(opts.sessionId ?? 'webui'),
      channelId: String(opts.channelId || opts.sessionId || 'webui'),
      deliveryMode: 'stream',
      pipeline: frames.DEFAULT_PIPELINE,
    };

    this._handlers = this._defaultHandlers();
    this._typingIdleMs = ALLOWED_TYPING_IDLE_MS.includes(opts.typingIdleMs)
      ? opts.typingIdleMs : 3000;
    this._getDraft = typeof opts.getDraft === 'function' ? opts.getDraft : () => '';

    this._pulse = new TypingPulseDriver(SPEAK_TYPING_PULSE_MS, (typing, draft) => {
      this.sendFrame(frames.typingPulse(typing, draft, this._env));
    });

    this._conn = new WsConnection(WS_PATHS.agentRun, {
      onOpen: () => {
        this.sendFrame(frames.sessionOpen(this._env));
        this.sendTypingIdleMs();
        this._pulse.start(this._getDraft);
      },
      onMessage: frame => this._onFrame(frame),
      onClose: () => {
        this._pulse.stop();
        while (this._turnWaiters.length) {
          this._turnWaiters.shift()?.({ type: 'disconnected' });
        }
      },
      onError: err => this._handlers.onError(err),
    });

    // 回合等待队列：sendTurn 与其 finish/work_pending/error 一一配对。
    this._turnWaiters = [];

    // 主动消息去重：已确认过的 delivery 断线重推不再渲染。
    this._completedProactive = new Set();
    this._proactiveWaiters = new Map();     // delivery_id → resolver
    this._suppressProactiveId = '';
  }

  _defaultHandlers() {
    return {
      onSessionReady: _noop,     // ({...session_ready})
      onTurnStart: _noop,        // ({event, meta:{deliveryId}})
      onSpeakEvent: _noop,       // ({kind,text,final,renderMeta,deliveryId})
      onTurnFinish: _noop,       // (turn_finish 帧)
      onRouteDecision: _noop,
      onRoutePierceOk: _noop,
      onWorkEvent: _noop,        // 类型化 work 事件（见 agent_events.classifyAgentFrame）
      onTypingAck: _noop,
      onAborted: _noop,
      onSessionEnd: _noop,
      onError: _noop,
      onUnknown: _noop,          // 未识别帧（版本错位时保持健壮）
    };
  }

  /** 更新回调。只覆盖传入键，其余保持不变。 */
  setHandlers(handlers = {}) {
    for (const key of Object.keys(this._handlers)) {
      if (typeof handlers[key] === 'function') this._handlers[key] = handlers[key];
    }
  }

  // ── 状态查询 ───────────────────────────────────────────────────────────────

  isConnected() { return this._conn.connected; }
  get sessionId() { return this._env.sessionId; }
  get channelId() { return this._env.channelId; }
  /** 当前流代际（出站帧信封用）。 */
  get genId() { return this._env.genId; }

  // ── 出站 ───────────────────────────────────────────────────────────────────

  /** 发送一个由 protocol/frames.js 构造好的帧。 */
  sendFrame(frame) { return this._conn.send(frame); }

  /** 发送 worker 确认域任意信封帧（兼容遗留 payload 调用点）。 */
  sendWorkFrame(payload) {
    if (!payload || typeof payload !== 'object') return false;
    if (!this.isConnected()) return false;
    return this.sendFrame({ ...payload, ...frames.briefEnv(this._env) });
  }

  setTypingIdleMs(ms) {
    const want = Number(ms);
    this._typingIdleMs = ALLOWED_TYPING_IDLE_MS.includes(want) ? want : 3000;
    this.sendTypingIdleMs();
  }

  sendTypingIdleMs() {
    this.sendFrame(frames.setTypingIdleMs(this._typingIdleMs, this._env));
  }

  ping() { this.sendFrame(frames.ping(this._env)); }

  /** 终止当前流（服务端会以 `aborted` 应答）。 */
  abort() {
    this._pulse.stop();
    this.sendFrame(frames.abort(this._env));
  }

  acknowledgeProactive(deliveryId) {
    const id = String(deliveryId ?? '').trim();
    if (!id) return false;
    // 本地先记完成：断线时 ack 发不出去，重连重推也不得再渲染。
    this._completedProactive.add(id);
    const resolver = this._proactiveWaiters.get(id);
    if (resolver) {
      this._proactiveWaiters.delete(id);
      resolver();
    }
    if (!this.isConnected()) return false;
    this.sendFrame(frames.proactiveAck(id, this._env));
    return true;
  }

  /** 已被 ack 过的 delivery 不再阻塞 hub 下一条投递。 */
  waitForProactiveDelivery(deliveryId) {
    const id = String(deliveryId ?? '').trim();
    if (!id || this._completedProactive.has(id)) return Promise.resolve();
    return new Promise(resolve => this._proactiveWaiters.set(id, resolve));
  }

  // ── 会话生命周期 ───────────────────────────────────────────────────────────

  connect() { return this._conn.connect().then(() => this); }

  /**
   * 建连并可选择性地直接发送第一条消息。
   * @returns {Promise<{type:string}|null>} 无消息时返回 {type:'session_open'}
   */
  async run(question) {
    await this.connect();
    const text = String(question ?? '').trim();
    if (!text) return { type: 'session_open' };
    return this.sendTurn(text);
  }

  /** 提交一轮对话；Promise 在 turn_finish / work 挂起 / error / 掉线时兑现。 */
  async sendTurn(question) {
    const text = String(question ?? '').trim();
    if (!text) return null;
    if (!this.isConnected()) await this.connect();
    // 先登记 waiter 再发送：快速 fallback 可能在 send 返回前就到达 finish，
    // 否则没有对应 resolver，前端会永远停在 streaming 态。
    const resultPromise = this._waitTurn();
    this.sendFrame(frames.userMessage(text, this._env));
    const result = await resultPromise;
    if (result?.type === 'error') {
      this._handlers.onError(new Error(result.message ?? 'Agent error'));
    }
    return result;
  }

  close() {
    this._shouldStopWaitersOnClose();
    this.closeSilently();
  }

  /** 不再重连、停脉冲、resolve 所有主动消息等待者并尽力发送 close 帧。 */
  closeSilently() {
    for (const resolve of this._proactiveWaiters.values()) resolve();
    this._proactiveWaiters.clear();
    this._pulse.stop();
    this._conn.close(frames.close(this._env));
  }

  _shouldStopWaitersOnClose() { /* placeholder for future drain policy */ }

  // ── 入站分发 ───────────────────────────────────────────────────────────────

  _waitTurn() {
    return new Promise(resolve => this._turnWaiters.push(resolve));
  }

  _onFrame(rawMsg) {
    const parsed = classifyAgentFrame(rawMsg, this._env.genId);
    if (!parsed) return;

    switch (parsed.kind) {
      case 'session_ready':
        this._handlers.onSessionReady(parsed.event);
        return;
      case 'turn_start': {
        const deliveryId = parsed.meta.deliveryId;
        if (deliveryId && this._completedProactive.has(deliveryId)) {
          this._suppressProactiveId = deliveryId;
          return;
        }
        this._suppressProactiveId = '';
        this._handlers.onTurnStart({ event: parsed.event, meta: parsed.meta });
        return;
      }
      case 'speak_event': {
        const ev = parsed.event;
        const dupProactive = ev.deliveryId && this._completedProactive.has(ev.deliveryId);
        const suppressed = this._suppressProactiveId
          && (!ev.deliveryId || ev.deliveryId === this._suppressProactiveId);
        if (dupProactive || suppressed) return;
        this._handlers.onSpeakEvent(ev);
        return;
      }
      case 'turn_finish': {
        const deliveryId = parsed.meta.deliveryId ?? extractFinishDeliveryId(parsed.event);
        this._suppressProactiveId = '';
        if (deliveryId && this._completedProactive.has(deliveryId)) {
          // 已展示过的 proactive：跳过 UI，补发 ack 清服务端 bus。
          this.acknowledgeProactive(deliveryId);
          const dupResolve = this._turnWaiters.shift();
          if (dupResolve) dupResolve({ type: 'proactive_duplicate', ...parsed.event });
          return;
        }
        if (deliveryId) this._completedProactive.add(deliveryId);
        this._handlers.onTurnFinish(parsed.event);
        const resolve = this._turnWaiters.shift();
        if (resolve) resolve(parsed.event);
        return;
      }
      case 'route_decision':
        this._handlers.onRouteDecision(parsed.event);
        return;
      case 'route_pierce_ok':
        this._handlers.onRoutePierceOk(parsed.event);
        return;
      case 'work': {
        const ev = parsed.event;
        this._handlers.onWorkEvent(ev);
        // 到达关键节点时释放 turn waiter，让 UI 离开 streaming、进入确认态。
        if (
          ev.type === 'work_confirmation_required'
          || ev.type === 'work_declined'
          || ev.type === 'work_started'
        ) {
          const resolve = this._turnWaiters.shift();
          if (resolve) resolve({ type: 'work_pending', work_id: ev.workId, work_type: ev.type });
        }
        return;
      }
      case 'typing_ack':
        this._handlers.onTypingAck(parsed.event);
        return;
      case 'aborted':
        this._handlers.onAborted(parsed.event);
        return;
      case 'session_end': {
        const resolve = this._turnWaiters.shift();
        if (resolve) resolve({ type: 'session_end' });
        this._handlers.onSessionEnd(parsed.event);
        return;
      }
      case 'error': {
        const resolve = this._turnWaiters.shift();
        if (resolve) resolve({ type: 'error', message: parsed.event.message });
        this._handlers.onError(new Error(parsed.event.message || 'Agent error'));
        return;
      }
      default:
        this._handlers.onUnknown(parsed.event);
    }
  }
}

/** turn_finish 的 delivery_id 只出现在顶层或缺失时由顶层字段兜底。 */
function extractFinishDeliveryId(finishFrame) {
  return String(finishFrame?.delivery_id ?? '').trim();
}

/** 供 UI 判断工作是否已到终态（镜像 WORK_TERMINAL_STATUSES）。 */
export function isWorkTerminal(status) {
  return WORK_TERMINAL_STATUSES.includes(String(status ?? ''));
}
