/**
 * accounts.js — 外部来访账号（MVP：本地选择，无密码）。
 */

import { http, PATHS } from '../api.js';

const STORAGE_ACCOUNT = 'react_current_account_id';
const STORAGE_INTERACTOR = 'react_current_interactor_id';

let _cached = null;

export function getStoredAccountId() {
  return (localStorage.getItem(STORAGE_ACCOUNT) || '').trim();
}

export function getCurrentInteractorId() {
  const fromCache = (localStorage.getItem(STORAGE_INTERACTOR) || '').trim();
  if (fromCache) return fromCache;
  return (_cached?.interactor_id || '').trim();
}

export function getStoredAccount() {
  if (_cached) return _cached;
  const accountId = getStoredAccountId();
  if (!accountId) return null;
  const iid = getCurrentInteractorId();
  if (!iid) return { account_id: accountId, interactor_id: '', display_name: '' };
  return { account_id: accountId, interactor_id: iid, display_name: '' };
}

function _persistSelection(account) {
  _cached = {
    account_id: account.account_id,
    interactor_id: account.interactor_id,
    display_name: account.display_name || '',
  };
  localStorage.setItem(STORAGE_ACCOUNT, _cached.account_id);
  localStorage.setItem(STORAGE_INTERACTOR, _cached.interactor_id);
}

export function clearStoredAccount() {
  _cached = null;
  localStorage.removeItem(STORAGE_ACCOUNT);
  localStorage.removeItem(STORAGE_INTERACTOR);
}

export async function listAccounts() {
  const data = await http.get(PATHS.accounts.list);
  return data.accounts || [];
}

export async function createAccount(displayName, meta = null) {
  const body = { display_name: displayName };
  if (meta) body.meta = meta;
  const data = await http.post(PATHS.accounts.create, body);
  return data.account;
}

export async function bindVisitor(accountId, channelId) {
  return http.post(PATHS.soul.visitorBind, {
    account_id: accountId,
    channel_id: channelId,
  });
}

export async function selectAccount(account) {
  _persistSelection(account);
  const channelId = account.interactor_id;
  await bindVisitor(account.account_id, channelId);
  return account;
}

export function hasStoredAccount() {
  const id = getStoredAccountId();
  const iid = getCurrentInteractorId();
  return Boolean(id && iid);
}
