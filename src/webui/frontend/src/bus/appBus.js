import mitt from 'mitt';
import { EVENTS } from '../events.js';

export const appBus = mitt();

/** @param {string} msg */
export function emitToast(msg) {
  appBus.emit(EVENTS.toast, msg);
}
