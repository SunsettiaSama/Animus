from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from ...guidance.memory import (
    format_interactor_preview,
    render_interactor_portrait_for_prompt,
    render_interactor_portrait_inject,
)

from .layer import SpeakPersonaLayer


@dataclass(frozen=True)
class InteractorPortraitPull:
    portrait_text: str = ""
    interactor_id: str = ""
    turn_index: int = 0
    display_name: str = ""
    core_traits: tuple[str, ...] = ()
    portrait_body: str = ""
    agent_relation: str = ""
    recent_impression: str = ""


class InteractorPortraitPullPort(Protocol):
    def pull(
        self,
        session_id: str,
        turn_index: int,
        *,
        wait_ms: int = 100,
    ) -> InteractorPortraitPull: ...


InteractorPortraitRequestFn = Callable[
    [str, int, str, str],
    None,
]


@dataclass
class PersonaInteractorPortraitService:
    """Persona 域对话者画像：请求/拉取/写入 layer（与 memory compose 链路对接）。"""

    _pull: InteractorPortraitPullPort | None = None
    _request: InteractorPortraitRequestFn | None = None
    _wait_ms: int = 100

    def bind_pull_port(self, port: InteractorPortraitPullPort | None) -> None:
        self._pull = port

    def bind_request(
        self,
        request_fn: InteractorPortraitRequestFn | None,
    ) -> None:
        self._request = request_fn

    def request_for_turn(
        self,
        session_id: str,
        turn_index: int,
        *,
        user_text: str = "",
        agent_text: str = "",
    ) -> None:
        if self._request is None:
            return
        self._request(
            session_id.strip(),
            turn_index,
            user_text,
            agent_text,
        )

    def pull_for_compose(
        self,
        session_id: str,
        turn_index: int,
        *,
        wait_ms: int | None = None,
    ) -> InteractorPortraitPull:
        if self._pull is None:
            return InteractorPortraitPull()
        resolved_wait = self._wait_ms if wait_ms is None else wait_ms
        return self._pull.pull(session_id, turn_index, wait_ms=resolved_wait)

    def render_for_prompt(self, pulled: InteractorPortraitPull) -> str:
        narrative = pulled.portrait_text.strip()
        if narrative:
            return narrative
        if pulled.display_name or pulled.core_traits or pulled.portrait_body:
            return render_interactor_portrait_for_prompt(
                name=pulled.display_name,
                core_traits=list(pulled.core_traits),
                portrait_body=pulled.portrait_body,
                agent_relation=pulled.agent_relation,
                recent_impression=pulled.recent_impression,
            )
        return render_interactor_portrait_inject(pulled.portrait_text)

    def apply_to_layer(
        self,
        layer: SpeakPersonaLayer,
        pulled: InteractorPortraitPull,
    ) -> str:
        block = self.render_for_prompt(pulled)
        layer.relational.interactor_portrait = block
        return block

    def apply_to_bundle(self, bundle, pulled: InteractorPortraitPull) -> None:
        from ....prompt_trace import get_prompt_trace

        block = self.apply_to_layer(bundle.persona, pulled)
        preview = format_interactor_preview(block or pulled.portrait_text)
        if preview:
            bundle.guidance.interactor_portrait = preview
        if pulled.interactor_id:
            bundle.meta["resolved_interactor_id"] = pulled.interactor_id
        if pulled.turn_index:
            bundle.meta["interactor_portrait_turn_index"] = pulled.turn_index
        if block.strip():
            bundle.meta["persona_interactor_portrait_chars"] = len(block.strip())
        if get_prompt_trace().is_enabled(bundle.session_id):
            trace_pull = bundle.meta.setdefault("trace_pull", {})
            if isinstance(trace_pull, dict):
                trace_pull["portrait"] = {
                    "portrait_text": pulled.portrait_text,
                    "interactor_id": pulled.interactor_id,
                    "turn_index": pulled.turn_index,
                }


@dataclass
class MemoryComposePortraitPullPort:
    """InboundMemoryComposeBridge → PersonaInteractorPortraitService 拉取适配。"""

    _bridge: object

    def pull(
        self,
        session_id: str,
        turn_index: int,
        *,
        wait_ms: int = 100,
    ) -> InteractorPortraitPull:
        result = self._bridge.pull_interactor_portrait(session_id, turn_index)
        return interactor_pull_from_memory_result(result)


def interactor_pull_from_memory_result(result) -> InteractorPortraitPull:
    snippets = getattr(result, "neighborhood_snippets", ()) or ()
    return InteractorPortraitPull(
        portrait_text=str(getattr(result, "portrait_text", "") or ""),
        interactor_id=str(getattr(result, "interactor_id", "") or ""),
        turn_index=int(getattr(result, "turn_index", 0) or 0),
        display_name=str(getattr(result, "display_name", "") or ""),
        core_traits=tuple(getattr(result, "core_traits", ()) or ()),
        portrait_body=str(getattr(result, "portrait_body", "") or ""),
        agent_relation=str(getattr(result, "agent_relation", "") or ""),
        recent_impression=str(getattr(result, "recent_impression", "") or ""),
    )
