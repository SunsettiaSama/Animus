/**
 * transport/ws_session.js — WebSocket 连接生命周期原语。
 *
 * 职责：epoch 计数防旧连接回魂、断线自动重连（1s）、JSON 帧收发、
 * 异常帧解析隔离。协议语义（握手、类型分发）不在本层 —— 见 agent_channel.js。
 */

import { wsFactory } from './http.js';

export const RECONNECT_DELAY_MS = 1000;

export class WsConnection {
  /**
   * @param {string} path WS 端点
   * @param {Object} handlers 上层钩子
   *   onOpen(): 连接打开（已通过 epoch 校验）
   *   onMessage(obj): 已解析的入站帧
   *   onClose(): 干净的连接关闭通知（epoch 有效时）
   *   onError(err): 解析失败或连接错误
   */
  constructor(path, handlers = {}) {
    this._path = path;
    this._onOpen = handlers.onOpen ?? (() => {});
    this._onMessage = handlers.onMessage ?? (() => {});
    this._onClose = handlers.onClose ?? (() => {});
    this._onError = handlers.onError ?? (() => {});

    this._ws = null;
    this._connected = false;
    this._closedByUs = false;
    this._connectPromise = null;
    this._reconnectTimer = null;
    this._shouldReconnect = false;
    this._connectionEpoch = 0;
  }

  get connected() { return this._connected && this._ws?.readyState === WebSocket.OPEN; }

  /** 当前连接代际；上层用其决定是否丢弃过期的异步回调。 */
  get epoch() { return this._connectionEpoch; }

  isOpen() { return Boolean(this._ws && this._ws.readyState === WebSocket.OPEN); }

  /**
   * 打开连接（幂等：重复调用复用进行中的 promise）。
   * epoch 校验：一个更晚的 close/connect 会使早先的 open 回调失效。
   */
  connect() {
    if (this.connected) return Promise.resolve(this);
    if (this._connectPromise) return this._connectPromise;

    this._closedByUs = false;
    this._shouldReconnect = true;
    const epoch = ++this._connectionEpoch;
    const ws = wsFactory(this._path);
    this._ws = ws;

    this._connectPromise = new Promise((resolve, reject) => {
      ws.onopen = () => {
        if (epoch !== this._connectionEpoch || this._closedByUs) {
          ws.close();
          reject(new Error('WebSocket connection superseded'));
          return;
        }
        this._connected = true;
        this._onOpen();
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
        this._onMessage(msg);
      };

      ws.onerror = () => {
        if (!this._connected) reject(new Error('WebSocket connection error'));
      };

      ws.onclose = () => {
        if (epoch !== this._connectionEpoch) return;
        this._connected = false;
        this._onClose();
        this._scheduleReconnect();
      };
    }).finally(() => {
      if (epoch === this._connectionEpoch) this._connectPromise = null;
    });

    return this._connectPromise;
  }

  _scheduleReconnect() {
    if (!this._shouldReconnect || this._closedByUs || this._reconnectTimer) return;
    this._reconnectTimer = setTimeout(() => {
      this._reconnectTimer = null;
      this.connect().then(
        () => {},
        () => this._scheduleReconnect(),
      );
    }, RECONNECT_DELAY_MS);
  }

  /** 发送任意可序列化对象；未连接时静默丢弃（与旧行为一致）。 */
  send(payloadObj) {
    if (!this.isOpen()) return false;
    this._ws.send(JSON.stringify(payloadObj));
    return true;
  }

  /** 关闭且不再重连。 */
  close(closeFrame = null) {
    this._shouldReconnect = false;
    this._connectionEpoch += 1;
    if (this._reconnectTimer) {
      clearTimeout(this._reconnectTimer);
      this._reconnectTimer = null;
    }
    this._connectPromise = null;
    this._connected = false;
    if (this._ws && !this._closedByUs) {
      this._closedByUs = true;
      if (closeFrame) this.send(closeFrame);
      if (this._ws.readyState === WebSocket.OPEN) this._ws.close();
    }
  }
}

/** typing_pulse 心跳定时器（默认 500ms，独立可测）。 */
export class TypingPulseDriver {
  constructor(intervalMs, sendFn) {
    this._intervalMs = intervalMs;
    this._send = sendFn;
    this._timer = null;
    this._getDraft = () => '';
  }

  start(getDraft) {
    if (typeof getDraft === 'function') this._getDraft = getDraft;
    this.stop();
    this._timer = setInterval(() => {
      const draft = String(this._getDraft() ?? '').trim();
      this._send(draft.length > 0, draft);
    }, this._intervalMs);
  }

  stop() {
    if (this._timer) {
      clearInterval(this._timer);
      this._timer = null;
    }
  }
}
