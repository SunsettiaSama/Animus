"""Context units that form a Worker turn timeline."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4


class UnitKind(str, Enum):
    USER = "user"
    THOUGHT_ACTION = "thought_action"
    OBSERVATION = "observation"


class UnitPriority(int, Enum):
    NORMAL = 0
    HIGH = 100


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class ContextUnit:
    kind: UnitKind
    payload: dict[str, Any]
    unit_id: str = field(default_factory=lambda: str(uuid4()))
    created_at: str = field(default_factory=utc_now_iso)
    priority: UnitPriority = UnitPriority.NORMAL
    source: str = "tao"
    step_index: int = -1
    parent_id: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def char_count(self) -> int:
        text = self.render_text()
        return len(text)

    def render_text(self) -> str:
        if self.kind == UnitKind.USER:
            text = str(self.payload.get("text", "")).strip()
            return f"[用户输入]\n{text}" if text else ""
        if self.kind == UnitKind.THOUGHT_ACTION:
            import json

            thought = str(self.payload.get("thought", "") or "")
            calls = self.payload.get("calls")
            action = str(self.payload.get("action", "") or "")
            action_input = self.payload.get("action_input") or {}
            output = str(self.payload.get("output", "") or "")
            parts = [
                f"<T>{thought}</T>" if thought else "<T></T>",
            ]
            if calls:
                parts.append(f"<A>{json.dumps(calls, ensure_ascii=False)}</A>")
            else:
                parts.append(
                    f"<A>{json.dumps([{'action': action, 'args': action_input}], ensure_ascii=False)}</A>"
                )
            if output:
                parts.append(f"<O>{output}</O>")
            return "\n".join(parts)
        if self.kind == UnitKind.OBSERVATION:
            obs = str(self.payload.get("observation", "") or "")
            tool = str(self.payload.get("tool", "") or "")
            if tool:
                return f"[系统工具反馈] ({tool}): {obs}"
            return f"[系统工具反馈]: {obs}"
        return ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "unit_id": self.unit_id,
            "kind": self.kind.value,
            "created_at": self.created_at,
            "priority": int(self.priority),
            "source": self.source,
            "step_index": self.step_index,
            "parent_id": self.parent_id,
            "payload": dict(self.payload),
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ContextUnit:
        return cls(
            unit_id=str(data.get("unit_id") or uuid4()),
            kind=UnitKind(str(data["kind"])),
            created_at=str(data.get("created_at") or utc_now_iso()),
            priority=UnitPriority(int(data.get("priority", 0))),
            source=str(data.get("source") or "tao"),
            step_index=int(data.get("step_index", -1)),
            parent_id=str(data.get("parent_id") or ""),
            payload=dict(data.get("payload") or {}),
            metadata=dict(data.get("metadata") or {}),
        )
