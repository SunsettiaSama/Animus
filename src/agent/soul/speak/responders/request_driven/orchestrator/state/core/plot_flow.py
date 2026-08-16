from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Literal

PlotBeatKind = Literal["open", "interact", "push", "hold"]

_MAX_BEATS = 12


def _new_beat_id() -> str:
    return f"beat-{uuid.uuid4().hex[:10]}"


@dataclass
class PlotBeat:
    """剧情流中的一拍：角色↔用户交互轨迹上的一小步。"""

    text: str
    beat_id: str = ""
    kind: PlotBeatKind = "interact"
    at_poll: int = 0
    at_turn: int = 0

    def __post_init__(self) -> None:
        if not self.beat_id.strip():
            self.beat_id = _new_beat_id()

    def snapshot(self) -> dict[str, Any]:
        return {
            "beat_id": self.beat_id,
            "text": self.text,
            "kind": self.kind,
            "at_poll": int(self.at_poll),
            "at_turn": int(self.at_turn),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> PlotBeat | None:
        if not isinstance(data, dict):
            return None
        text = str(data.get("text") or "").strip()
        if not text:
            return None
        kind = str(data.get("kind") or "interact").strip().lower()
        if kind not in ("open", "interact", "push", "hold"):
            kind = "interact"
        return cls(
            beat_id=str(data.get("beat_id") or "").strip(),
            text=text,
            kind=kind,  # type: ignore[arg-type]
            at_poll=int(data.get("at_poll") or 0),
            at_turn=int(data.get("at_turn") or 0),
        )


@dataclass
class PlotFlow:
    """内部场记（编剧主维护，调度注入用，不推用户通读）。

    - chronicle：连贯场面纪要
    - interaction_process：用户交互如何发生、对角色后续的影响（不写角色台词）
    - focus_now / next_push：此刻动作与下一步抓手
    - beats：近期拍点（截断保留）
    - 记忆/分享调度：由编剧写入本表；导演不得挑选或压入
    用户可见开场旁白不在此表，见 director_cache.narrative_opening。
    """

    chronicle: str = ""
    interaction_process: str = ""
    focus_now: str = ""
    next_push: str = ""
    beats: list[PlotBeat] = field(default_factory=list)
    # 编剧写入的记忆/分享调度（角色本轮一次性卡片）
    inject_memory: bool = False
    memory_unit_ids: list[str] = field(default_factory=list)
    inject_share: bool = False
    share_indices: list[int] = field(default_factory=list)
    pass_info: bool = False
    material_reason: str = ""
    version: int = 1
    poll_seq: int = 0
    turn_index: int = 0
    revised_at: float = 0.0

    @property
    def ready(self) -> bool:
        return bool(
            self.chronicle.strip()
            or self.interaction_process.strip()
            or self.focus_now.strip()
            or self.next_push.strip()
            or self.beats
        )

    def snapshot(self) -> dict[str, Any]:
        return {
            "chronicle": self.chronicle,
            "interaction_process": self.interaction_process,
            "focus_now": self.focus_now,
            "next_push": self.next_push,
            "beats": [b.snapshot() for b in self.beats],
            "inject_memory": bool(self.inject_memory),
            "memory_unit_ids": list(self.memory_unit_ids),
            "inject_share": bool(self.inject_share),
            "share_indices": list(self.share_indices),
            "pass_info": bool(self.pass_info),
            "material_reason": self.material_reason,
            "version": int(self.version),
            "poll_seq": int(self.poll_seq),
            "turn_index": int(self.turn_index),
            "revised_at": float(self.revised_at),
            "ready": self.ready,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> PlotFlow:
        if not isinstance(data, dict):
            return cls()
        beats: list[PlotBeat] = []
        for item in data.get("beats") or []:
            beat = PlotBeat.from_dict(item if isinstance(item, dict) else None)
            if beat is not None:
                beats.append(beat)
        mem_ids = data.get("memory_unit_ids") or []
        share_idx = data.get("share_indices") or []
        if not isinstance(mem_ids, list):
            mem_ids = []
        if not isinstance(share_idx, list):
            share_idx = []
        return cls(
            chronicle=str(data.get("chronicle") or "").strip(),
            interaction_process=str(data.get("interaction_process") or "").strip(),
            focus_now=str(data.get("focus_now") or "").strip(),
            next_push=str(data.get("next_push") or "").strip(),
            beats=beats[-_MAX_BEATS:],
            inject_memory=bool(data.get("inject_memory")),
            memory_unit_ids=[str(x) for x in mem_ids if str(x).strip()],
            inject_share=bool(data.get("inject_share")),
            share_indices=[
                int(x) for x in share_idx if str(x).lstrip("-").isdigit()
            ],
            pass_info=bool(data.get("pass_info")),
            material_reason=str(data.get("material_reason") or "").strip(),
            version=max(1, int(data.get("version") or 1)),
            poll_seq=int(data.get("poll_seq") or 0),
            turn_index=int(data.get("turn_index") or 0),
            revised_at=float(data.get("revised_at") or 0.0),
        )

    def render_for_inject(self, *, max_beats: int = 4) -> str:
        """面向角色 agent：冷静客观的情景 unit（此刻在做什么）。"""
        if not self.ready:
            return ""
        lines = ["[情景 unit]"]
        if self.focus_now.strip():
            lines.append(f"此刻在做：{self.focus_now.strip()}")
        if self.interaction_process.strip():
            process = self.interaction_process.strip()
            if len(process) > 420:
                process = process[-420:]
            lines.append(f"交互：{process}")
        if self.chronicle.strip():
            chronicle = self.chronicle.strip()
            if len(chronicle) > 360:
                chronicle = chronicle[-360:]
            lines.append(f"近况：{chronicle}")
        recent = self.beats[-max(1, int(max_beats)) :]
        if recent:
            lines.append("近拍：")
            for beat in recent:
                text = beat.text.strip()
                if text:
                    lines.append(f"- {text}")
        return "\n".join(lines)

    def render_for_screenwriter(self) -> str:
        lines = [
            "[剧情流·当前唯一表]",
            f"version={self.version} poll_seq={self.poll_seq} turn={self.turn_index}",
        ]
        body = self.render_for_inject(max_beats=6)
        if body:
            lines.append(body)
        else:
            lines.append("场记正文暂无——请从开场场面写起。")
        if self.inject_memory or self.inject_share:
            lines.append(
                "本表材料调度："
                f"memory={self.inject_memory} ids={self.memory_unit_ids[:4]} "
                f"share={self.inject_share} indices={self.share_indices[:4]}"
            )
        return "\n".join(lines)

    def set_material_schedule(
        self,
        *,
        inject_memory: bool = False,
        memory_unit_ids: list[str] | None = None,
        inject_share: bool = False,
        share_indices: list[int] | None = None,
        pass_info: bool = False,
        reason: str = "",
    ) -> None:
        """编剧写入记忆/分享调度；消费后由 SpeakService 清零。"""
        self.inject_memory = bool(inject_memory)
        self.memory_unit_ids = [
            str(x).strip() for x in (memory_unit_ids or []) if str(x).strip()
        ]
        self.inject_share = bool(inject_share)
        self.share_indices = [int(x) for x in (share_indices or []) if str(x).lstrip("-").isdigit()]
        self.pass_info = bool(pass_info)
        self.material_reason = str(reason or "").strip()

    def clear_material_schedule(self) -> None:
        self.set_material_schedule(reason="consumed")

    def append_beat(
        self,
        text: str,
        *,
        kind: PlotBeatKind = "interact",
        poll_seq: int = 0,
        turn_index: int = 0,
    ) -> PlotBeat | None:
        body = text.strip()
        if not body:
            return None
        beat = PlotBeat(
            text=body,
            kind=kind,
            at_poll=int(poll_seq),
            at_turn=int(turn_index),
        )
        self.beats.append(beat)
        if len(self.beats) > _MAX_BEATS:
            self.beats = self.beats[-_MAX_BEATS:]
        return beat

    def advance_from_payload(
        self,
        payload: dict[str, Any],
        *,
        poll_seq: int,
        turn_index: int,
        now: float | None = None,
    ) -> PlotFlow:
        """用编剧本拍输出推进本表（整表改写字段 + 追加一拍）。"""
        current = time.time() if now is None else float(now)
        nxt = PlotFlow.from_dict({**self.snapshot(), **payload})
        # 字段以本拍为准；空则保留旧值
        nxt.chronicle = str(payload.get("chronicle") or self.chronicle).strip() or self.chronicle
        nxt.interaction_process = (
            str(payload.get("interaction_process") or self.interaction_process).strip()
            or self.interaction_process
        )
        nxt.focus_now = str(payload.get("focus_now") or self.focus_now).strip() or self.focus_now
        nxt.next_push = str(payload.get("next_push") or self.next_push).strip() or self.next_push
        nxt.beats = list(self.beats)
        beat_text = str(payload.get("beat") or "").strip()
        beat_kind = str(payload.get("beat_kind") or "interact").strip().lower()
        if beat_kind not in ("open", "interact", "push", "hold"):
            beat_kind = "interact"
        if beat_text:
            nxt.append_beat(
                beat_text,
                kind=beat_kind,  # type: ignore[arg-type]
                poll_seq=poll_seq,
                turn_index=turn_index,
            )
        nxt.version = int(self.version) + 1
        nxt.poll_seq = int(poll_seq)
        nxt.turn_index = int(turn_index)
        nxt.revised_at = current
        # 材料调度：本拍 payload 有则覆盖，否则沿用表上旧值
        if any(
            key in payload
            for key in (
                "inject_memory",
                "memory_unit_ids",
                "inject_share",
                "share_indices",
                "pass_info",
                "material_reason",
            )
        ):
            nxt.set_material_schedule(
                inject_memory=bool(payload.get("inject_memory", self.inject_memory)),
                memory_unit_ids=list(
                    payload.get("memory_unit_ids")
                    if isinstance(payload.get("memory_unit_ids"), list)
                    else self.memory_unit_ids
                ),
                inject_share=bool(payload.get("inject_share", self.inject_share)),
                share_indices=list(
                    payload.get("share_indices")
                    if isinstance(payload.get("share_indices"), list)
                    else self.share_indices
                ),
                pass_info=bool(payload.get("pass_info", self.pass_info)),
                reason=str(
                    payload.get("material_reason") or self.material_reason or ""
                ).strip(),
            )
        else:
            nxt.set_material_schedule(
                inject_memory=self.inject_memory,
                memory_unit_ids=list(self.memory_unit_ids),
                inject_share=self.inject_share,
                share_indices=list(self.share_indices),
                pass_info=self.pass_info,
                reason=self.material_reason,
            )
        return nxt
