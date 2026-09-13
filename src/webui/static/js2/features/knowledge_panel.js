/**
 * features/knowledge_panel.js — 知识库面板（KB）渲染与检索/入库。
 */

import { API } from '../protocol/http_api.js';
import { http } from '../transport/http.js';
import { bus, EVENTS } from '../store/bus.js';

const _toast = text => bus.emit(EVENTS.toastShow, String(text ?? ''));
const _esc = s => String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');

export async function search(query, mode = 'hybrid') {
  return http.post(API.knowledge.search, { query, mode });
}

export async function ingest(formData) {
  return http.upload(API.knowledge.ingest, formData);
}

export async function listDocuments() {
  const data = await http.get(API.knowledge.docs).catch(() => ({ documents: [] }));
  return data.documents ?? [];
}

export async function deleteDocument(docId) {
  return http.del(API.knowledge.doc(docId));
}

export async function repairIndex() {
  return http.post(API.knowledge.fixIndex);
}

/** 渲染 KB 文档列表到容器。 */
export async function renderPanel(containerEl) {
  if (!containerEl) return;
  const docs = await listDocuments();
  if (!docs.length) {
    containerEl.innerHTML = '<div class="kb-empty">暂无文档</div>';
    return;
  }
  containerEl.innerHTML = docs.map(d => `
    <div class="kb-doc-row" data-doc-id="${_esc(d.doc_id)}">
      <span class="kb-doc-name" title="${_esc(d.source ?? '')}">${_esc(d.name || d.doc_id)}</span>
      <span class="kb-doc-meta">${_esc(String(d.chunks ?? ''))} chunks</span>
      <button class="kb-doc-del" title="删除">🗑</button>
    </div>`).join('');

  containerEl.querySelectorAll('.kb-doc-del').forEach(btn => {
    btn.addEventListener('click', async e => {
      e.stopPropagation();
      const row = btn.closest('.kb-doc-row');
      const docId = row?.dataset.docId;
      if (!docId || !confirm('删除该文档？')) return;
      await deleteDocument(docId);
      _toast('文档已删除');
      renderPanel(containerEl);
    });
  });
}
