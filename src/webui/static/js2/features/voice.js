/**
 * features/voice.js — TTS 合成播放与 STT 录音转写。
 */

import { API } from '../protocol/http_api.js';
import { http } from '../transport/http.js';
import { bus, EVENTS } from '../store/bus.js';

const _toast = text => bus.emit(EVENTS.toastShow, String(text ?? ''));

// ── TTS / STT config ────────────────────────────────────────────────────────

export async function loadTTSConfig() {
  return http.get(API.voice.tts.config);
}

export async function saveTTSConfig(payload) {
  await http.post(API.voice.tts.save, payload);
  _toast('TTS config saved');
}

export async function loadSTTConfig() {
  return http.get(API.voice.stt.config);
}

export async function saveSTTConfig(payload) {
  await http.post(API.voice.stt.save, payload);
  _toast('STT config saved');
}

// ── TTS synthesis ───────────────────────────────────────────────────────────

let _currentAudio = null;

export async function speak(text) {
  stopSpeaking();
  const resp = await fetch(API.voice.tts.synth, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ text }),
  });
  if (!resp.ok) {
    _toast('TTS failed');
    return null;
  }
  const blob = await resp.blob();
  const url = URL.createObjectURL(blob);
  const audio = new Audio(url);
  _currentAudio = audio;
  audio.addEventListener('ended', () => {
    URL.revokeObjectURL(url);
    _currentAudio = null;
  });
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
  return Boolean(_currentAudio) && !_currentAudio.paused;
}

// ── STT recording ───────────────────────────────────────────────────────────

let _mediaRecorder = null;
let _chunks = [];

export async function startRecording() {
  const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
  _chunks = [];
  const mimeType = MediaRecorder.isTypeSupported('audio/webm;codecs=opus')
    ? 'audio/webm;codecs=opus'
    : 'audio/webm';
  _mediaRecorder = new MediaRecorder(stream, { mimeType });
  _mediaRecorder.ondataavailable = e => {
    if (e.data.size > 0) _chunks.push(e.data);
  };
  _mediaRecorder.start(100);
}

export function isRecording() {
  return Boolean(_mediaRecorder) && _mediaRecorder.state === 'recording';
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
  const resp = await fetch(API.voice.stt.transcribe, { method: 'POST', body: form });
  if (!resp.ok) {
    _toast('STT failed');
    return '';
  }
  const { text } = await resp.json();
  return text;
}
