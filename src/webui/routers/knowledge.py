from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from state import get_state

router = APIRouter()


class KBIngestRequest(BaseModel):
    text: str
    title: str = ""
    domain: str = ""
    concept: str = ""


def _get_kb():
    state = get_state()
    if state.kb is None:
        from knowledge import KnowledgeBase
        state.kb = KnowledgeBase.from_config(state.kb_cfg)
        state.kb.setup()
    return state.kb


@router.get("/api/kb/documents")
def kb_list_documents():
    kb   = _get_kb()
    docs = kb.store.list_documents(include_deleted=False)
    return {
        "documents": [
            {
                "id":          d.id,
                "source":      d.source,
                "source_type": d.source_type,
                "title":       d.title or "",
                "status":      d.status,
                "meta":        d.meta or {},
                "created_at":  str(d.created_at),
            }
            for d in docs
        ]
    }


@router.get("/api/kb/search")
def kb_search(q: str, top_k: int = 5, top_k_each: int = 3, mode: str = "hybrid"):
    kb = _get_kb()
    if mode == "keyword":
        results = kb.search_keyword(q, top_k=top_k)
    elif mode == "semantic":
        results = kb.search_semantic(q, top_k=top_k)
    else:
        results = kb.hybrid_search(q, top_k_each=top_k_each)
    return {
        "query":  q,
        "mode":   mode,
        "results": [
            {
                "chunk_id": r.chunk_id,
                "doc_id":   r.doc_id,
                "score":    r.score,
                "source":   r.source,
                "content":  r.content,
                "meta":     r.meta,
            }
            for r in results
        ],
    }


@router.post("/api/kb/ingest")
def kb_ingest(req: KBIngestRequest):
    kb   = _get_kb()
    meta: dict = {}
    if req.domain:
        meta["domain"] = req.domain
    if req.concept:
        meta["concept"] = req.concept
    doc_id = kb.ingest_text(
        req.text,
        source="webui",
        source_type="manual",
        title=req.title or (f"{req.domain}/{req.concept}" if req.domain else "manual"),
        meta=meta if meta else None,
    )
    return {"status": "ok", "doc_id": doc_id}


@router.delete("/api/kb/documents/{doc_id}")
def kb_delete_document(doc_id: str):
    _get_kb().delete(doc_id)
    return {"status": "ok"}


@router.post("/api/kb/repair")
@router.post("/api/kb/fix-index")
def kb_repair():
    kb    = _get_kb()
    count = kb.repair()
    return {"status": "ok", "repaired": count}
