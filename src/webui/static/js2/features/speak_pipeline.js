/**
 * features/speak_pipeline.js — speak 管线（request_driven / direct）选择。
 *
 * 持久化在 localStorage（key: speak_pipeline），设置页 Speak 区的
 * <select id="s-speak-pipeline"> 为编辑入口；变更派发 window 事件
 * 'speak:pipeline'，conversation 侧订阅后向通道发送中途切换帧
 * （服务端 /ws/agent/run 与 /ws/speak/run 均支持会话内切换）。
 */

export const SPEAK_PIPELINES = Object.freeze(['request_driven', 'direct']);
export const DEFAULT_PIPELINE = 'request_driven';
const STORAGE_KEY = 'speak_pipeline';
const SELECT_ID = 's-speak-pipeline';

export function getSpeakPipeline() {
  const value = String(localStorage.getItem(STORAGE_KEY) || '').trim();
  return SPEAK_PIPELINES.includes(value) ? value : DEFAULT_PIPELINE;
}

export function setSpeakPipeline(value) {
  const next = String(value || '').trim();
  if (!SPEAK_PIPELINES.includes(next)) {
    return getSpeakPipeline();
  }
  const prev = getSpeakPipeline();
  if (next === prev) {
    return prev;
  }
  localStorage.setItem(STORAGE_KEY, next);
  window.dispatchEvent(new CustomEvent('speak:pipeline', { detail: { pipeline: next } }));
  return next;
}

/**
 * 同步设置页下拉框（设置页打开时调用）。
 * 兼容旧名 syncSpeakResponderSetting：soul tab 的 load 钩子仍以该名调用。
 */
export function syncSpeakResponderSetting() {
  const select = document.getElementById(SELECT_ID);
  if (!select) {
    return;
  }
  const current = getSpeakPipeline();
  select.value = current;
  select.querySelectorAll('option').forEach(option => {
    option.selected = option.value === current;
  });
}

function _bindSelectOnce() {
  const select = document.getElementById(SELECT_ID);
  if (!select || select.dataset.pipelineBound === '1') {
    return;
  }
  select.dataset.pipelineBound = '1';
  select.addEventListener('change', () => {
    setSpeakPipeline(select.value);
  });
  select.addEventListener('click', () => {
    // 每次打开设置页都重新绑定一次同步（load 时 tab 会重渲染）
    syncSpeakResponderSetting();
  });
}

_bindSelectOnce();
