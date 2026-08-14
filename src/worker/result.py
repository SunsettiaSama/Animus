from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class SubAgentResult:
    agent_id: str
    status: str = "running"   # running | done | failed | not_found | timeout
    answer: str = ""
    error: str = ""
