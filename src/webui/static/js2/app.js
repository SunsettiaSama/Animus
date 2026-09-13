/**
 * app.js — 入口加载器。
 *
 * 静态 import 图整体移入 app_main.js；这里动态导入并在任何模块求值失败时
 * 把错误渲染到页面（避免"白屏静默"），同时写入 window.__js2BootError。
 */

window.addEventListener('error', e => {
  window.__js2BootError = String(e.message ?? e);
});

function _renderFatal(message) {
  document.body?.setAttribute('data-js2-loader', 'fatal');
  const host = document.createElement('div');
  host.id = 'js2-boot-fatal';
  host.style.cssText = [
    'position:fixed', 'inset:auto 12px 12px 12px', 'z-index:99999',
    'max-height:40vh', 'overflow:auto', 'padding:12px 14px',
    'background:#2a1518', 'color:#ffb4b4', 'border:1px solid #7f2d2d',
    'border-radius:10px', 'font:12px/1.5 monospace', 'white-space:pre-wrap',
  ].join(';');
  host.textContent = '[js2 启动失败] ' + message;
  document.body?.appendChild(host);
}

window.addEventListener('unhandledrejection', e => {
  const reason = e.reason;
  window.__js2BootError = 'unhandledrejection: ' + String(reason?.stack || reason);
  _renderFatal(String(reason?.stack || reason));
});

import('./app_main.js')
  .then(() => {
    document.body?.setAttribute('data-js2-loader', 'ok');
  })
  .catch(err => {
  const message = err?.stack || String(err);
  window.__js2BootError = message;
  const render = () => _renderFatal(message);
  if (document.body) render();
  else document.addEventListener('DOMContentLoaded', render, { once: true });
});

// 诊断装置：#/probe=路径 → 单独导入该模块并显示结果（定位语法错误用）
async function _probe() {
  const m = location.hash.match(/#probe=(.+)$/);
  if (!m) return false;
  const mod = m[1];
  try {
    await import(mod.startsWith('/') ? mod : `./${mod}`);
    _renderFatal(`PROBE OK: ${mod}`);
  } catch (err) {
    _renderFatal(`PROBE FAIL: ${mod}\n${err?.stack || err}`);
  }
  return true;
}
if (location.hash.startsWith('#probe=')) {
  document.addEventListener('DOMContentLoaded', () => void _probe(), { once: true });
}
