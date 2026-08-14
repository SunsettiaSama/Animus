from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

from ..blocks.core.types import BlockId
from ..frame import PreparedComposeFrame

if TYPE_CHECKING:
    from ..blocks.guidance.control import GuidanceControlState
else:
    GuidanceControlState = Any  # type: ignore[assignment,misc]

SocialArmedKind = Literal["enter_greeting", "silence_break", "initiative"]

KNOWN_DIRECTOR_MODULES: tuple[BlockId, ...] = (
    "persona",
    "scene",
    "guidance",
    "context",
    "memory",
    "social",
    "share",
)


@dataclass(frozen=True)
class ModuleSnapshot:
    block: BlockId
    summary: str
    version: int | None = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ModuleDecision:
    block: BlockId
    refresh: bool
    include: bool
    reason: str
    guidance_trigger: str | None = None


@dataclass(frozen=True)
class MemoryInjectPlan:
    request_emergence: bool = False
    request_keyword: bool = False
    request_portrait: bool = False
    include_recall: bool = True
    include_portrait: bool = True
    pull_at_consume: bool = True


@dataclass(frozen=True)
class ShareComposePlan:
    include_preview: bool = False
    include_in_planner: bool = False
    guidance_trigger: str | None = None
    share_queue_count: int = 0
    share_linked: bool = False
    deferred_use_session_queue: bool = False


@dataclass
class DirectorPlan:
    session_id: str
    target_turn_index: int
    generation: int = 0
    modules: tuple[ModuleDecision, ...] = ()
    memory: MemoryInjectPlan = field(default_factory=MemoryInjectPlan)
    share: ShareComposePlan = field(default_factory=ShareComposePlan)
    social_armed: SocialArmedKind | None = None
    prepared_frame: PreparedComposeFrame | None = None
    control_snapshot: GuidanceControlState | None = None
    source_user_text: str = ""
    notes: list[str] = field(default_factory=list)

    def decision_for(self, block: BlockId) -> ModuleDecision | None:
        for item in self.modules:
            if item.block == block:
                return item
        return None

    def refresh_flags(self) -> dict[str, bool]:
        out: dict[str, bool] = {}
        for item in self.modules:
            out[item.block] = item.refresh
        return out

    def snapshot(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "target_turn_index": self.target_turn_index,
            "generation": self.generation,
            "modules": [
                {
                    "block": d.block,
                    "refresh": d.refresh,
                    "include": d.include,
                    "reason": d.reason,
                    "guidance_trigger": d.guidance_trigger,
                }
                for d in self.modules
            ],
            "memory": {
                "request_emergence": self.memory.request_emergence,
                "request_keyword": self.memory.request_keyword,
                "request_portrait": self.memory.request_portrait,
                "include_recall": self.memory.include_recall,
                "include_portrait": self.memory.include_portrait,
            },
            "share": {
                "include_preview": self.share.include_preview,
                "include_in_planner": self.share.include_in_planner,
                "guidance_trigger": self.share.guidance_trigger,
                "share_queue_count": self.share.share_queue_count,
                "share_linked": self.share.share_linked,
            },
            "social_armed": self.social_armed,
            "has_prepared_frame": self.prepared_frame is not None,
            "has_control_snapshot": self.control_snapshot is not None,
            "source_user_text": self.source_user_text,
            "notes": list(self.notes),
            "refresh": self.refresh_flags(),
        }
