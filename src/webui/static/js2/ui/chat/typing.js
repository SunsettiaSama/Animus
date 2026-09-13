/**
 * ui/chat/typing.js — 顶栏「对方正在输入」状态。
 */

let _probeCount = 0;

export function setTitleBarTyping(active) {
  const tb = document.getElementById('tb-title');
  const spin = document.getElementById('tb-typing');
  // 探针：状态镜像到 body dataset，供自动化/调试读取（含触发计数）。
  try {
    document.body.dataset.tbtState = active ? 'on' : 'off';
    document.body.dataset.tbtLast = String(active);
    document.body.dataset.tbtCount = String(++_probeCount);
  } catch { /* ignore */ }
  if (!tb) return;
  if (active) {
    if (!tb.dataset.savedTitle) {
      tb.dataset.savedTitle = tb.textContent.trim() || '对话';
    }
    tb.textContent = '对方正在输入…';
    tb.classList.add('tb-typing');
    if (spin) {
      spin.classList.remove('hidden');
      spin.setAttribute('aria-hidden', 'false');
    }
    return;
  }
  tb.classList.remove('tb-typing');
  if (spin) {
    spin.classList.add('hidden');
    spin.setAttribute('aria-hidden', 'true');
  }
  const saved = tb.dataset.savedTitle;
  if (saved) {
    tb.textContent = saved;
    delete tb.dataset.savedTitle;
  }
}

export function showSpeakTurnTyping() {
  setTitleBarTyping(true);
}
