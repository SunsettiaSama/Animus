/** Speak responder selector. The WebUI uses the request-driven pipeline only. */

const STORAGE_KEY = 'speak_responder';
const DEFAULT_PIPELINE = 'request_driven';

function normalizeSpeakResponder(pipeline) {
  return DEFAULT_PIPELINE;
}

export function getSpeakResponder() {
  const v = localStorage.getItem(STORAGE_KEY);
  const next = normalizeSpeakResponder(v);
  if (v !== next) localStorage.setItem(STORAGE_KEY, next);
  return next;
}

export function setSpeakResponder(pipeline) {
  const next = normalizeSpeakResponder(pipeline);
  localStorage.setItem(STORAGE_KEY, next);
  window.dispatchEvent(new CustomEvent('speak:responder', { detail: next }));
  return next;
}

let _settingBound = false;

export function bindSpeakResponderSetting() {
  if (_settingBound) return;
  const select = document.getElementById('s-speak-responder');
  if (!select) return;
  _settingBound = true;
  select.value = getSpeakResponder();
  select.addEventListener('change', () => {
    setSpeakResponder(select.value);
  });
  window.addEventListener('speak:responder', e => {
    select.value = normalizeSpeakResponder(e.detail);
  });
}

export function syncSpeakResponderSetting() {
  const select = document.getElementById('s-speak-responder');
  if (select) select.value = getSpeakResponder();
}
