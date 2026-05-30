/**
 * account_gate.js — MVP 账号选择/创建（进入工作站前）。
 */

import * as accounts from '../modules/accounts.js';
import { bus } from '../eventBus.js';

let _bound = false;

function _el(id) {
  return document.getElementById(id);
}

export function showAccountGate() {
  const overlay = _el('account-gate-overlay');
  if (overlay) overlay.classList.remove('hidden');
  document.getElementById('s-landing')?.classList.add('hidden');
  document.getElementById('s-workspace')?.classList.add('hidden');
  void refreshAccountList();
}

export function hideAccountGate() {
  _el('account-gate-overlay')?.classList.add('hidden');
}

async function refreshAccountList() {
  const listEl = _el('account-gate-list');
  if (!listEl) return;
  listEl.textContent = '加载中…';
  const rows = await accounts.listAccounts().catch(() => []);
  if (!rows.length) {
    listEl.innerHTML = '<p class="account-gate-empty">暂无账号，请创建。</p>';
    return;
  }
  listEl.innerHTML = '';
  const currentId = accounts.getStoredAccountId();
  for (const acc of rows) {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'account-gate-item' + (acc.account_id === currentId ? ' selected' : '');
    btn.textContent = acc.display_name || acc.account_id.slice(0, 8);
    btn.title = acc.interactor_id;
    btn.addEventListener('click', () => onSelectAccount(acc));
    listEl.appendChild(btn);
  }
}

async function onSelectAccount(account) {
  await accounts.selectAccount(account);
  hideAccountGate();
  bus.emit('account:selected', account);
}

async function onCreateAccount() {
  const input = _el('account-gate-name');
  const name = (input?.value || '').trim();
  if (!name) {
    bus.emit('toast', '请输入显示名称');
    return;
  }
  const account = await accounts.createAccount(name);
  await accounts.selectAccount(account);
  if (input) input.value = '';
  hideAccountGate();
  bus.emit('account:selected', account);
}

export function bindAccountGate() {
  if (_bound) return;
  _bound = true;
  _el('account-gate-create')?.addEventListener('click', () => {
    onCreateAccount().catch(e => bus.emit('toast', e.message));
  });
  _el('account-gate-refresh')?.addEventListener('click', () => {
    refreshAccountList().catch(e => bus.emit('toast', e.message));
  });
}

/**
 * 若已选账号则绑定渠道；否则显示 gate。
 * @returns {Promise<boolean>} 是否可进入工作站
 */
export async function ensureAccountReady() {
  bindAccountGate();
  if (accounts.hasStoredAccount()) {
    const stored = accounts.getStoredAccount();
    const channelId = accounts.getCurrentInteractorId();
    await accounts.bindVisitor(stored.account_id, channelId);
    return true;
  }
  showAccountGate();
  return false;
}
