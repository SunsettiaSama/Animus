/**
 * channel.js — 记忆渠道 ID（MVP：等于当前账号的 interactor_id）。
 * 与 history 里的 session_id（后端 Speak 上下文）分离。
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
