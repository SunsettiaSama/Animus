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
  if (_current) {
    _current.abort();
    _current.close();
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
    this._deliveryMode = opts.deliveryMode === 'simulated' ? 'simulated' : 'stream';
    this._typingIdleMs = opts.typingIdleMs === 5000 ? 5000 : 3000;
    this._getDraft = opts.getDraft ?? (() => '');
    this._typingPulseTimer = null;
    this._connected = false;
    this._aborted = false;
  }

  isConnected() {
    return this._connected && this._ws?.readyState === WebSocket.OPEN;
  }

  setTurnCallbacks(opts = {}) {
    if (opts.onEvent) this._onEvent = opts.onEvent;
    if (opts.onTurnFinish) this._onTurnFinish = opts.onTurnFinish;
    if (opts.onUserAck) this._onUserAck = opts.onUserAck;
    if (opts.onTurnStart) this._onTurnStart = opts.onTurnStart;
  }

  setDeliveryMode(mode) {
    this._deliveryMode = mode === 'simulated' ? 'simulated' : 'stream';
  }

  _wsPayload(extra = {}) {
    return {
      ...extra,
      gen_id: this._genId,
      session_id: this._sessionId,
      channel_id: this._channelId,
      delivery_mode: this._deliveryMode,
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
    if (msg.gen_id && msg.gen_id !== this._genId) return;

    if (msg.type === 'turn_start') {
      this._onTurnStart(msg);
    }

    if (msg.type === 'speak_event') {
      this._onEvent(msg.kind, msg.text ?? '', msg.meta ?? {});
      return;
    }

    if (msg.type === 'user_ack') {
      this._onUserAck(msg);
      return;
    }

    if (msg.type === 'turn_finish') {
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

  async run(question) {
    const first = String(question ?? '').trim();
    if (!first) {
      this._onError(new Error('empty question'));
      return;
    }

    await this._open();
    this._connected = true;
    this._turnResolvers = [];
    this._turnRejectors = [];

    this._ws.onmessage = evt => {
      let msg;
      try {
        msg = JSON.parse(evt.data);
      } catch (e) {
        this._onError(new Error(`Malformed WebSocket frame: ${e.message}`));
        return;
      }
      this._handleMessage(msg);
    };

    this._ws.onerror = () => {
      this._connected = false;
      this._onError(new Error('WebSocket connection error'));
    };

    this._ws.onclose = () => {
      this._connected = false;
    };

    this._send({
      type: 'start',
      question: first,
      ...this._wsPayload(),
    });
    this.sendTypingIdleMs();
    this.startTypingPulse(this._getDraft);

    const result = await this._waitTurn();
    if (result?.type === 'error') {
      this._onError(new Error(result.message ?? 'Speak error'));
    }
    return result;
  }

  async sendTurn(question) {
    const text = String(question ?? '').trim();
    if (!text || !this.isConnected()) return null;
    this._send({
      type: 'user_message',
      question: text,
      ...this._wsPayload(),
    });
    const result = await this._waitTurn();
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
    this.stopTypingPulse();
    super.close();
  }

  abort() {
    this.stopTypingPulse();
    this._aborted = true;
    this._send({ type: 'abort', gen_id: this._genId });
  }
}
