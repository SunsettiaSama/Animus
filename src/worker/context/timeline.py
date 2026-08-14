"""Priority-aware Worker context timeline with character budget."""
from __future__ import annotations

from typing import Any

from worker.context.unit import ContextUnit, UnitKind, UnitPriority, utc_now_iso


DEFAULT_BUDGET_CHARS = 12000
_OBS_SUMMARY_LIMIT = 240


class ContextTimeline:
    """Single manager for USER / THOUGHT_ACTION / OBSERVATION units in one turn."""

    def __init__(self, *, budget_chars: int = DEFAULT_BUDGET_CHARS) -> None:
        if budget_chars < 1000:
            raise ValueError("context timeline budget_chars must be at least 1000")
        self._budget = budget_chars
        self._units: list[ContextUnit] = []

    @property
    def units(self) -> tuple[ContextUnit, ...]:
        return tuple(self._units)

    def append(self, unit: ContextUnit) -> ContextUnit:
        self._units.append(unit)
        self._enforce_budget()
        return unit

    def add_user(
        self,
        text: str,
        *,
        priority: UnitPriority = UnitPriority.NORMAL,
        metadata: dict[str, Any] | None = None,
        source: str = "user",
    ) -> ContextUnit:
        unit = ContextUnit(
            kind=UnitKind.USER,
            payload={"text": str(text or "").strip()},
            priority=priority,
            source=source,
            metadata=dict(metadata or {}),
            created_at=utc_now_iso(),
        )
        return self.append(unit)

    def pin_user(
        self,
        text: str,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> ContextUnit:
        """Highest-priority user interrupt; rendered ahead of the rest."""
        return self.add_user(
            text,
            priority=UnitPriority.HIGH,
            metadata=metadata,
            source="user",
        )

    def add_thought_action(
        self,
        *,
        thought: str,
        action: str,
        action_input: dict[str, Any] | None = None,
        calls: list[dict] | None = None,
        output: str = "",
        step_index: int = -1,
        metadata: dict[str, Any] | None = None,
    ) -> ContextUnit:
        unit = ContextUnit(
            kind=UnitKind.THOUGHT_ACTION,
            payload={
                "thought": thought,
                "action": action,
                "action_input": dict(action_input or {}),
                "calls": list(calls) if calls else None,
                "output": output,
            },
            source="tao",
            step_index=step_index,
            metadata=dict(metadata or {}),
        )
        return self.append(unit)

    def add_observation(
        self,
        observation: str,
        *,
        parent_id: str = "",
        tool: str = "",
        step_index: int = -1,
        source: str = "tool",
        metadata: dict[str, Any] | None = None,
    ) -> ContextUnit:
        unit = ContextUnit(
            kind=UnitKind.OBSERVATION,
            payload={"observation": observation, "tool": tool},
            parent_id=parent_id,
            source=source,
            step_index=step_index,
            metadata=dict(metadata or {}),
        )
        return self.append(unit)

    def render_order(self) -> list[ContextUnit]:
        high = [u for u in self._units if u.priority == UnitPriority.HIGH]
        rest = [u for u in self._units if u.priority != UnitPriority.HIGH]
        high.sort(key=lambda u: u.created_at)
        rest.sort(key=lambda u: u.created_at)
        return high + rest

    def render_text(self) -> str:
        parts = [u.render_text() for u in self.render_order()]
        return "\n".join(p for p in parts if p)

    def total_chars(self) -> int:
        return sum(u.char_count() for u in self._units)

    def to_unit_dicts(self) -> list[dict[str, Any]]:
        return [u.to_dict() for u in self.render_order()]

    def summary_lines(self, *, max_units: int = 24, max_chars: int = 1800) -> list[str]:
        lines: list[str] = []
        used = 0
        for unit in self.render_order()[-max_units:]:
            if unit.kind == UnitKind.USER:
                line = f"user: {str(unit.payload.get('text', ''))[:160]}"
            elif unit.kind == UnitKind.THOUGHT_ACTION:
                line = (
                    f"act: {unit.payload.get('action', '')} "
                    f"thought={str(unit.payload.get('thought', ''))[:80]}"
                )
            else:
                line = (
                    f"obs({unit.payload.get('tool', '')}): "
                    f"{str(unit.payload.get('observation', ''))[:120]}"
                )
            if used + len(line) > max_chars:
                break
            lines.append(line)
            used += len(line)
        return lines

    def project_task_actions(self) -> list[tuple[dict, str]]:
        """Pair each thought_action call with its following observation."""
        by_id = {u.unit_id: u for u in self._units}
        pairs: list[tuple[dict, str]] = []
        for unit in self._units:
            if unit.kind != UnitKind.THOUGHT_ACTION:
                continue
            calls = unit.payload.get("calls") or [
                {
                    "action": unit.payload.get("action"),
                    "args": unit.payload.get("action_input") or {},
                }
            ]
            obs_units = [
                u
                for u in self._units
                if u.kind == UnitKind.OBSERVATION and u.parent_id == unit.unit_id
            ]
            if not obs_units:
                for call in calls:
                    pairs.append((call, ""))
                continue
            if len(obs_units) == 1 and len(calls) > 1:
                obs_text = str(obs_units[0].payload.get("observation", ""))
                for call in calls:
                    pairs.append((call, obs_text))
            else:
                for call, obs in zip(calls, obs_units):
                    pairs.append((call, str(obs.payload.get("observation", ""))))
                for call in calls[len(obs_units) :]:
                    pairs.append((call, ""))
            _ = by_id
        return pairs

    def _enforce_budget(self) -> None:
        while self.total_chars() > self._budget:
            candidates = [
                i
                for i, u in enumerate(self._units)
                if u.kind == UnitKind.OBSERVATION
                and u.priority != UnitPriority.HIGH
                and not u.metadata.get("compressed")
            ]
            if candidates:
                idx = candidates[0]
                unit = self._units[idx]
                obs = str(unit.payload.get("observation", ""))
                if len(obs) > _OBS_SUMMARY_LIMIT:
                    unit.payload["observation"] = (
                        obs[:_OBS_SUMMARY_LIMIT].rstrip() + "…[已压缩]"
                    )
                    unit.metadata["original_chars"] = len(obs)
                unit.metadata["compressed"] = True
                continue
            # All observations already compressed — drop oldest non-HIGH obs.
            drop = [
                i
                for i, u in enumerate(self._units)
                if u.kind == UnitKind.OBSERVATION and u.priority != UnitPriority.HIGH
            ]
            if not drop:
                break
            self._units.pop(drop[0])
