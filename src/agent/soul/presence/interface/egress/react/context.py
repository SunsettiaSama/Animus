from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from agent.soul.memory.embed_text import cosine_similarity
from config.soul.presence.interface_config import InterfaceReactConfig

from .chunker import split_text_chunks
from .ports import EmbeddingPort

if TYPE_CHECKING:
    from agent.soul.service import SoulService


@dataclass
class SessionContextChunk:
    index: int
    text: str
    score: float = 0.0


@dataclass
class SessionContextResult:
    session_id: str
    query: str
    full_context_chars: int
    chunks: list[SessionContextChunk] = field(default_factory=list)
    injected_text: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "query": self.query,
            "full_context_chars": self.full_context_chars,
            "chunks": [
                {"index": c.index, "text": c.text, "score": c.score}
                for c in self.chunks
            ],
            "injected_text": self.injected_text,
        }


class SessionContextRetriever:
    """将完整会话上下文分块 → 向量检索 → 注入最相关片段。"""

    def __init__(
        self,
        soul: SoulService,
        *,
        embedder: EmbeddingPort | None = None,
        cfg: InterfaceReactConfig | None = None,
    ) -> None:
        self._soul = soul
        self._embedder = embedder
        self._cfg = cfg or InterfaceReactConfig.default()

    def set_embedder(self, embedder: EmbeddingPort | None) -> None:
        self._embedder = embedder

    def _resolve_embedder(self) -> EmbeddingPort:
        if self._embedder is not None:
            return self._embedder
        embedder = self._soul.resolve_embedding_port()
        if embedder is None:
            raise RuntimeError("session_context 需要顶层 embedding 服务")
        return embedder

    def gather_full_context(self, session_id: str) -> str:
        parts: list[str] = []
        snap = self._soul.presence.snapshot(session_id)
        parts.append(f"【当下态】\n{snap.state.affect.narrative}".strip())

        dialogue = self._soul.experience.dialogue.state(session_id)
        if dialogue is not None:
            from agent.soul.presence.experience.dialogue.session import render_session_transcript

            transcript = render_session_transcript(dialogue.session).strip()
            if transcript:
                parts.append(f"【全量对话】\n{transcript}")
            wm = dialogue.working_memory_text().strip()
            if wm:
                parts.append(f"【工作记忆】\n{wm}")

        wm_fsm = snap.state.cognition.working_memory.strip()
        if wm_fsm:
            parts.append(f"【FSM工作记忆】\n{wm_fsm}")

        text = "\n\n".join(p for p in parts if p)
        limit = self._cfg.session_context_max_chars
        if len(text) > limit:
            return text[:limit]
        return text

    def retrieve(
        self,
        session_id: str,
        *,
        query: str,
        top_k: int | None = None,
    ) -> SessionContextResult:
        full = self.gather_full_context(session_id)
        k = top_k if top_k is not None else self._cfg.session_context_top_k
        if not full.strip():
            return SessionContextResult(
                session_id=session_id,
                query=query,
                full_context_chars=0,
            )
        if not query.strip():
            return SessionContextResult(
                session_id=session_id,
                query=query,
                full_context_chars=len(full),
                injected_text=full[: self._cfg.chunk_size],
            )

        pieces = split_text_chunks(
            full,
            chunk_size=self._cfg.chunk_size,
            overlap=self._cfg.chunk_overlap,
        )
        if not pieces:
            return SessionContextResult(
                session_id=session_id,
                query=query,
                full_context_chars=len(full),
            )

        embedder = self._resolve_embedder()
        query_vec = embedder.embed(query.strip())
        doc_vecs = embedder.embed_documents(pieces)

        scored: list[SessionContextChunk] = []
        for idx, (piece, vec) in enumerate(zip(pieces, doc_vecs)):
            score = cosine_similarity(query_vec, vec) if vec else 0.0
            scored.append(SessionContextChunk(index=idx, text=piece, score=score))
        scored.sort(key=lambda c: c.score, reverse=True)
        picked = scored[: max(1, k)]
        injected = "\n---\n".join(c.text for c in picked)
        return SessionContextResult(
            session_id=session_id,
            query=query,
            full_context_chars=len(full),
            chunks=picked,
            injected_text=injected,
        )
