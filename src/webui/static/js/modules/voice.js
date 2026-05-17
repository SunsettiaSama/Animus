/**
 * modules/voice.js — TTS/STT configuration, synthesis, and recording.
 */

import { http, PATHS, wsFactory } from '../api.js';

const _cb = { onToast: () => {}, onTranscript: () => {} };
export function setCallbacks(cbs) { Object.assign(_cb, cbs); }

// ── TTS config ────────────────────────────────────────────────────────────────

export async function loadTTSConfig() {
  return http.get(PATHS.voice.tts.config);
}

export async function saveTTSConfig(payload) {
  await http.post(PATHS.voice.tts.save, payload);
  _cb.onToast('TTS config saved');
}

// ── STT config ────────────────────────────────────────────────────────────────

export async function loadSTTConfig() {
  return http.get(PATHS.voice.stt.config);
}

export async function saveSTTConfig(payload) {
  await http.post(PATHS.voice.stt.save, payload);
  _cb.onToast('STT config saved');
}

// ── TTS synthesis ─────────────────────────────────────────────────────────────

let _currentAudio = null;

export async function speak(text) {
  stopSpeaking();
  const resp  = await fetch(PATHS.voice.tts.synth, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ text }),
  });
  if (!resp.ok) { _cb.onToast('TTS failed'); return null; }
  const blob  = await resp.blob();
  const url   = URL.createObjectURL(blob);
  const audio = new Audio(url);
  _currentAudio = audio;
  audio.addEventListener('ended', () => { URL.revokeObjectURL(url); _currentAudio = null; });
  audio.play();
  return audio;
}

export function stopSpeaking() {
  if (_currentAudio) {
    _currentAudio.pause();
    _currentAudio = null;
  }
}

export function isSpeaking() {
  return !!_currentAudio && !_currentAudio.paused;
}

// ── STT recording ─────────────────────────────────────────────────────────────

let _mediaRecorder = null;
let _chunks        = [];

export async function startRecording() {
  const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
  _chunks      = [];
  const mimeType = MediaRecorder.isTypeSupported('audio/webm;codecs=opus')
    ? 'audio/webm;codecs=opus'
    : 'audio/webm';
  _mediaRecorder = new MediaRecorder(stream, { mimeType });
  _mediaRecorder.ondataavailable = e => { if (e.data.size > 0) _chunks.push(e.data); };
  _mediaRecorder.start(100);
}

export function isRecording() {
  return !!_mediaRecorder && _mediaRecorder.state === 'recording';
}

export async function stopRecordingAndTranscribe() {
  if (!_mediaRecorder) return '';
  const mimeType = _mediaRecorder.mimeType;
  await new Promise(resolve => {
    _mediaRecorder.onstop = resolve;
    _mediaRecorder.stop();
    _mediaRecorder.stream.getTracks().forEach(t => t.stop());
  });
  _mediaRecorder = null;

  const blob = new Blob(_chunks, { type: mimeType });
  const form = new FormData();
  form.append('audio', blob, 'recording.webm');
  const resp = await fetch(PATHS.voice.stt.transcribe, { method: 'POST', body: form });
  if (!resp.ok) { _cb.onToast('STT failed'); return ''; }
  const { text } = await resp.json();
  _cb.onTranscript(text);
  return text;
}

// ── Workstation card ──────────────────────────────────────────────────────────

export async function updateWorkstationCard() {
  const bodyEl = document.getElementById('mc-voice-body');
  if (!bodyEl) return;

  const [tts, stt] = await Promise.allSettled([loadTTSConfig(), loadSTTConfig()]);
  const ttsData = tts.status === 'fulfilled' ? tts.value : null;
  const sttData = stt.status === 'fulfilled' ? stt.value : null;

  bodyEl.innerHTML = `
    <div class="mc-row"><span class="mc-key">TTS</span>
      <span class="mc-val">${ttsData?.provider ?? '—'}</span></div>
    <div class="mc-row"><span class="mc-key">STT</span>
      <span class="mc-val">${sttData?.provider ?? '—'}</span></div>
    <div class="mc-row"><span class="mc-key">Voice</span>
      <span class="mc-val mc-truncate">${ttsData?.voice ?? '—'}</span></div>`;
}
