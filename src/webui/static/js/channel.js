/**
 * channel.js — 唯一通信渠道 ID（localStorage 持久化，模拟人与人之间固定会话）。
 */

const STORAGE_KEY = 'react_speak_channel_id';

export function getChannelId() {
  let id = localStorage.getItem(STORAGE_KEY);
  if (!id) {
    id = crypto.randomUUID();
    localStorage.setItem(STORAGE_KEY, id);
  }
  return id;
}
