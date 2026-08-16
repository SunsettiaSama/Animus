/**
 * channel.js — 记忆渠道 ID（MVP：等于当前账号的 interactor_id）。
 * Speak 短期生命线与 history 的 convId 分离：同一 channel 共用一条 live session。
 */

import { getCurrentInteractorId, getStoredAccountId } from './modules/accounts.js';

const LEGACY_KEY = 'react_speak_channel_id';

export function getChannelId() {
  const iid = getCurrentInteractorId();
  if (iid) return iid;
  const legacy = (localStorage.getItem(LEGACY_KEY) || '').trim();
  if (legacy && getStoredAccountId()) return legacy;
  return '';
}

export function requireChannelId() {
  const id = getChannelId();
  if (!id) {
    throw new Error('请先选择来访账号');
  }
  return id;
}

/** Speak 内在短期态唯一 key：不受前端对话页（convId）切换影响。 */
export function speakLiveSessionId(channelId = '') {
  const ch = String(channelId || getChannelId() || '').trim();
  if (ch) return `live:${ch}`;
  return 'live:anon';
}

export function isLiveSessionId(value) {
  return String(value || '').trim().startsWith('live:');
}

export function channelIdFromLiveSession(sessionId = '') {
  const sid = String(sessionId || '').trim();
  if (!isLiveSessionId(sid)) return '';
  return sid.slice('live:'.length).trim();
}
