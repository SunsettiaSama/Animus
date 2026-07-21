from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal, Sequence

if TYPE_CHECKING:
    from .models import HistoryBeat

TurnTrigger = Literal["user", "poll"]


@dataclass(frozen=True)
class DirectorBeat:
    """一拍开口中枢决策（轻量场记，防复读）。"""

    trigger: TurnTrigger
    gate: str
    cue: str = ""
    tempo: str = ""
    reply_guide: str = ""
    reason: str = ""
    spoke: bool = False

    def one_line(self, *, limit: int = 120) -> str:
        parts = [f"gate={self.gate}"]
        if self.tempo.strip():
            parts.append(f"节奏={self.tempo.strip()}")
        if self.cue.strip():
            parts.append(f"开口={self.cue.strip()}")
        if self.reply_guide.strip():
            parts.append(f"给回复={self.reply_guide.strip()}")
        if self.reason.strip():
            parts.append(f"因={self.reason.strip()}")
        body = "；".join(parts).replace("\n", " ")
        if len(body) > limit:
            body = body[: limit - 1] + "…"
        return f"[{self.trigger}] {body}"

    def snapshot(self) -> dict[str, Any]:
        return {
            "trigger": self.trigger,
            "gate": self.gate,
            "cue": self.cue,
            "tempo": self.tempo,
            "reply_guide": self.reply_guide,
            "reason": self.reason,
            "spoke": self.spoke,
        }


def _is_echo_beat(beat: DirectorBeat) -> bool:
    """listen/hold 且未开口：回灌会诱发自回归复读，场记里跳过。"""
    if beat.spoke:
        return False
    return beat.gate in ("listen", "hold")


def weave_dialogue_and_directors(
    history: Sequence[HistoryBeat],
    directors: Sequence[DirectorBeat],
    *,
    history_limit: int = 6,
    director_limit: int = 2,
) -> list[str]:
    """
    对白与近几拍「有效」导演决策穿插。

    只回灌开口过的 / brew·speak 决策；连续 listen/hold 不进场记，避免自回归陷阱。
    """
    beats = list(history[-history_limit:])
    dirs = [d for d in directors if not _is_echo_beat(d)][-director_limit:]
    if not beats and not dirs:
        return ["（尚无场记）"]

    attach: dict[int, DirectorBeat] = {}
    agent_idxs = [i for i, b in enumerate(beats) if b.speaker == "agent"]
    for beat_dir, idx in zip(reversed(dirs), reversed(agent_idxs)):
        attach[idx] = beat_dir
    attached = set(attach.values())
    leftover = [d for d in dirs if d not in attached]

    lines: list[str] = []
    for i, beat in enumerate(beats):
        lines.append(f"- [对白] {beat.one_line()}")
        if i in attach:
            lines.append(f"- [导演] {attach[i].one_line()}")
    for d in leftover:
        lines.append(f"- [导演] {d.one_line()}")
    return lines
