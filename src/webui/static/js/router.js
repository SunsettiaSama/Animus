/**
 * router.js — Single source of truth for screen navigation.
 *
 * Every screen transition must go through router.navigate().
 * Emits 'navigate' and 'screen:enter' events on the bus so any
 * module can react to screen changes without being tightly coupled
 * to the main entry point.
 *
 * Screens are identified by their DOM element id.
 */

import { bus } from './eventBus.js';

const SCREENS = [
  's-landing',
  's-workspace',
  's-plan',
  's-benchmark',
  's-scheduler',
];

let _current = null;
let _history  = [];

function _apply(screenId) {
  SCREENS.forEach(id => {
    document.getElementById(id)?.classList.toggle('hidden', id !== screenId);
  });
  _current = screenId;
}

/**
 * Navigate to a screen.
 * @param {string} screenId  One of the SCREENS ids.
 * @param {boolean} [push=true]  Whether to push to history stack.
 */
export function navigate(screenId, push = true) {
  if (!SCREENS.includes(screenId)) {
    console.warn(`[router] Unknown screen: ${screenId}`);
    return;
  }
  const prev = _current;
  if (push && prev && prev !== screenId) _history.push(prev);
  _apply(screenId);
  bus.emit('navigate', screenId);
  bus.emit('screen:enter', screenId);
}

/** Go back to the previous screen (default: landing). */
export function back() {
  const prev = _history.pop();
  if (prev) {
    _apply(prev);
    bus.emit('navigate', prev);
    bus.emit('screen:enter', prev);
  } else {
    navigate('s-landing', false);
  }
}

/** Return the current screen id. */
export function current() { return _current; }

/** Named shorthand helpers — keep go* symmetry with existing call-sites. */
export const goHome      = () => navigate('s-landing');
export const goWorkspace = () => navigate('s-workspace');
export const goPlan      = () => navigate('s-plan');
export const goBenchmark = () => navigate('s-benchmark');
export const goScheduler = () => navigate('s-scheduler');
