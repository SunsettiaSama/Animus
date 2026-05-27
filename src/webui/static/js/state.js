/**
 * state.js — Frontend application state machine.
 *
 * Single source of truth for all UI-visible state.
 * State changes are broadcast as CustomEvents on `window`.
 *
 * ── State machine ─────────────────────────────────────────────────────────
 *
 *  idle ──► initializing ──► streaming ──► idle
 *            │                 │
 *            ▼                 ▼
 *           error           aborting ──► idle
 *
 * ── Field ownership ───────────────────────────────────────────────────────
 *
 *   S.genId        – UUID string                (set by streaming.js per session)
 *   S.convId       – UUID string | null         (set by history.js / main.js)
 *   S.convTitle    – string                     (set by history.js / main.js)
 *   S.lifecycle    – LifecycleState (see below)  (set ONLY via setState())
 *   S.reactReady   – bool                        (set by react module)
 *   S.personaName  – string | null               (set by persona module)
 *   S.llmModel     – string | null               (set by llm module)
 */

/** @typedef {'idle'|'initializing'|'streaming'|'aborting'|'error'} LifecycleState */

const _VALID_TRANSITIONS = {
  idle:         ['initializing', 'streaming'],
  initializing: ['streaming', 'error', 'idle'],
  streaming:    ['aborting', 'idle', 'error'],
  aborting:     ['idle', 'error'],
  error:        ['idle'],
};

/** Shared mutable state object — read-only outside this module (by convention). */
export const S = {
  /** @type {LifecycleState} */
  lifecycle:   'idle',

  /** Per-generation UUID, used to validate abort signals. */
  genId:       '',

  /** Active conversation UUID (null = not yet saved). */
  convId:      null,

  /** Title shown in topbar / sidebar. */
  convTitle:   'New Conversation',

  /** True when ReAct backend is ready. */
  reactReady:  false,

  /** True when Soul Speak backend is ready. */
  speakReady:  false,

  /** True when Soul backend is running. */
  soulReady:   false,

  /** Active conversation mode: 'speak' | 'react' | 'plan' | 'chat'. */
  convMode:    'speak',

  /** Active persona name, or null. */
  personaName: null,

  /** Currently loaded LLM model, or null. */
  llmModel:    null,
};

/**
 * Transition to a new lifecycle state and dispatch `react:state` on window.
 *
 * @param {LifecycleState} next
 * @param {object}         [payload]  — extra detail forwarded to listeners
 */
export function setState(next, payload = {}) {
  const from   = S.lifecycle;
  const allowed = _VALID_TRANSITIONS[from];
  if (!allowed || !allowed.includes(next)) {
    console.warn(`[state] Invalid transition ${from} → ${next}; skipped.`);
    return;
  }
  S.lifecycle = next;
  window.dispatchEvent(new CustomEvent('react:state', {
    detail: { from, to: next, ...payload },
  }));
}

/** Convenience: true when the app is busy (streaming / aborting / initializing). */
export function isBusy() {
  return S.lifecycle !== 'idle' && S.lifecycle !== 'error';
}

/** Set a top-level key on S and optionally emit a `react:update` event. */
export function set(key, value, silent = false) {
  S[key] = value;
  if (!silent) {
    window.dispatchEvent(new CustomEvent('react:update', {
      detail: { key, value },
    }));
  }
}
