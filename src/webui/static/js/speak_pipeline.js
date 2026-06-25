/** Speak 管线：legacy_qa（一问一答）| request_driven（新管线） */

const STORAGE_KEY = 'speak_pipeline';

export function getSpeakPipeline() {
  const v = localStorage.getItem(STORAGE_KEY);
  return v === 'request_driven' ? 'request_driven' : 'legacy_qa';
}

export function setSpeakPipeline(pipeline) {
  const next = pipeline === 'request_driven' ? 'request_driven' : 'legacy_qa';
  localStorage.setItem(STORAGE_KEY, next);
  window.dispatchEvent(new CustomEvent('speak:pipeline', { detail: next }));
  return next;
}

let _settingBound = false;

export function bindSpeakPipelineSetting() {
  if (_settingBound) return;
  const select = document.getElementById('s-speak-pipeline');
  if (!select) return;
  _settingBound = true;
  select.value = getSpeakPipeline();
  select.addEventListener('change', () => {
    setSpeakPipeline(select.value);
  });
  window.addEventListener('speak:pipeline', e => {
    select.value = e.detail === 'request_driven' ? 'request_driven' : 'legacy_qa';
  });
}

export function syncSpeakPipelineSetting() {
  const select = document.getElementById('s-speak-pipeline');
  if (select) select.value = getSpeakPipeline();
}
