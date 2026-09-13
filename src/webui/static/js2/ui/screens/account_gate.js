/**
 * ui/screens/account_gate.js — MVP 账号选择/创建遮罩（进入工作站前）。
 */

import { bus, EVENTS } from '../../store/bus.js';
import * as accounts from '../../features/accounts.js';

const DEFAULT_VISITOR_NAME = '荧';

let _bound = false;

const _id = id => document.getElementById(id);

function _ensureDefaultNameInput() {
  const input = _id('account-gate-name');
  if (input && !(input.value || '').trim()) input.value = DEFAULT_VISITOR_NAME;
}

export function showAccountGate() {
  _id('account-gate-overlay')?.classList.remove('hidden');
  _id('s-landing')?.classList.add('hidden');
  _id('s-workspace')?.classList.add('hidden');
  _ensureDefaultNameInput();
  void refreshAccountList();
}

export function hideAccountGate() {
  _id('account-gate-overlay')?.classList.add('hidden');
}

async function refreshAccountList() {
  const listEl = _id('account-gate-list');
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
  bus.emit(EVENTS.accountSelected, account);
}

async function onCreateAccount() {
  const input = _id('account-gate-name');
  const name = (input?.value || '').trim() || DEFAULT_VISITOR_NAME;
  const account = await accounts.createAccount(name);
  await accounts.selectAccount(account);
  if (input) input.value = DEFAULT_VISITOR_NAME;
  hideAccountGate();
  bus.emit(EVENTS.accountSelected, account);
}

export function bindAccountGate() {
  if (_bound) return;
  _bound = true;
  _id('account-gate-create')?.addEventListener('click', () => {
    onCreateAccount().catch(e => bus.emit(EVENTS.toastShow, e.message));
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
    return accounts
      .bindVisitor(stored.account_id, channelId)
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
