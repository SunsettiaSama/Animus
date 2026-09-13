/**
 * ui/router.js — 屏幕导航唯一入口。
 *
 * 屏幕以 DOM 元素 id 标识；所有跳屏经 navigate()。同时响应下层通过
 * bus 发出的 navigate:request（如 features/conversation 的开窗）。
 */

import { bus, EVENTS } from '../store/bus.js';

const SCREENS = [
  's-landing',
  's-workspace',
  's-plan',
  's-benchmark',
  's-scheduler',
];

let _current = null;
let _history = [];

function _apply(screenId) {
  SCREENS.forEach(id => {
    document.getElementById(id)?.classList.toggle('hidden', id !== screenId);
  });
  _current = screenId;
}

/**
 * @param {string} screenId SCREENS 之一
 * @param {boolean} [push=true] 是否压入返回栈
 */
export function navigate(screenId, push = true) {
  if (!SCREENS.includes(screenId)) {
    console.warn(`[router] Unknown screen: ${screenId}`);
    return;
  }
  const prev = _current;
  if (push && prev && prev !== screenId) _history.push(prev);
  _apply(screenId);
  bus.emit(EVENTS.navigate, screenId);
  bus.emit(EVENTS.screenEnter, screenId);
}

export function back() {
  const prev = _history.pop();
  if (prev) {
    _apply(prev);
    bus.emit(EVENTS.navigate, prev);
    bus.emit(EVENTS.screenEnter, prev);
  } else {
    navigate('s-landing', false);
  }
}

export function current() { return _current; }

export const goHome      = () => navigate('s-landing');
export const goWorkspace = () => navigate('s-workspace');
export const goPlan      = () => navigate('s-plan');
export const goBenchmark = () => navigate('s-benchmark');
export const goScheduler = () => navigate('s-scheduler');

/** 装配：订阅下层跳屏请求。app 启动时调用一次。 */
export function bindNavigationRequests() {
  bus.on(EVENTS.navigateRequest, ({ screen } = {}) => {
    if (screen) navigate(screen);
  });
}
