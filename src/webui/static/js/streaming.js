/**
 * streaming.js — WebSocket streaming session management.
 *
 * Issue 1 fix: abort sends {type:'abort',gen_id} over the SAME WebSocket,
 *              avoiding a separate REST call that could race with the WS close.
 * Issue 3 fix: on aborted finish, caller skips conversation persistence.
 * Issue 6 fix: full prompt is sent exactly once via prompt_preview message
 *              and rendered by render.js; never duplicated.
 */

import { wsFactory, PATHS }  from './api.js';
import { S, setState, set }  from './state.js';

// ── Base session ──────────────────────────────────────────────────────────────

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
      this._ws.onerror = e => reject(new Error(`WebSocket error on ${this._path}`));
    });
  }

  close() {
    if (this._ws && !this._closed) {
      this._closed = true;
      this._ws.close();
    }
  }
}

// ── ReAct session ─────────────────────────────────────────────────────────────

/**
 * Streams a full ReAct reasoning turn.
 *
 * @param {string}   question
 * @param {string}   genId
 * @param {object}   [opts]
 * @param {Function} [opts.onPromptPreview]   (messages: array) => void  — Issue 6
 * @param {Function} [opts.onStepStart]       (index: number) => void
 * @param {Function} [opts.onChunk]           (index: number, chunk: string) => void
 * @param {Function} [opts.onStep]            (stepObj) => void
 * @param {Function} [opts.onRetry]           (index: number, reason: string) => void
 * @param {Function} [opts.onApprovalRequest] (requestId, tool, args) => void
 * @param {Function} [opts.onFinish]          (answer: string, aborted: bool) => void
 * @param {Function} [opts.onError]           (err: Error) => void
 */
export class ReactSession extends BaseSession {
  constructor(question, genId, opts = {}) {
    super(PATHS.react.run, genId);
    this._question          = question;
    this._onPromptPreview   = opts.onPromptPreview   ?? (() => {});
    this._onStepStart       = opts.onStepStart       ?? (() => {});
    this._onChunk           = opts.onChunk           ?? (() => {});
    this._onStep            = opts.onStep            ?? (() => {});
    this._onRetry           = opts.onRetry           ?? (() => {});
    this._onApprovalRequest = opts.onApprovalRequest ?? (() => {});
    this._onFinish          = opts.onFinish          ?? (() => {});
    this._onError           = opts.onError           ?? (() => {});
    this._onSubStart        = opts.onSubStart        ?? (() => {});
    this._onSubChunk        = opts.onSubChunk        ?? (() => {});
    this._onSubStep         = opts.onSubStep         ?? (() => {});
    this._onSubFinish       = opts.onSubFinish       ?? (() => {});
    this._onSubError        = opts.onSubError        ?? (() => {});
    this._aborted           = false;
  }

  async run() {
    await this._open();
    this._ws.send(JSON.stringify({ question: this._question, gen_id: this._genId }));

    let finalAnswer = '';

    await new Promise(resolve => {
      this._ws.onmessage = evt => {
        const msg = JSON.parse(evt.data);
        switch (msg.type) {
          case 'prompt_preview':
            // Issue 6: rendered exactly once from the backend payload
            this._onPromptPreview(msg.messages);
            break;
          case 'step_start':
            this._onStepStart(msg.index);
            break;
          case 'chunk':
            this._onChunk(msg.index, msg.chunk);
            break;
          case 'step':
            this._onStep(msg);
            break;
          case 'retry':
            this._onRetry(msg.index, msg.reason);
            break;
          case 'approval_request':
            this._onApprovalRequest(msg.request_id, msg.tool, msg.args ?? {});
            break;
          case 'sub_start':
            this._onSubStart(msg.action, msg.instruction);
            break;
          case 'sub_chunk':
            this._onSubChunk(msg.index, msg.chunk);
            break;
          case 'sub_step':
            this._onSubStep(msg);
            break;
          case 'sub_finish':
            this._onSubFinish(msg.answer);
            break;
          case 'sub_error':
            this._onSubError(msg.error);
            break;
          case 'finish':
            finalAnswer       = msg.answer ?? '';
            this._aborted     = msg.aborted ?? false;
            resolve();
            break;
          case 'error':
            this._onError(new Error(msg.message));
            resolve();
            break;
        }
      };
      this._ws.onclose = resolve;
    });

    // Issue 1/3: pass aborted flag to caller — they skip persistence when true
    this._onFinish(finalAnswer, this._aborted);
  }

  /** Issue 1: abort over the same WebSocket (not a separate REST call). */
  abort() {
    if (this._ws && this._ws.readyState === WebSocket.OPEN) {
      this._aborted = true;
      this._ws.send(JSON.stringify({ type: 'abort', gen_id: this._genId }));
    }
  }

  /** Send an approval response back to the backend. */
  respond(requestId, approved) {
    if (this._ws && this._ws.readyState === WebSocket.OPEN) {
      this._ws.send(JSON.stringify({
        type: 'approval_response',
        request_id: requestId,
        approved,
      }));
    }
  }
}

// ── Active session registry ───────────────────────────────────────────────────
// Kept in module scope so main.js and domain modules can call abortCurrent().

let _current = null;

/** Start a new streaming session, aborting any existing one. */
export function startSession(session) {
  if (_current) {
    _current.abort();
    _current = null;
  }
  _current = session;
  return session;
}

/** Abort the currently running session (if any). */
export function abortCurrent() {
  if (_current) {
    _current.abort();
    _current = null;
  }
}

/** Called by the session itself when it ends, to deregister. */
export function clearCurrent() {
  _current = null;
}
