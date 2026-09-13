/**
 * features/boot_diagnostics.js — 启动期错误网。
 *
 * 必须是 app.js 的第一个 import：在任何业务模块求值前挂上
 * error / unhandledrejection 捕获，把现场写入 window.__js2BootError。
 */

if (typeof window !== 'undefined') {
  window.addEventListener('error', e => {
    window.__js2BootError = [
      'error:', String(e.message ?? e),
      '@', String(e.filename ?? ''), ':', String(e.lineno ?? ''),
    ].join('');
  });
  window.addEventListener('unhandledrejection', e => {
    const reason = e.reason;
    window.__js2BootError =
      'unhandledrejection: ' + String(reason?.stack || reason);
  });
}
