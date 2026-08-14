/**
 * WorkEventStore — aggregate work_* events by work_id.
 */
import { S, set } from '../state.js';

const _items = new Map(); // work_id → item
const _listeners = new Set();

function _syncState() {
  const active = [];
  for (const [id, item] of _items) {
    if (!['finished', 'failed', 'aborted', 'declined', 'fallback_to_speak'].includes(item.status)) {
      active.push(id);
    }
  }
  set('activeWorkIds', active, true);
  set('workBusy', active.length > 0, true);
}

function _notify(item, event) {
  _listeners.forEach(fn => fn(item, event));
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

export function ingest(event) {
  if (!event || !event.work_id) return null;
  const seq = Number(event.seq || 0);
  let item = _items.get(event.work_id);
  if (!item) {
    item = {
      workId: event.work_id,
      status: event.status || 'detected',
      question: event.payload?.question || '',
      reason: event.reason || '',
      reasonCode: event.reason_code || '',
      answer: '',
      matchedTerms: event.payload?.matched_terms || [],
      monitor: {},
      message: event.message || '',
      prompt: event.payload?.prompt || '',
      suggestedAction: event.payload?.suggested_action || '',
      events: [],
      lastSeq: 0,
      createdAt: event.created_at || new Date().toISOString(),
      updatedAt: event.created_at || new Date().toISOString(),
      restored: false,
    };
    _items.set(event.work_id, item);
  }
  if (seq && seq <= item.lastSeq) return item;
  if (seq) item.lastSeq = seq;

  item.status = event.status || item.status;
  item.message = event.message || item.message;
  item.updatedAt = event.created_at || new Date().toISOString();
  if (event.reason) item.reason = event.reason;
  if (event.reason_code) item.reasonCode = event.reason_code;
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
    reason_code: event.reason_code || '',
    payload: event.payload || {},
    created_at: event.created_at,
  });

  _syncState();
  _notify(item, event);
  return item;
}

// Ensure state keys exist
if (!Array.isArray(S.activeWorkIds)) set('activeWorkIds', [], true);
if (typeof S.workBusy !== 'boolean') set('workBusy', false, true);
