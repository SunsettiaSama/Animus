from __future__ import annotations

from dataclasses import dataclass

from .state import ShareComposeState, ShareEventView


@dataclass(frozen=True)
class ShareRevealPointer:
    """分享指向：暂支持队列 index 或 topic 文本。"""

    value: str


@dataclass(frozen=True)
class ShareRevealResult:
    ok: bool
    pointer: str
    full_text: str = ""
    event: ShareEventView | None = None
    trigger_source: str = ""
    reason: str = ""


def _resolve_event(
    state: ShareComposeState,
    pointer: ShareRevealPointer,
) -> ShareEventView | None:
    raw = pointer.value.strip()
    if not raw:
        return None
    if raw.isdigit():
        index = int(raw)
        for event in state.events:
            if event.index == index:
                return event
        return None
    for event in state.events:
        if event.topic == raw or event.brief == raw:
            return event
    return None


def render_share_full_text(event: ShareEventView) -> str:
    """单条分享事件的完整摘要（供 reveal 接口交给 agent）。"""
    lines = [
        "【分享详情】",
        f"话题：{event.topic}",
        f"分享意愿：{event.share_desire.value}",
    ]
    if event.source.strip():
        lines.append(f"来源：{event.source.strip()}")
    if event.salience > 0:
        lines.append(f"显著性：{event.salience:.2f}")
    lines.append("")
    lines.append(event.topic.strip())
    return "\n".join(lines)


class ShareRevealGate:
    """分享揭示接口：按指向返回完整摘要；触发方接线预留。"""

    def reveal(
        self,
        *,
        state: ShareComposeState,
        pointer: ShareRevealPointer,
    ) -> ShareRevealResult:
        event = _resolve_event(state, pointer)
        if event is None:
            return ShareRevealResult(
                ok=False,
                pointer=pointer.value,
                reason="share pointer not found",
            )
        return ShareRevealResult(
            ok=True,
            pointer=pointer.value,
            full_text=render_share_full_text(event),
            event=event,
        )

    def trigger(
        self,
        *,
        state: ShareComposeState,
        pointer: str,
        source: str = "",
    ) -> ShareRevealResult:
        """预留触发入口：``source`` 预留给 heartbeat / tool / explicit 等未来接线。"""
        result = self.reveal(state=state, pointer=ShareRevealPointer(pointer))
        if not result.ok:
            return result
        return ShareRevealResult(
            ok=True,
            pointer=result.pointer,
            full_text=result.full_text,
            event=result.event,
            trigger_source=source.strip(),
        )
