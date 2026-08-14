"""可扩展上下文 Unit：内置 user / thought_action / observation，未知 kind 只参与 render。"""
from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4


@dataclass
class Unit(ABC):
    kind: str = ""
    unit_id: str = field(default_factory=lambda: str(uuid4()))
    parent_id: str = ""
    step_index: int = -1
    source: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    @abstractmethod
    def render(self) -> str:
        """Return prompt text for this unit; empty string is skipped by Timeline."""


@dataclass
class UserUnit(Unit):
    text: str = ""

    def __post_init__(self) -> None:
        if not self.kind:
            self.kind = "user"
        if not self.source:
            self.source = "user"

    def render(self) -> str:
        text = self.text.strip()
        return f"[用户输入]\n{text}" if text else ""


@dataclass
class ThoughtActionUnit(Unit):
    thought: str = ""
    action: str = ""
    action_input: dict[str, Any] = field(default_factory=dict)
    calls: list[dict[str, Any]] | None = None
    output: str = ""

    def __post_init__(self) -> None:
        if not self.kind:
            self.kind = "thought_action"
        if not self.source:
            self.source = "tao"

    def render(self) -> str:
        parts = [
            f"<T>{self.thought}</T>" if self.thought else "<T></T>",
        ]
        if self.calls:
            parts.append(f"<A>{json.dumps(self.calls, ensure_ascii=False)}</A>")
        else:
            parts.append(
                f"<A>{json.dumps([{'action': self.action, 'args': dict(self.action_input)}], ensure_ascii=False)}</A>"
            )
        if self.output.strip():
            parts.append(f"<O>{self.output}</O>")
        return "\n".join(parts)


@dataclass
class ObservationUnit(Unit):
    observation: str = ""
    tool: str = ""

    def __post_init__(self) -> None:
        if not self.kind:
            self.kind = "observation"
        if not self.source:
            self.source = "tool"

    def render(self) -> str:
        obs = self.observation.strip()
        if not obs:
            return ""
        if self.tool.strip():
            return f"[系统工具反馈] ({self.tool}): {obs}"
        return f"[系统工具反馈]: {obs}"
