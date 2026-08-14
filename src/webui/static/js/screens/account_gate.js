/**
 * account_gate.js — MVP 账号选择/创建（进入工作站前）。
 */

import * as accounts from '../modules/accounts.js';
import { bus } from '../eventBus.js';

const DEFAULT_VISITOR_NAME = '荧';

let _bound = false;

function _el(id) {
  return document.getElementById(id);
}

function _ensureDefaultNameInput() {
  const input = _el('account-gate-name');
  if (input && !(input.value || '').trim()) {
    input.value = DEFAULT_VISITOR_NAME;
  }
}

export function showAccountGate() {
  const overlay = _el('account-gate-overlay');
  if (overlay) overlay.classList.remove('hidden');
  document.getElementById('s-landing')?.classList.add('hidden');
  document.getElementById('s-workspace')?.classList.add('hidden');
  _ensureDefaultNameInput();
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
  const name = (input?.value || '').trim() || DEFAULT_VISITOR_NAME;
  const account = await accounts.createAccount(name);
  await accounts.selectAccount(account);
  if (input) input.value = DEFAULT_VISITOR_NAME;
  hideAccountGate();
  bus.emit('account:selected', account);
}

export function bindAccountGate() {
  if (_bound) return;
  _bound = true;
  _el('account-gate-create')?.addEventListener('click', () => {
    onCreateAccount().catch(e => bus.emit('toast', e.message));
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
    return accounts.bindVisitor(stored.account_id, channelId)
      .then(() => true)
      .catch(() => {
        accounts.clearStoredAccount();
        showAccountGate();
        return false;
      });
  }
  showAccountGate();
  return false;
}
