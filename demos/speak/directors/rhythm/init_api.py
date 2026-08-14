from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Protocol

from ...stage import DesireArc, StageState
from .arc import DesireArcSupplier, ExternalDesireArcSupplier


@dataclass(frozen=True)
class DesireArcInitResult:
    """对话弧 init / 热初始化结果。"""

    arc: DesireArc
    hot: bool
    reason: str
    stage: dict[str, Any]


class DesireArcHotInitPort(Protocol):
    """
    外界热初始化口：模型态 / presence / life 变更时强制重拟定对话弧。

    与冷启动 init 共用同一套 SoftDesireArcSupplier（或外部 supplier）。
    """

    def hot_init_desire_arc(
        self,
        *,
        reason: str = "external",
        supplier: DesireArcSupplier | None = None,
        mutate: Callable[[StageState], None] | None = None,
        arc_text: str | None = None,
    ) -> DesireArcInitResult: ...

    def notify_stage_changed(
        self,
        *,
        reason: str = "external.notify",
        agent_status: str | None = None,
        agent_presence: str | None = None,
        affect_intensity: float | None = None,
        affect_label: str | None = None,
        affect_valence: str | None = None,
        share_title: str | None = None,
        share_detail: str = "",
        share_urgency: float = 0.6,
        reinit_arc: bool = True,
        supplier: DesireArcSupplier | None = None,
        arc_text: str | None = None,
    ) -> DesireArcInitResult | None: ...


def apply_stage_notify_patch(
    stage: StageState,
    *,
    agent_status: str | None = None,
    agent_presence: str | None = None,
    affect_intensity: float | None = None,
    affect_label: str | None = None,
    affect_valence: str | None = None,
    share_title: str | None = None,
    share_detail: str = "",
    share_urgency: float = 0.6,
) -> None:
    """把外界通知落到舞台态（不做弧决策）。"""
    if agent_status is not None:
        stage.set_agent_status(agent_status)
    if agent_presence is not None:
        stage.agent_presence = agent_presence.strip()
    if (
        affect_intensity is not None
        or affect_label is not None
        or affect_valence is not None
    ):
        stage.set_affect(
            intensity=affect_intensity,
            label=affect_label,
            valence=affect_valence,
        )
    if share_title is not None and share_title.strip():
        stage.enqueue_share(
            share_title.strip(),
            detail=share_detail,
            urgency=share_urgency,
        )


def resolve_hot_supplier(
    *,
    supplier: DesireArcSupplier | None,
    arc_text: str | None,
    default: DesireArcSupplier | None,
) -> DesireArcSupplier | None:
    if arc_text is not None and arc_text.strip():
        return ExternalDesireArcSupplier(arc_text.strip())
    return supplier or default


__all__ = [
    "DesireArcInitResult",
    "DesireArcHotInitPort",
    "apply_stage_notify_patch",
    "resolve_hot_supplier",
]
