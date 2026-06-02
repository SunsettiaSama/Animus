from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

DirectorAction = Literal["push_now", "enqueue_brew", "hold"]
DirectorTrigger = Literal["typing_start", "typing_idle", "rule_share", "rule_silence"]


@dataclass
class DirectorInput:
    session_id: str
    trigger: DirectorTrigger
    typing_active: bool = False
    draft_user_text: str = ""
    phase: str = "idle"
    context_distill: str = ""
    working_memory: str = ""
    share_wants: bool = False
    share_summary: str = ""
    share_queue_depth: int = 0
    silence_armed: bool = False

    def prompt_block(self) -> str:
        parts = [
            f"trigger={self.trigger}",
            f"typing_active={self.typing_active}",
            f"phase={self.phase}",
        ]
        if self.draft_user_text.strip():
            parts.append(f"draft_user_text={self.draft_user_text.strip()[:400]}")
        if self.context_distill.strip():
            parts.append(f"context_distill={self.context_distill.strip()[:500]}")
        if self.working_memory.strip():
            wm = self.working_memory.strip()
            lines = [ln.strip() for ln in wm.splitlines() if ln.strip()][-6:]
            parts.append("working_memory=" + " | ".join(lines))
        parts.append(f"share_wants={self.share_wants} share_queue_depth={self.share_queue_depth}")
        if self.share_summary.strip():
            parts.append(f"share_summary={self.share_summary.strip()[:200]}")
        parts.append(f"silence_armed={self.silence_armed}")
        return "\n".join(parts)


@dataclass
class DirectorSignals:
    share_wants: bool = False
    share_summary: str = ""
    share_queue_depth: int = 0
    silence_armed: bool = False

    def snapshot(self) -> dict[str, object]:
        return {
            "share_wants": self.share_wants,
            "share_summary": self.share_summary,
            "share_queue_depth": self.share_queue_depth,
            "silence_armed": self.silence_armed,
        }
