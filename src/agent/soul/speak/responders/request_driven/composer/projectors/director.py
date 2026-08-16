from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from .base import ContextView

if TYPE_CHECKING:
    from ..manager import ComposeManager


@dataclass(frozen=True)
class DirectorContextView:
    session_id: str
    brief: str = ""
    memory_brief: str = ""
    history_brief: str = ""
    director_memory_texts: tuple[str, ...] = ()
    director_memory_ids: tuple[str, ...] = ()
    role_memory_texts: tuple[str, ...] = ()
    role_memory_ids: tuple[str, ...] = ()
    meta: dict[str, object] = field(default_factory=dict)


class DirectorContextPort:
    """导演侧投影：独立检索 + 可见角色命中；可继承覆写预算/字段。"""

    def __init__(self, manager: ComposeManager, *, max_chars: int = 500) -> None:
        self._manager = manager
        self._max_chars = max(80, max_chars)

    def project(self, session_id: str, *, user_text: str = "") -> DirectorContextView:
        sid = session_id.strip()
        distilled, working = self._manager.trajectory_snapshot(sid)
        # 角色检索：供导演看见（只读参考）
        role_hits = self._manager.retrieve_for_role(sid, user_text=user_text)
        # 导演自己的检索：不复用角色命中列表
        director_hits = self._manager.retrieve_for_director(sid, user_text=user_text)
        history = " | ".join(distilled[-3:])
        working_brief = " | ".join(f"U:{u} A:{a}" for u, a in working[-2:])
        dir_mem = " | ".join(hit.unit.text for hit in director_hits[:3])
        role_mem = " | ".join(hit.unit.text for hit in role_hits[:3])
        brief_parts = [p for p in (user_text.strip(), history, working_brief, dir_mem) if p]
        brief = self._clip(" // ".join(brief_parts))
        return DirectorContextView(
            session_id=sid,
            brief=brief,
            memory_brief=self._clip(dir_mem),
            history_brief=self._clip(history),
            director_memory_texts=tuple(hit.unit.text for hit in director_hits),
            director_memory_ids=tuple(hit.unit.unit_id for hit in director_hits),
            role_memory_texts=tuple(hit.unit.text for hit in role_hits),
            role_memory_ids=tuple(hit.unit.unit_id for hit in role_hits),
            meta={
                "source": "compose_manager.director_own_retrieve",
                "role_hits_visible": True,
                "intervene_max": self._manager.config.director_memory_intervene_max,
                "role_memory_brief": self._clip(role_mem),
            },
        )

    def as_context_view(self, session_id: str, *, user_text: str = "") -> ContextView:
        view = self.project(session_id, user_text=user_text)
        return ContextView(
            session_id=view.session_id,
            history_distilled=(),
            working_turns=(),
            memory_hits=tuple(
                (mid, text, 0.0, "director")
                for mid, text in zip(view.director_memory_ids, view.director_memory_texts)
            ),
            meta=dict(view.meta),
        )

    def _clip(self, text: str) -> str:
        text = text.strip()
        if len(text) <= self._max_chars:
            return text
        return text[: self._max_chars]
