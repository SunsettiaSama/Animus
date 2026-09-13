/**
 * ui/components/toast.js — 全局轻提示。
 *
 * 渲染 #toast 元素；消息来源统一是 bus 的 toast:show 事件（含 work 错误等），
 * 视图层通过 showToast() 发射而非直接操作其他模块的 DOM。
 */

import { bus, EVENTS } from '../../store/bus.js';

let _timer = null;

export function initToast() {
  const el = document.getElementById('toast');
  if (!el) return;
  bus.on(EVENTS.toastShow, text => showToast(text));
}

export function showToast(text) {
  const msg = String(text ?? '').trim();
  if (!msg) return;
  const el = document.getElementById('toast');
  if (!el) {
    console.info('[toast]', msg);
    return;
  }
  el.textContent = msg;
  el.classList.add('show');
  clearTimeout(_timer);
  _timer = setTimeout(() => {
    el.classList.remove('show');
  }, 2600);
}
