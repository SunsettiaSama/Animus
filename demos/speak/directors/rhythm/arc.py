from __future__ import annotations

from typing import Any, Protocol

from ...contracts import TextGenerator
from ...stage import StageState
from ...stage.desire import ArcSource, DesireArc
from ..base import extract_json_object, generate_text
from .prompts import ARC_INIT_SYSTEM, stage_brief_for_arc_init


class DesireArcSupplier(Protocol):
    """
    对话弧供应口。

    默认走软指令（LLM）；soul.presence / soul.life / external 可替换注入。
    """

    source: ArcSource

    def build_arc(
        self,
        stage: StageState,
        *,
        reason: str = "",
        previous: DesireArc | None = None,
    ) -> DesireArc: ...


def parse_desire_arc(payload: dict[str, Any], *, source: ArcSource) -> DesireArc:
    text = str(
        payload.get("arc")
        or payload.get("text")
        or payload.get("snapshot")
        or ""
    ).strip()
    if not text:
        raise ValueError("desire arc: empty natural-language snapshot")
    return DesireArc(text=text, source=source)


class SoftDesireArcSupplier:
    """软指令驱动：会话材料 -> 模型 -> 自然语言对话弧。"""

    source: ArcSource = "rhythm.init"

    def __init__(self, llm: TextGenerator) -> None:
        self._llm = llm

    def build_arc(
        self,
        stage: StageState,
        *,
        reason: str = "",
        previous: DesireArc | None = None,
    ) -> DesireArc:
        del previous
        raw = generate_text(
            self._llm,
            system=ARC_INIT_SYSTEM,
            user=stage_brief_for_arc_init(stage, reason=reason, previous=None),
        )
        payload = extract_json_object(raw, director="rhythm.init")
        return parse_desire_arc(payload, source=self.source)


class ExternalDesireArcSupplier:
    """外界直接注入对话弧文本（不经 LLM）。"""

    source: ArcSource = "external"

    def __init__(self, text: str) -> None:
        body = text.strip()
        if not body:
            raise ValueError("ExternalDesireArcSupplier: empty arc text")
        self._text = body

    def build_arc(
        self,
        stage: StageState,
        *,
        reason: str = "",
        previous: DesireArc | None = None,
    ) -> DesireArc:
        del stage, reason, previous
        return DesireArc(text=self._text, source=self.source)


class PresenceDesireArcSupplier:
    """预留给 soul.presence（软指令/域服务注入）。"""

    source: ArcSource = "soul.presence"

    def __init__(self, llm: TextGenerator | None = None) -> None:
        self._llm = llm

    def build_arc(
        self,
        stage: StageState,
        *,
        reason: str = "",
        previous: DesireArc | None = None,
    ) -> DesireArc:
        if self._llm is None:
            raise RuntimeError(
                "PresenceDesireArcSupplier: 留给 soul.presence 接线（需注入 llm 或域实现）"
            )
        del previous
        raw = generate_text(
            self._llm,
            system=ARC_INIT_SYSTEM + "\n材料侧重 presence 当下态与冲动。",
            user=stage_brief_for_arc_init(stage, reason=reason, previous=None),
        )
        payload = extract_json_object(raw, director="soul.presence.arc")
        return parse_desire_arc(payload, source=self.source)


class LifeDesireArcSupplier:
    """预留给 soul.life。"""

    source: ArcSource = "soul.life"

    def __init__(self, llm: TextGenerator | None = None) -> None:
        self._llm = llm

    def build_arc(
        self,
        stage: StageState,
        *,
        reason: str = "",
        previous: DesireArc | None = None,
    ) -> DesireArc:
        if self._llm is None:
            raise RuntimeError(
                "LifeDesireArcSupplier: 留给 soul.life 接线（需注入 llm 或域实现）"
            )
        del previous
        raw = generate_text(
            self._llm,
            system=ARC_INIT_SYSTEM + "\n材料侧重 life 体验与叙事余温。",
            user=stage_brief_for_arc_init(stage, reason=reason, previous=None),
        )
        payload = extract_json_object(raw, director="soul.life.arc")
        return parse_desire_arc(payload, source=self.source)
