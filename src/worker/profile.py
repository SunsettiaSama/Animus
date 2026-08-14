from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any


@dataclass
class SubAgentProfile:
    max_steps: int = 10
    memory: Any = None
    tool_package: str | None = None
    tools: list[str] | None = None
    system_note: str = ""

    def __post_init__(self) -> None:
        if self.memory is None:
            from worker.cards.registry import _sub_memory

            self.memory = _sub_memory()


def _default_profiles() -> dict[str, SubAgentProfile]:
    from worker.cards import get_card_registry

    reg = get_card_registry()
    # Materialize profile-oriented cards only (richer than thin package cards).
    profile_ids = (
        "minimal",
        "executor",
        "researcher",
        "researcher_with_memory",
        "analyst",
        "coder",
    )
    return {cid: reg.materialize(cid) for cid in profile_ids}


@dataclass
class SubAgentConfig:
    llm_cfg_path: str = "config/llm_core/config.yaml"
    profiles: dict[str, SubAgentProfile] = field(default_factory=_default_profiles)
    max_concurrent: int = 4

    def resolve_profile(self, card_id: str) -> SubAgentProfile:
        from worker.cards import materialize_capability

        if card_id in self.profiles:
            return copy.deepcopy(self.profiles[card_id])
        return materialize_capability(card_id)
