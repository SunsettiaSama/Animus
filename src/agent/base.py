from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from agent.flow.document import TaskExecutionContext


@dataclass
class AgentResult:
    agent_id: str
    role: str
    status: str                                 # done | failed | aborted
    output: Any                                 # PlanDocument | ReplanDecision | str
    execution_ctx: TaskExecutionContext | None = field(default=None)


class AgentBase(ABC):
    @property
    @abstractmethod
    def role(self) -> str:
        """Role identifier: planner | replanner | executor | ..."""

    @abstractmethod
    async def run(self, instruction: str, **ctx: Any) -> AgentResult: ...
