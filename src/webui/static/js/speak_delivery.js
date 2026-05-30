/** Speak 出站展示模式：stream（流式）| simulated（逐字呈现） */

const STORAGE_KEY = 'speak_delivery_mode';

/** 产品名：设置页与文案统一使用 */
export const SPEAK_DELIVERY_PACE_LABEL = '逐字呈现';

export function getSpeakDeliveryMode() {
  const v = localStorage.getItem(STORAGE_KEY);
  return v === 'simulated' ? 'simulated' : 'stream';
}

export function setSpeakDeliveryMode(mode) {
  const next = mode === 'simulated' ? 'simulated' : 'stream';
  localStorage.setItem(STORAGE_KEY, next);
  window.dispatchEvent(new CustomEvent('speak:delivery_mode', { detail: next }));
  return next;
}

export function isSimulatedDelivery() {
  return getSpeakDeliveryMode() === 'simulated';
}

let _settingBound = false;

/** Settings → Soul → Speak 中的「逐字呈现」开关 */
export function bindSpeakDeliverySetting() {
  if (_settingBound) return;
  const cb = document.getElementById('s-speak-simulated');
  if (!cb) return;
  _settingBound = true;
  cb.checked = isSimulatedDelivery();
  cb.addEventListener('change', () => {
    setSpeakDeliveryMode(cb.checked ? 'simulated' : 'stream');
  });
  window.addEventListener('speak:delivery_mode', e => {
    cb.checked = e.detail === 'simulated';
  });
}

export function syncSpeakDeliverySetting() {
  const cb = document.getElementById('s-speak-simulated');
  if (cb) cb.checked = isSimulatedDelivery();
}
