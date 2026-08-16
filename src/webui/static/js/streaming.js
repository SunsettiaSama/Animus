/**
 * streaming.js — WebSocket streaming session management.
 */
import { wsFactory, PATHS }  from './api.js';

class BaseSession {
  constructor(wsPath, genId) {
    this._path   = wsPath;
    this._genId  = genId;
    this._ws     = null;
    this._closed = false;
  }

  _open() {
    this._ws = wsFactory(this._path);
    return new Promise((resolve, reject) => {
      this._ws.onopen  = resolve;
      this._ws.onerror = () => reject(new Error(`WebSocket error on ${this._path}`));
    });
  }

  close() {
    this.stopTypingPulse();
    if (this._ws && !this._closed) {
      this._closed = true;
      if (this._ws.readyState === WebSocket.OPEN) {
        this._ws.send(JSON.stringify({ type: 'close', gen_id: this._genId }));
      }
      this._ws.close();
    }
  }

  startTypingPulse(getDraft) {
    if (typeof getDraft === 'function') {
      this._getDraft = getDraft;
    }
    this.stopTypingPulse();
    this._typingPulseTimer = setInterval(() => {
      if (!this.isConnected()) return;
      const draft = String(this._getDraft() ?? '').trim();
      this._send({
        type: 'typing_pulse',
        typing: draft.length > 0,
        draft,
        ...this._wsPayload(),
      });
    }, SPEAK_TYPING_PULSE_MS);
  }

  stopTypingPulse() {
    if (this._typingPulseTimer) {
      clearInterval(this._typingPulseTimer);
      this._typingPulseTimer = null;
    }
  }

  sendTypingIdleMs() {
    this._send({
      type: 'set_typing_idle_ms',
      typing_idle_ms: this._typingIdleMs,
      ...this._wsPayload(),
    });
  }
}

export class ReactSession extends BaseSession {
  constructor(question, genId, opts = {}) {
    super(PATHS.react.run, genId);
    this._question          = question;
    this._streamMode        = opts.streamMode ?? 'chunk';
    this._onPromptPreview   = opts.onPromptPreview   ?? (() => {});
    this._onStepStart       = opts.onStepStart       ?? (() => {});
    this._onChunk           = opts.onChunk           ?? (() => {});
    this._onStep            = opts.onStep            ?? (() => {});
    this._onRetry           = opts.onRetry           ?? (() => {});
    this._onApprovalRequest = opts.onApprovalRequest ?? (() => {});
    this._onFinish          = opts.onFinish          ?? (() => {});
    this._onError           = opts.onError           ?? (() => {});
    this._aborted           = false;
  }

  async run() {
    await this._open();
    this._ws.send(JSON.stringify({
      question:    this._question,
      gen_id:      this._genId,
      stream_mode: this._streamMode,
    }));

    let finalAnswer = '';

    try {
      await new Promise((resolve, reject) => {
        this._ws.onmessage = evt => {
          let msg;
          try {
            msg = JSON.parse(evt.data);
          } catch (e) {
            reject(new Error(`Malformed WebSocket frame: ${e.message}`));
            return;
          }
          if (msg.channel === 'workflow') {
            window.dispatchEvent(new CustomEvent('workflow:wire', { detail: msg }));
            return;
          }
          switch (msg.type) {
            case 'finish':
              finalAnswer = msg.answer ?? '';
              this._aborted = msg.aborted ?? false;
              resolve();
              break;
            case 'error':
              reject(new Error(msg.message));
              break;
            default:
              break;
          }
        };
        this._ws.onerror = () => reject(new Error('WebSocket connection error'));
        this._ws.onclose = e => {
          if (e.wasClean || e.code === 1000 || e.code === 1005) resolve();
          else reject(new Error(`Connection dropped (code ${e.code})`));
        };
      });
      this._onFinish(finalAnswer, this._aborted);
    } catch (e) {
      this._onError(e);
    }
  }

  abort() {
    if (this._ws?.readyState === WebSocket.OPEN) {
      this._aborted = true;
      this._ws.send(JSON.stringify({ type: 'abort', gen_id: this._genId }));
    }
  }
}

let _current = null;

export function startSession(session) {
  if (_current && _current !== session) {
    // Speak 长连接勿发 abort：否则服务端刚 arm_enter_greeting 就被拆掉，主动问候永远进不来
    if (typeof _current.close === 'function') {
      _current.close();
    }
    _current = null;
  }
  _current = session;
  return session;
}

export function getCurrent() {
  return _current;
}

export function abortCurrent() {
  if (_current) {
    _current.abort();
    _current.close();
    _current = null;
  }
}

export function clearCurrent() {
  if (_current) _current.close();
  _current = null;
}

/**
 * Soul Speak 长连接：单条 WebSocket 可多轮输入；流式过程中可 sendUserMessage。
 */
export const SPEAK_TYPING_PULSE_MS = 500;

export class SpeakSession extends BaseSession {
  constructor(genId, opts = {}) {
    super(PATHS.speak.run, genId);
    this._sessionId = opts.sessionId ?? 'webui';
    this._channelId = opts.channelId ?? this._sessionId;
    this._onEvent = opts.onEvent ?? (() => {});
    this._onTurnFinish = opts.onTurnFinish ?? (() => {});
    this._onUserAck = opts.onUserAck ?? (() => {});
    this._onTurnStart = opts.onTurnStart ?? (() => {});
    this._onError = opts.onError ?? (() => {});
    this._onWorkEvent = opts.onWorkEvent ?? (() => {});
    this._deliveryMode = 'stream';
    this._pipeline = 'request_driven';
    this._typingIdleMs = opts.typingIdleMs === 5000 ? 5000 : 3000;
    this._getDraft = opts.getDraft ?? (() => '');
    this._typingPulseTimer = null;
    this._connected = false;
    this._aborted = false;
    this._workHold = false;
    this._turnResolvers = [];
    this._connectPromise = null;
    this._reconnectTimer = null;
    this._shouldReconnect = false;
    this._connectionEpoch = 0;
    this._proactiveResolvers = new Map();
    this._completedProactive = new Set();
    this._suppressProactiveId = '';
  }

  isConnected() {
    return this._connected && this._ws?.readyState === WebSocket.OPEN;
  }

  get sessionId() {
    return this._sessionId;
  }

  setTurnCallbacks(opts = {}) {
    if (opts.onEvent) this._onEvent = opts.onEvent;
    if (opts.onTurnFinish) this._onTurnFinish = opts.onTurnFinish;
    if (opts.onUserAck) this._onUserAck = opts.onUserAck;
    if (opts.onTurnStart) this._onTurnStart = opts.onTurnStart;
    if (opts.onWorkEvent) this._onWorkEvent = opts.onWorkEvent;
  }

  sendWorkFrame(payload) {
    if (!payload || typeof payload !== 'object') return false;
    if (!this.isConnected()) return false;
    this._send({ ...payload, gen_id: this._genId, session_id: this._sessionId });
    return true;
  }

  acknowledgeProactive(deliveryId) {
    const id = String(deliveryId ?? '').trim();
    if (!id) return false;
    // 本地先记完成：断线时 ack 发不出去，重连重推也不得再渲染
    this._completedProactive.add(id);
    const resolve = this._proactiveResolvers.get(id);
    if (resolve) {
      this._proactiveResolvers.delete(id);
      resolve();
    }
    if (!this.isConnected()) return false;
    this._send({
      type: 'proactive_ack',
      delivery_id: id,
      ...this._wsPayload(),
    });
    return true;
  }

  _proactiveDeliveryId(msg) {
    if (!msg || typeof msg !== 'object') return '';
    const top = String(msg.delivery_id ?? '').trim();
    if (top) return top;
    const meta = msg.meta;
    if (meta && typeof meta === 'object') {
      return String(meta.delivery_id ?? '').trim();
    }
    return '';
  }

  waitForProactiveDelivery(deliveryId) {
    const id = String(deliveryId ?? '').trim();
    if (!id || this._completedProactive.has(id)) return Promise.resolve();
    return new Promise(resolve => {
      this._proactiveResolvers.set(id, resolve);
    });
  }

  setDeliveryMode() {
    this._deliveryMode = 'stream';
  }

  setPipeline(pipeline) {
    this._pipeline = 'request_driven';
  }

  _wsPayload(extra = {}) {
    return {
      ...extra,
      gen_id: this._genId,
      session_id: this._sessionId,
      channel_id: this._channelId,
      delivery_mode: this._deliveryMode,
      pipeline: this._pipeline,
    };
  }

  _send(payload) {
    if (this._ws?.readyState === WebSocket.OPEN) {
      this._ws.send(JSON.stringify(payload));
    }
  }

  sendUserMessage(question) {
    const text = String(question ?? '').trim();
    if (!text || !this._connected) return false;
    this._send({
      type: 'user_message',
      question: text,
      ...this._wsPayload(),
    });
    return true;
  }

  _handleMessage(msg) {
    if (msg.gen_id && msg.gen_id !== this._genId && !String(msg.type || '').startsWith('work_')) {
      return;
    }

    if (String(msg.type || '').startsWith('work_')) {
      this._onWorkEvent(msg);
      // Release turn waiter so UI leaves streaming while waiting for confirmation.
      if (
        msg.type === 'work_confirmation_required'
        || msg.type === 'work_declined'
        || msg.type === 'work_started'
      ) {
        this._workHold = msg.type === 'work_confirmation_required' || msg.type === 'work_started';
        const resolve = this._turnResolvers.shift();
        if (resolve) {
          resolve({ type: 'work_pending', work_id: msg.work_id, work_type: msg.type });
        }
      }
      return;
    }

    if (msg.type === 'turn_start') {
      const deliveryId = this._proactiveDeliveryId(msg);
      if (deliveryId && this._completedProactive.has(deliveryId)) {
        this._suppressProactiveId = deliveryId;
        return;
      }
      this._suppressProactiveId = '';
      this._onTurnStart(msg);
      return;
    }

    if (msg.type === 'speak_event') {
      const deliveryId = this._proactiveDeliveryId(msg);
      if (
        (deliveryId && this._completedProactive.has(deliveryId))
        || (this._suppressProactiveId
          && (!deliveryId || deliveryId === this._suppressProactiveId))
      ) {
        return;
      }
      this._onEvent(msg.kind, msg.text ?? '', msg.meta ?? {});
      return;
    }

    if (msg.type === 'user_ack') {
      this._onUserAck(msg);
      return;
    }

    if (msg.type === 'turn_finish') {
      const deliveryId = this._proactiveDeliveryId(msg);
      this._suppressProactiveId = '';
      if (deliveryId && this._completedProactive.has(deliveryId)) {
        // 已展示过的 proactive：跳过 UI，补发 ack 清 bus
        this.acknowledgeProactive(deliveryId);
        const resolveDup = this._turnResolvers.shift();
        if (resolveDup) resolveDup({ type: 'proactive_duplicate', ...msg });
        return;
      }
      if (deliveryId) this._completedProactive.add(deliveryId);
      this._aborted = Boolean(msg.aborted);
      this._onTurnFinish(msg);
      const resolve = this._turnResolvers.shift();
      if (resolve) resolve(msg);
      return;
    }

    if (msg.type === 'session_end') {
      this._connected = false;
      const resolve = this._turnResolvers.shift();
      if (resolve) resolve({ type: 'session_end' });
      return;
    }

    if (msg.type === 'error') {
      const resolve = this._turnResolvers.shift();
      if (resolve) resolve({ type: 'error', message: msg.message });
      this._onError(new Error(msg.message ?? 'Speak error'));
    }
  }

  _waitTurn() {
    return new Promise(resolve => {
      this._turnResolvers.push(resolve);
    });
  }

  _scheduleReconnect() {
    if (!this._shouldReconnect || this._closed || this._reconnectTimer) return;
    this._reconnectTimer = setTimeout(() => {
      this._reconnectTimer = null;
      this.connect().then(
        () => {},
        () => this._scheduleReconnect(),
      );
    }, 1000);
  }

  connect() {
    if (this.isConnected()) return Promise.resolve(this);
    if (this._connectPromise) return this._connectPromise;

    this._closed = false;
    this._shouldReconnect = true;
    const epoch = ++this._connectionEpoch;
    const ws = wsFactory(this._path);
    this._ws = ws;

    this._connectPromise = new Promise((resolve, reject) => {
      ws.onopen = () => {
        if (epoch !== this._connectionEpoch || this._closed) {
          ws.close();
          reject(new Error('Speak connection superseded'));
          return;
        }
        this._connected = true;
        ws.send(JSON.stringify({
          type: 'session_open',
          ...this._wsPayload(),
        }));
        this.sendTypingIdleMs();
        this.startTypingPulse(this._getDraft);
        resolve(this);
      };

      ws.onmessage = evt => {
        let msg;
        try {
          msg = JSON.parse(evt.data);
        } catch (e) {
          this._onError(new Error(`Malformed WebSocket frame: ${e.message}`));
          return;
        }
        this._handleMessage(msg);
      };

      ws.onerror = () => {
        if (!this._connected) reject(new Error('WebSocket connection error'));
      };

      ws.onclose = () => {
        if (epoch !== this._connectionEpoch) return;
        this._connected = false;
        this.stopTypingPulse();
        while (this._turnResolvers.length) {
          this._turnResolvers.shift()?.({ type: 'disconnected' });
        }
        this._scheduleReconnect();
      };
    }).finally(() => {
      if (epoch === this._connectionEpoch) this._connectPromise = null;
    });

    return this._connectPromise;
  }

  async run(question) {
    const first = String(question ?? '').trim();
    await this.connect();
    if (!first) return { type: 'session_open' };

    return this.sendTurn(first);
  }

  async sendTurn(question) {
    const text = String(question ?? '').trim();
    if (!text) return null;
    if (!this.isConnected()) await this.connect();
    // 先登记 waiter，再发送：本地/快速 fallback 可在 send() 返回前收到 turn_finish，
    // 否则 finish 没有对应 resolver，会让前端永远停在 streaming。
    const resultPromise = this._waitTurn();
    this._send({
      type: 'user_message',
      question: text,
      ...this._wsPayload(),
    });
    const result = await resultPromise;
    if (result?.type === 'error') {
      this._onError(new Error(result.message ?? 'Speak error'));
    }
    return result;
  }

  startTypingPulse(getDraft) {
    if (typeof getDraft === 'function') {
      this._getDraft = getDraft;
    }
    this.stopTypingPulse();
    this._typingPulseTimer = setInterval(() => {
      if (!this.isConnected()) return;
      const draft = String(this._getDraft() ?? '').trim();
      this._send({
        type: 'typing_pulse',
        typing: draft.length > 0,
        draft,
        ...this._wsPayload(),
      });
    }, SPEAK_TYPING_PULSE_MS);
  }

  stopTypingPulse() {
    if (this._typingPulseTimer) {
      clearInterval(this._typingPulseTimer);
      this._typingPulseTimer = null;
    }
  }

  sendTypingIdleMs() {
    this._send({
      type: 'set_typing_idle_ms',
      typing_idle_ms: this._typingIdleMs,
      ...this._wsPayload(),
    });
  }

  close() {
    this._shouldReconnect = false;
    this._connectionEpoch += 1;
    if (this._reconnectTimer) {
      clearTimeout(this._reconnectTimer);
      this._reconnectTimer = null;
    }
    this._connectPromise = null;
    this._connected = false;
    for (const resolve of this._proactiveResolvers.values()) resolve();
    this._proactiveResolvers.clear();
    this.stopTypingPulse();
    super.close();
  }

  abort() {
    this.stopTypingPulse();
    this._aborted = true;
    this._send({ type: 'abort', gen_id: this._genId });
  }
}

/** Work frame types handled by SpeakSession (same WS). */
export const WORK_EVENT_TYPES = [
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
];
