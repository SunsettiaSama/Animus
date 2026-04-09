from __future__ import annotations

from config.react.memory.retrieve_config import RetrieveConfig
from react.memory.long_term.retrieve.base import (
    RetrieveMode,
    RetrieveRequest,
    RetrieveResult,
)
from react.memory.long_term.retrieve.triggers import detect_mode
from react.memory.long_term.store import LongTermStore

_MODE_PARAMS: dict[RetrieveMode, tuple[str, str]] = {
    RetrieveMode.LIGHT:      ("light_top_k",      "light_min_score"),
    RetrieveMode.HEAVY:      ("heavy_top_k",      "heavy_min_score"),
    RetrieveMode.SUPPLEMENT: ("supplement_top_k", "supplement_min_score"),
    RetrieveMode.PROFILE:    ("profile_top_k",    "profile_min_score"),
}


class Retriever:
    def __init__(self, store: LongTermStore, cfg: RetrieveConfig):
        self._store = store
        self._cfg = cfg

    # --- 主入口：显式指定模式 ---

    def retrieve(self, req: RetrieveRequest) -> RetrieveResult:
        top_k_attr, min_score_attr = _MODE_PARAMS[req.mode]
        top_k: int = getattr(self._cfg, top_k_attr)
        min_score: float = getattr(self._cfg, min_score_attr)

        hits = self._search(req.query, top_k, min_score)
        return RetrieveResult(
            mode=req.mode,
            hits=hits,
            combined="\n\n".join(hits),
        )

    # --- 自动模式：根据上下文自动判断触发场景 ---

    def auto_retrieve(
        self,
        query: str = "",
        is_session_start: bool = False,
        short_term_context: str = "",
        medium_term_context: str = "",
    ) -> RetrieveResult:
        mode = detect_mode(
            query=query,
            cfg=self._cfg,
            is_session_start=is_session_start,
            short_term_context=short_term_context,
            medium_term_context=medium_term_context,
        )

        # 场景4：会话启动时使用预设档案查询语句
        effective_query = (
            self._cfg.profile_query
            if mode == RetrieveMode.PROFILE and not query
            else query
        )

        return self.retrieve(
            RetrieveRequest(
                query=effective_query,
                mode=mode,
                short_term_context=short_term_context,
                medium_term_context=medium_term_context,
            )
        )

    # --- 内部：带阈值过滤的检索 ---

    def _search(self, query: str, top_k: int, min_score: float) -> list[str]:
        pairs = self._store.search_with_scores(query, top_k)
        return [text for score, text in pairs if score >= min_score]
