/**
 * bubbleManager.js — TurnBubbleManager
 *
 * Manages the lifecycle of per-step StepBubble controllers within a single
 * ReAct conversation turn.  workspace.js instantiates one manager per turn
 * and routes all incoming streaming events through it.
 *
 * Public API:
 *   startStep(index)
 *   appendChunk(index, chunk)
 *   finalizeStep(stepObj)
 *   showActivity(text)
 *   openSubAgent(action, instruction)
 *   addSubChunk(index, chunk)
 *   addSubStep(stepObj)
 *   closeSubAgent(answerOrError, isError)
 *   addStepPause(index, output, reqId, onContinue, onStop)
 *   showPrompt(messages)
 *   get hasContent
 *   cleanup()
 */

import * as render from './render.js';

export class TurnBubbleManager {
  #bubbles   = new Map();   // index → StepBubble controller
  #current   = null;        // most recently created StepBubble controller
  #hasContent = false;

  // ── Step lifecycle ───────────────────────────────────────────────────────────

  startStep(index) {
    const bubble = render.appendStepBubble(index);
    this.#bubbles.set(index, bubble);
    this.#current = bubble;
    this.#hasContent = true;
  }

  appendChunk(index, chunk) {
    const bubble = this.#getOrCreate(index);
    bubble.streamChunk(chunk);
  }

  finalizeStep(stepObj) {
    const bubble = this.#getOrCreate(stepObj.index);
    bubble.finalize(stepObj);
    // Do NOT advance #current here — sub-agent events after finalize still
    // belong to this bubble until the next startStep call.
  }

  // ── Activity (delegated to current bubble) ───────────────────────────────────

  showActivity(text = 'Thinking…') {
    this.#current?.showActivity(text);
  }

  // ── Sub-agent events (delegated to current bubble) ───────────────────────────

  openSubAgent(action, instruction) {
    this.#current?.openSubAgent(action, instruction);
  }

  addSubChunk(index, chunk) {
    this.#current?.addSubChunk(index, chunk);
  }

  addSubStep(stepObj) {
    this.#current?.addSubStep(stepObj);
  }

  closeSubAgent(answerOrError, isError = false) {
    this.#current?.closeSubAgent(answerOrError, isError);
  }

  // ── Step pause (approval / human-in-the-loop) ────────────────────────────────

  addStepPause(index, output, reqId, onContinue, onStop) {
    const bubble = this.#getOrCreate(index);
    bubble.addStepPause?.(output, reqId, onContinue, onStop);
  }

  // ── Prompt preview (attach to first bubble) ──────────────────────────────────

  showPrompt(messages) {
    const first = this.#bubbles.values().next().value;
    first?.showPrompt(messages);
  }

  // ── Housekeeping ─────────────────────────────────────────────────────────────

  get hasContent() { return this.#hasContent; }

  cleanup() {
    if (!this.#hasContent) {
      this.#bubbles.forEach(b => b.remove?.());
    }
  }

  // ── Private ──────────────────────────────────────────────────────────────────

  #getOrCreate(index) {
    if (!this.#bubbles.has(index)) {
      this.startStep(index);
    }
    return this.#bubbles.get(index);
  }
}
