/**
 * modules/knowledge.js — Knowledge base document management.
 */

import { http, PATHS } from '../api.js';

const _cb = { onToast: () => {} };
export function setCallbacks(cbs) { Object.assign(_cb, cbs); }

export async function listDocuments() {
  const { documents } = await http.get(PATHS.knowledge.docs);
  return documents;
}

export async function search(query, opts = {}) {
  const params = new URLSearchParams({ q: query, ...opts });
  return http.get(`${PATHS.knowledge.search}?${params}`);
}

export async function ingest(payload) {
  const result = await http.post(PATHS.knowledge.ingest, payload);
  _cb.onToast('Document ingested');
  return result;
}

export async function deleteDoc(id) {
  await http.del(PATHS.knowledge.doc(id));
  _cb.onToast('Document deleted');
}

export async function repair() {
  const { repaired } = await http.post(PATHS.knowledge.repair, {});
  _cb.onToast(`Index repaired (${repaired} chunks)`);
  return repaired;
}

export async function renderPanel(containerEl) {
  if (!containerEl) return;
  containerEl.innerHTML = '<span style="color:var(--text3)">Loading…</span>';
  const docs = await listDocuments().catch(() => []);
  if (!docs.length) {
    containerEl.innerHTML = '<span style="color:var(--text3)">No documents.</span>';
    return;
  }
  containerEl.innerHTML = '';
  const ul = document.createElement('ul');
  ul.style.cssText = 'margin:0;padding:0;list-style:none;display:flex;flex-direction:column;gap:6px;';
  docs.forEach(d => {
    const li = document.createElement('li');
    li.style.cssText = 'display:flex;align-items:center;gap:8px;font-size:13px;';
    li.innerHTML = `
      <span style="flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="${_esc(d.source)}">
        ${_esc(d.title || d.source)}
      </span>
      <span style="font-size:11px;color:var(--text3)">${d.source_type}</span>
      <button class="icon-btn danger" data-id="${d.id}" title="Delete">🗑</button>`;
    li.querySelector('button').addEventListener('click', async () => {
      await deleteDoc(d.id);
      renderPanel(containerEl);
    });
    ul.appendChild(li);
  });
  containerEl.appendChild(ul);
}

function _esc(s) {
  return String(s ?? '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}
