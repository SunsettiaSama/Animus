"""有序上下文时间线：严格插入顺序，无 HIGH 抢插。"""
from __future__ import annotations

from typing import Any

from infra.agent.unit import ObservationUnit, ThoughtActionUnit, Unit, UserUnit


class Timeline:
    """Session-scoped unit list. Loop snapshots before each LLM call."""

    def __init__(self) -> None:
        self._units: list[Unit] = []

    @property
    def units(self) -> tuple[Unit, ...]:
        return tuple(self._units)

    def clear(self) -> None:
        self._units.clear()

    def inject(self, unit: Unit) -> Unit:
        self._units.append(unit)
        return unit

    def add_user(
        self,
        text: str,
        *,
        source: str = "user",
        metadata: dict[str, Any] | None = None,
    ) -> UserUnit:
        unit = UserUnit(
            text=str(text or "").strip(),
            source=source,
            metadata=dict(metadata or {}),
        )
        return self.inject(unit)  # type: ignore[return-value]

    def add_thought_action(
        self,
        *,
        thought: str,
        action: str = "",
        action_input: dict[str, Any] | None = None,
        calls: list[dict[str, Any]] | None = None,
        output: str = "",
        step_index: int = -1,
        source: str = "tao",
        metadata: dict[str, Any] | None = None,
    ) -> ThoughtActionUnit:
        unit = ThoughtActionUnit(
            thought=thought,
            action=action,
            action_input=dict(action_input or {}),
            calls=list(calls) if calls else None,
            output=output,
            step_index=step_index,
            source=source,
            metadata=dict(metadata or {}),
        )
        return self.inject(unit)  # type: ignore[return-value]

    def add_observation(
        self,
        observation: str,
        *,
        parent_id: str = "",
        tool: str = "",
        step_index: int = -1,
        source: str = "tool",
        metadata: dict[str, Any] | None = None,
    ) -> ObservationUnit:
        unit = ObservationUnit(
            observation=observation,
            tool=tool,
            parent_id=parent_id,
            step_index=step_index,
            source=source,
            metadata=dict(metadata or {}),
        )
        return self.inject(unit)  # type: ignore[return-value]

    def render(self) -> str:
        parts = [u.render() for u in self._units]
        return "\n".join(p for p in parts if p)

    def snapshot(self) -> Timeline:
        """Shallow copy of current unit list for a single LLM prompt build."""
        snapped = Timeline()
        snapped._units = list(self._units)
        return snapped
