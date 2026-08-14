from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar

from .config import ComposeManagerConfig
from .manager import ComposeManager
from .projectors.director import DirectorContextView
from .projectors.role_view import RoleContextView

T = TypeVar("T")


class ComposeManagerGateway:
    """L0：flag + 新链调用；关闭或异常时走 legacy（不吞业务 raise 到调用方可选）。"""

    def __init__(
        self,
        manager: ComposeManager | None = None,
        *,
        config: ComposeManagerConfig | None = None,
        on_fallback: Callable[[str, BaseException | None], None] | None = None,
    ) -> None:
        self._manager = manager or ComposeManager(config=config)
        self._on_fallback = on_fallback

    @property
    def manager(self) -> ComposeManager:
        return self._manager

    @property
    def enabled(self) -> bool:
        return self._manager.enabled

    def run_or_legacy(
        self,
        label: str,
        new_fn: Callable[[], T],
        legacy_fn: Callable[[], T],
    ) -> T:
        if not self.enabled:
            if self._on_fallback is not None:
                self._on_fallback(label, None)
            return legacy_fn()
        try:
            return new_fn()
        except Exception as exc:
            if self._on_fallback is not None:
                self._on_fallback(label, exc)
            return legacy_fn()

    def context_for_role_or_empty(self, session_id: str, *, user_text: str = "") -> RoleContextView:
        if not self.enabled:
            return RoleContextView(session_id=session_id.strip())
        try:
            return self._manager.context_for_role(session_id, user_text=user_text)
        except Exception as exc:
            if self._on_fallback is not None:
                self._on_fallback("context_for_role", exc)
            return RoleContextView(session_id=session_id.strip(), meta={"fallback": True})

    def context_for_director_or_empty(
        self,
        session_id: str,
        *,
        user_text: str = "",
    ) -> DirectorContextView:
        if not self.enabled:
            return DirectorContextView(session_id=session_id.strip())
        try:
            return self._manager.context_for_director(session_id, user_text=user_text)
        except Exception as exc:
            if self._on_fallback is not None:
                self._on_fallback("context_for_director", exc)
            return DirectorContextView(session_id=session_id.strip(), meta={"fallback": True})
