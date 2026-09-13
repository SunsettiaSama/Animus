/**
 * store/work_store.js — work_* 事件聚合（迁移自旧 work/store.js）。
 *
 * work_id → item 聚合 + 终态判定；seq 单调去重。
 * UI 通过 subscribe / bus work:* 事件渲染确认卡、进度与监控面板。
 */

import { bus, EVENTS } from './bus.js';
import { update } from './session_store.js';
import { WORK_TERMINAL_STATUSES } from '../protocol/agent_events.js';

const _items = new Map(); // work_id → item
const _listeners = new Set();

function _syncState() {
  const active = [];
  for (const [id, item] of _items) {
    if (!WORK_TERMINAL_STATUSES.includes(item.status)) active.push(id);
  }
  update({ activeWorkIds: active, workBusy: active.length > 0 }, { silent: true });
  bus.emit(EVENTS.workBusy, { busy: active.length > 0, activeIds: active });
}

function _notify(item, event) {
  for (const fn of [..._listeners]) {
    try {
      fn(item, event);
    } catch (err) {
      console.warn('[work_store] subscriber error', err);
    }
  }
  bus.emit(EVENTS.workChanged, { item, event });
}

export function subscribe(fn) {
  _listeners.add(fn);
  return () => _listeners.delete(fn);
}

export function clear() {
  _items.clear();
  _syncState();
}

export function get(workId) {
  return _items.get(workId) || null;
}

export function all() {
  return [..._items.values()];
}

export function summariesForHistory() {
  return all().map(item => ({
    work_id: item.workId,
    status: item.status,
    question: item.question,
    reason: item.reason,
    reason_code: item.reasonCode,
    answer: item.answer,
    matched_terms: item.matchedTerms,
    monitor: item.monitor,
    events: item.events.slice(-20),
    created_at: item.createdAt,
    updated_at: item.updatedAt,
  }));
}

export function restoreFromHistory(workItems) {
  clear();
  (workItems || []).forEach(w => {
    const id = w.work_id;
    if (!id) return;
    _items.set(id, {
      workId: id,
      status: w.status || 'finished',
      question: w.question || '',
      reason: w.reason || '',
      reasonCode: w.reason_code || '',
      answer: w.answer || '',
      matchedTerms: w.matched_terms || [],
      monitor: w.monitor || {},
      message: w.message || '',
      prompt: '',
      suggestedAction: '',
      events: Array.isArray(w.events) ? [...w.events] : [],
      lastSeq: 0,
      createdAt: w.created_at || '',
      updatedAt: w.updated_at || '',
      restored: true,
    });
  });
  _syncState();
}

/**
 * 摄入一个 work_* 帧（类型化事件，来自 protocol/agent_events.js）。
 * @param {{type:string, workId:string, status:string, message:string,
 *          payload:object, reason:string, reasonCode:string, seq:number,
 *          createdAt:string}} event
 */
export function ingest(event) {
  if (!event || !event.workId) return null;
  const seq = Number(event.seq || 0);
  let item = _items.get(event.workId);
  if (!item) {
    item = {
      workId: event.workId,
      status: event.status || 'detected',
      question: event.payload?.question || '',
      reason: event.reason || '',
      reasonCode: event.reasonCode || '',
      answer: '',
      matchedTerms: event.payload?.matched_terms || [],
      monitor: {},
      message: event.message || '',
      prompt: event.payload?.prompt || '',
      suggestedAction: event.payload?.suggested_action || '',
      events: [],
      lastSeq: 0,
      createdAt: event.createdAt || new Date().toISOString(),
      updatedAt: event.createdAt || new Date().toISOString(),
      restored: false,
    };
    _items.set(event.workId, item);
  }
  if (seq && seq <= item.lastSeq) return item;
  if (seq) item.lastSeq = seq;

  item.status = event.status || item.status;
  item.message = event.message || item.message;
  item.updatedAt = event.createdAt || new Date().toISOString();
  if (event.reason) item.reason = event.reason;
  if (event.reasonCode) item.reasonCode = event.reasonCode;
  if (event.payload?.question) item.question = event.payload.question;
  if (event.payload?.matched_terms) item.matchedTerms = event.payload.matched_terms;
  if (event.payload?.prompt) item.prompt = event.payload.prompt;
  if (event.payload?.suggested_action) item.suggestedAction = event.payload.suggested_action;
  if (event.type === 'work_monitor' || event.type === 'work_progress') {
    item.monitor = { ...item.monitor, ...(event.payload || {}) };
  }
  if (event.type === 'work_finished') {
    item.answer = event.payload?.answer || event.message || '';
  }
  if (event.type === 'work_failed' || event.type === 'work_aborted' || event.type === 'work_declined') {
    item.reason = event.reason || event.message || item.reason;
  }

  item.events.push({
    type: event.type,
    status: event.status,
    message: event.message,
    seq,
    reason: event.reason || '',
    reason_code: event.reasonCode || '',
    payload: event.payload || {},
    created_at: event.createdAt,
  });

  _syncState();
  _notify(item, event);
  return item;
}
