from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Literal

from .interaction_plan import MIN_LIVE_UNITS_BEFORE_WAKE

ExecutableStatus = Literal["pending", "reserved", "consumed", "fired", "cancelled"]

_DETAIL_LIMIT = 240
_INNER_LIMIT = 240
_TRANSITION_LIMIT = 240
_STANCE_LIMIT = 160


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


def _clip(text: Any, limit: int) -> str:
    return str(text or "").strip()[:limit]


def plot_progress_fingerprint(plot_arc=None, plot_flow=None) -> str:
    """剧情推进指纹：只钉 unit_id + status，不含 poll 计数。"""
    active = None
    if plot_arc is not None and getattr(plot_arc, "ready", False):
        active = plot_arc.active_unit() if hasattr(plot_arc, "active_unit") else None
    return "|".join(
        [
            str(getattr(active, "unit_id", "") or "").strip(),
            str(getattr(active, "status", "") or "").strip(),
        ]
    )


@dataclass(init=False)
class ExecutableUnit:
    """节奏卡：与剧情 InteractionUnit 1:1，用「你」口吻扩充细节。

    开口时机不在本卡；由 CharacterSpeakAgenda 管理。
    """

    unit_id: str = ""
    plot_unit_id: str = ""
    script_text: str = ""
    reason: str = ""
    status: ExecutableStatus = "pending"
    detail: str = ""
    inner: str = ""
    transition: str = ""
    stance: str = ""
    window_start: float | None = None
    window_end: float | None = None
    open_at: float = 0.0

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        if "plot_unit_ids" in kwargs and "plot_unit_ids_arg" not in kwargs:
            kwargs["plot_unit_ids_arg"] = kwargs.pop("plot_unit_ids")
        if "focus" in kwargs and "focus_arg" not in kwargs:
            kwargs["focus_arg"] = kwargs.pop("focus")
        if "intent" in kwargs and "intent_arg" not in kwargs:
            kwargs["intent_arg"] = kwargs.pop("intent")
        if "direction" in kwargs and "direction_arg" not in kwargs:
            kwargs["direction_arg"] = kwargs.pop("direction")
        if "exit" in kwargs and "exit_arg" not in kwargs:
            kwargs["exit_arg"] = kwargs.pop("exit")
        fields = (
            "unit_id",
            "plot_unit_id",
            "script_text",
            "reason",
            "status",
            "detail",
            "inner",
            "transition",
            "stance",
            "window_start",
            "window_end",
            "open_at",
        )
        defaults: dict[str, Any] = {
            "unit_id": "",
            "plot_unit_id": "",
            "script_text": "",
            "reason": "",
            "status": "pending",
            "detail": "",
            "inner": "",
            "transition": "",
            "stance": "",
            "window_start": None,
            "window_end": None,
            "open_at": 0.0,
        }
        for i, name in enumerate(fields):
            if i < len(args):
                setattr(self, name, args[i])
            elif name in kwargs:
                setattr(self, name, kwargs.pop(name))
            else:
                setattr(self, name, defaults[name])
        self.__post_init__(
            plot_unit_ids_arg=kwargs.pop("plot_unit_ids_arg", None),
            focus_arg=kwargs.pop("focus_arg", ""),
            intent_arg=kwargs.pop("intent_arg", ""),
            direction_arg=kwargs.pop("direction_arg", ""),
            exit_arg=kwargs.pop("exit_arg", ""),
            info_need=kwargs.pop("info_need", ""),
            info_status=kwargs.pop("info_status", ""),
            info_due_at=kwargs.pop("info_due_at", None),
            result_brief=kwargs.pop("result_brief", ""),
        )
        if kwargs:
            raise TypeError(f"unexpected kwargs: {sorted(kwargs)}")

    def __post_init__(
        self,
        plot_unit_ids_arg: Any = None,
        focus_arg: str = "",
        intent_arg: str = "",
        direction_arg: str = "",
        exit_arg: str = "",
        info_need: str = "",
        info_status: str = "",
        info_due_at: Any = None,
        result_brief: str = "",
    ) -> None:
        del info_need, info_status, info_due_at, result_brief
        if not str(self.unit_id or "").strip():
            self.unit_id = _new_id("exec")
        if not str(self.plot_unit_id or "").strip() and plot_unit_ids_arg is not None:
            if isinstance(plot_unit_ids_arg, str) and plot_unit_ids_arg.strip():
                self.plot_unit_id = plot_unit_ids_arg.strip()
            elif isinstance(plot_unit_ids_arg, (list, tuple)):
                for x in plot_unit_ids_arg:
                    if str(x).strip():
                        self.plot_unit_id = str(x).strip()
                        break
        self.plot_unit_id = str(self.plot_unit_id or "").strip()
        self.script_text = str(self.script_text or "").strip()
        self.reason = str(self.reason or "").strip()
        status = str(self.status or "pending").strip().lower()
        if status not in ("pending", "reserved", "consumed", "fired", "cancelled"):
            status = "pending"
        self.status = status  # type: ignore[assignment]
        if not self.detail and focus_arg:
            self.detail = _clip(focus_arg, _DETAIL_LIMIT)
        if not self.inner and intent_arg:
            self.inner = _clip(intent_arg, _INNER_LIMIT)
        if not self.transition and direction_arg:
            self.transition = _clip(direction_arg, _TRANSITION_LIMIT)
        if not self.stance and exit_arg:
            self.stance = _clip(exit_arg, _STANCE_LIMIT)
        self.detail = _clip(self.detail, _DETAIL_LIMIT)
        self.inner = _clip(self.inner, _INNER_LIMIT)
        self.transition = _clip(self.transition, _TRANSITION_LIMIT)
        self.stance = _clip(self.stance, _STANCE_LIMIT)
        if self.window_start is not None:
            self.window_start = float(self.window_start)
        if self.window_end is not None:
            self.window_end = float(self.window_end)
        if float(self.open_at or 0) <= 0 and self.window_start is not None:
            self.open_at = float(self.window_start)
        elif float(self.open_at or 0) <= 0:
            self.open_at = time.time()

    @property
    def plot_unit_ids(self) -> tuple[str, ...]:
        return (self.plot_unit_id,) if self.plot_unit_id else ()

    @plot_unit_ids.setter
    def plot_unit_ids(self, value: tuple[str, ...] | list[str]) -> None:
        ids = [str(x).strip() for x in (value or ()) if str(x).strip()]
        self.plot_unit_id = ids[0] if ids else ""

    def action_duration_sec(self) -> float:
        """这一步动作在现实里做完要多久。"""
        if self.window_start is not None and self.window_end is not None:
            return max(0.0, float(self.window_end) - float(self.window_start))
        return 0.0

    def has_enrichment(self) -> bool:
        return bool(self.detail or self.inner or self.transition or self.stance)

    def apply_enrichment(self, data: dict[str, Any] | None) -> None:
        if not isinstance(data, dict):
            return
        detail = _clip(data.get("detail"), _DETAIL_LIMIT)
        inner = _clip(data.get("inner"), _INNER_LIMIT)
        transition = _clip(data.get("transition"), _TRANSITION_LIMIT)
        stance = _clip(data.get("stance"), _STANCE_LIMIT)
        if detail:
            self.detail = detail
        if inner:
            self.inner = inner
        if transition:
            self.transition = transition
        if stance:
            self.stance = stance
        if data.get("window_start") is not None:
            self.window_start = float(data.get("window_start"))
            self.open_at = float(self.window_start)
        if data.get("window_end") is not None:
            self.window_end = float(data.get("window_end"))

    def snapshot(self) -> dict[str, Any]:
        return {
            "unit_id": self.unit_id,
            "plot_unit_id": self.plot_unit_id,
            "plot_unit_ids": list(self.plot_unit_ids),
            "script_text": self.script_text,
            "reason": self.reason,
            "status": self.status,
            "detail": self.detail,
            "inner": self.inner,
            "transition": self.transition,
            "stance": self.stance,
            "window_start": self.window_start,
            "window_end": self.window_end,
            "open_at": float(self.open_at),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> ExecutableUnit | None:
        if not isinstance(data, dict):
            return None
        plot_id = str(data.get("plot_unit_id") or "").strip()
        if not plot_id:
            raw_ids = data.get("plot_unit_ids") or data.get("plot_unit_id") or ()
            if isinstance(raw_ids, str) and raw_ids.strip():
                plot_id = raw_ids.strip()
            elif isinstance(raw_ids, (list, tuple)):
                for x in raw_ids:
                    if str(x).strip():
                        plot_id = str(x).strip()
                        break
        # 旧四指令字段若仍存在，折入扩充字段（一次性读入，不再写出）
        detail = str(data.get("detail") or data.get("focus") or "").strip()
        inner = str(data.get("inner") or data.get("intent") or "").strip()
        transition = str(data.get("transition") or data.get("direction") or "").strip()
        stance = str(data.get("stance") or data.get("exit") or "").strip()
        ws = data.get("window_start")
        we = data.get("window_end")
        open_at = data.get("open_at")
        return cls(
            unit_id=str(data.get("unit_id") or data.get("entry_id") or "").strip(),
            plot_unit_id=plot_id,
            script_text=str(data.get("script_text") or "").strip(),
            reason=str(data.get("reason") or "").strip(),
            status=str(data.get("status") or "pending"),  # type: ignore[arg-type]
            detail=detail,
            inner=inner,
            transition=transition,
            stance=stance,
            window_start=float(ws) if ws is not None else None,
            window_end=float(we) if we is not None else None,
            open_at=float(open_at) if open_at is not None else 0.0,
        )

    def render_for_director(self) -> str:
        lines = [
            f"- [{self.status}] id={self.unit_id} plot={self.plot_unit_id or '—'} "
            f"reason={self.reason or '—'}"
        ]
        held = self.action_duration_sec()
        if self.window_start is not None or self.window_end is not None:
            hold = f" 动作约{held:.0f}s" if held > 0 else ""
            lines.append(
                f"  window={self.window_start or '—'} → {self.window_end or '—'}{hold}"
            )
        elif held > 0:
            lines.append(f"  动作约{held:.0f}s")
        if self.script_text:
            lines.append(f"  台本={self.script_text[:180]}")
        enrich = self.render_enrichment()
        if enrich:
            lines.append(enrich)
        return "\n".join(lines)

    def render_enrichment(self) -> str:
        """「你」口吻扩充文本，交给角色。"""
        lines: list[str] = []
        if self.detail:
            lines.append(f"你手头：{self.detail}")
        if self.inner:
            lines.append(f"你在想：{self.inner}")
        if self.transition:
            lines.append(f"你怎么过渡：{self.transition}")
        if self.stance:
            lines.append(f"你的姿态：{self.stance}")
        return "\n".join(lines)

    def render_script_for_character(self) -> str:
        return self.script_text.strip()

    # 旧调用名：有扩充即视为有指令
    def has_direction(self) -> bool:
        return self.has_enrichment()

    def apply_direction(self, data: dict[str, Any] | None) -> None:
        if not isinstance(data, dict):
            return
        mapped = {
            "detail": data.get("detail") or data.get("focus"),
            "inner": data.get("inner") or data.get("intent"),
            "transition": data.get("transition") or data.get("direction"),
            "stance": data.get("stance") or data.get("exit"),
            "window_start": data.get("window_start"),
            "window_end": data.get("window_end"),
        }
        self.apply_enrichment(mapped)

    def render_direction(self) -> str:
        return self.render_enrichment()

    @property
    def focus(self) -> str:
        return self.detail

    @focus.setter
    def focus(self, value: str) -> None:
        self.detail = _clip(value, _DETAIL_LIMIT)

    @property
    def intent(self) -> str:
        return self.inner

    @intent.setter
    def intent(self, value: str) -> None:
        self.inner = _clip(value, _INNER_LIMIT)

    @property
    def direction(self) -> str:
        return self.transition

    @direction.setter
    def direction(self, value: str) -> None:
        self.transition = _clip(value, _TRANSITION_LIMIT)

    @property
    def exit(self) -> str:
        return self.stance

    @exit.setter
    def exit(self, value: str) -> None:
        self.stance = _clip(value, _STANCE_LIMIT)


@dataclass
class DirectorPrivateNote:
    """仅导演可见：代入角色后的临场心思；不注入角色。"""

    thinking: str = ""
    noticing: str = ""
    wanting: str = ""

    def snapshot(self) -> dict[str, Any]:
        return {
            "thinking": self.thinking,
            "noticing": self.noticing,
            "wanting": self.wanting,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> DirectorPrivateNote:
        if not isinstance(data, dict):
            return cls()
        return cls(
            thinking=str(data.get("thinking") or "").strip(),
            noticing=str(data.get("noticing") or "").strip(),
            wanting=str(data.get("wanting") or "").strip(),
        )

    def render(self) -> str:
        lines = ["[导演私有·角色此刻心思]"]
        if self.thinking.strip():
            lines.append(f"在想={self.thinking.strip()}")
        if self.noticing.strip():
            lines.append(f"注意到={self.noticing.strip()}")
        if self.wanting.strip():
            lines.append(f"想做/不想做={self.wanting.strip()}")
        return "\n".join(lines) if len(lines) > 1 else ""


@dataclass
class CharacterRhythmSchedule:
    """节奏扩充表：与剧情 unit 1:1；活队列不足时补仓。"""

    executable_units: list[ExecutableUnit] = field(default_factory=list)
    consumption_history: list[dict[str, Any]] = field(default_factory=list)
    private: DirectorPrivateNote = field(default_factory=DirectorPrivateNote)
    revised_at: float = 0.0
    poll_seq: int = 0
    version: int = 1

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": int(self.version),
            "poll_seq": int(self.poll_seq),
            "revised_at": float(self.revised_at),
            "executable_units": [e.snapshot() for e in self.executable_units],
            "consumption_history": [dict(item) for item in self.consumption_history],
            "private": self.private.snapshot(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> CharacterRhythmSchedule:
        if not isinstance(data, dict):
            return cls()
        units: list[ExecutableUnit] = []
        raw_units = data.get("executable_units")
        if isinstance(raw_units, list):
            for item in raw_units:
                entry = ExecutableUnit.from_dict(item if isinstance(item, dict) else None)
                if entry is not None:
                    units.append(entry)
        history = data.get("consumption_history")
        return cls(
            executable_units=units,
            consumption_history=[
                dict(item) for item in history if isinstance(item, dict)
            ][-12:]
            if isinstance(history, list)
            else [],
            private=DirectorPrivateNote.from_dict(
                data.get("private") if isinstance(data.get("private"), dict) else None
            ),
            revised_at=float(data.get("revised_at") or 0.0),
            poll_seq=int(data.get("poll_seq") or 0),
            version=max(1, int(data.get("version") or 1)),
        )

    def live_unit_count(self) -> int:
        return len(
            [
                e
                for e in self.executable_units
                if e.status in ("pending", "reserved") and e.plot_unit_id
            ]
        )

    def needs_refill(self, *, min_live: int = MIN_LIVE_UNITS_BEFORE_WAKE) -> bool:
        return self.live_unit_count() < max(1, int(min_live))

    def covered_plot_ids(self) -> set[str]:
        return {
            e.plot_unit_id
            for e in self.executable_units
            if e.plot_unit_id and e.status not in ("cancelled",)
        }

    def unit_for_plot(self, plot_unit_id: str) -> ExecutableUnit | None:
        pid = str(plot_unit_id or "").strip()
        if not pid:
            return None
        for entry in self.executable_units:
            if entry.plot_unit_id == pid and entry.status in ("pending", "reserved"):
                return entry
        for entry in self.executable_units:
            if entry.plot_unit_id == pid:
                return entry
        return None

    def render_for_director(self) -> str:
        lines = [
            "[节奏扩充表｜剧情 unit 1:1]",
            f"version={self.version} poll_seq={self.poll_seq} live={self.live_unit_count()}",
        ]
        if self.executable_units:
            lines.append("节奏卡：")
            for entry in self.executable_units:
                lines.append(entry.render_for_director())
        else:
            lines.append("节奏卡：（无）")
        if self.consumption_history:
            lines.append("最近已消费：")
            for item in self.consumption_history[-6:]:
                lines.append(
                    f"- id={item.get('unit_id', '')} "
                    f"plot={item.get('plot_unit_id') or item.get('plot_unit_ids', '—')} "
                    f"reason={item.get('reason', '—')}"
                )
        private = self.private.render()
        if private:
            lines.append(private)
        return "\n".join(lines)

    def due_units(self, *, now: float | None = None) -> list[ExecutableUnit]:
        """窗口已到且仍 pending 的节奏卡（开窗交付）。"""
        current = time.time() if now is None else float(now)
        due: list[ExecutableUnit] = []
        for e in self.executable_units:
            if e.status != "pending":
                continue
            start = float(e.window_start if e.window_start is not None else e.open_at)
            if start <= current:
                due.append(e)
        return due

    def pending_units(self) -> list[ExecutableUnit]:
        return [e for e in self.executable_units if e.status == "pending"]

    def mark_reserved(self, unit_id: str) -> ExecutableUnit | None:
        eid = unit_id.strip()
        for entry in self.executable_units:
            if entry.unit_id == eid and entry.status in ("pending", "reserved"):
                entry.status = "reserved"
                return entry
        return None

    def release_reserved(self, unit_id: str) -> ExecutableUnit | None:
        eid = unit_id.strip()
        for entry in self.executable_units:
            if entry.unit_id == eid and entry.status == "reserved":
                entry.status = "pending"
                return entry
        return None

    def mark_consumed(
        self,
        unit_id: str,
        *,
        turn_index: int = 0,
        trigger_id: str = "",
        consumed_at: float | None = None,
        plot_fingerprint: str = "",
        script_text: str = "",
        answer_fingerprint: str = "",
    ) -> ExecutableUnit | None:
        eid = unit_id.strip()
        for entry in self.executable_units:
            if entry.unit_id == eid and entry.status in ("pending", "reserved"):
                entry.status = "consumed"
                self.consumption_history.append(
                    {
                        "unit_id": entry.unit_id,
                        "plot_unit_id": entry.plot_unit_id,
                        "plot_unit_ids": list(entry.plot_unit_ids),
                        "reason": entry.reason,
                        "script_text": str(
                            script_text or entry.script_text or ""
                        ).strip()[:240],
                        "answer_fingerprint": str(answer_fingerprint or "").strip()[:120],
                        "turn_index": int(turn_index or 0),
                        "trigger_id": trigger_id.strip(),
                        "consumed_at": float(
                            time.time() if consumed_at is None else consumed_at
                        ),
                        "plot_fingerprint": str(plot_fingerprint or "").strip(),
                    }
                )
                self.consumption_history = self.consumption_history[-12:]
                return entry
        return None

    def mark_fired(self, unit_id: str) -> ExecutableUnit | None:
        return self.mark_consumed(unit_id)

    def last_consumed_script_text(self) -> str:
        if not self.consumption_history:
            return ""
        return str(self.consumption_history[-1].get("script_text") or "").strip()

    def last_answer_fingerprint(self) -> str:
        if not self.consumption_history:
            return ""
        return str(self.consumption_history[-1].get("answer_fingerprint") or "").strip()

    def blocks_repeat_same_script(self, script_text: str) -> bool:
        script = str(script_text or "").strip()
        if not script:
            return False
        return script == self.last_consumed_script_text()

    def blocks_repeat_without_plot_progress(
        self,
        plot_unit_ids: tuple[str, ...] | list[str],
        *,
        plot_fingerprint: str,
    ) -> bool:
        """同剧情指纹下已消费过该 plot 则拦截重复 handoff。"""
        fingerprint = str(plot_fingerprint or "").strip()
        if not fingerprint or not self.consumption_history:
            return False
        wanted = {
            str(pid).strip()
            for pid in (plot_unit_ids or ())
            if str(pid).strip()
        }
        for item in reversed(self.consumption_history):
            if str(item.get("plot_fingerprint") or "").strip() != fingerprint:
                continue
            prior = str(item.get("plot_unit_id") or "").strip()
            prior_ids = {
                str(pid).strip()
                for pid in (item.get("plot_unit_ids") or [])
                if str(pid).strip()
            }
            if prior:
                prior_ids.add(prior)
            if not wanted:
                return True
            if wanted & prior_ids:
                return True
        return False

    def cancel_due_without_plot_progress(
        self,
        *,
        plot_fingerprint: str,
        now: float | None = None,
    ) -> list[str]:
        current = time.time() if now is None else float(now)
        cancelled: list[str] = []
        for entry in self.executable_units:
            if entry.status != "pending":
                continue
            start = float(entry.window_start if entry.window_start is not None else entry.open_at)
            if start > current:
                continue
            if not self.blocks_repeat_without_plot_progress(
                entry.plot_unit_ids,
                plot_fingerprint=plot_fingerprint,
            ):
                continue
            entry.status = "cancelled"
            cancelled.append(entry.unit_id)
        return cancelled

    def sync_scripts_from_plot_arc(self, plot_arc) -> int:
        if plot_arc is None or not getattr(plot_arc, "ready", False):
            return 0
        by_id = {
            str(u.unit_id): u
            for u in list(getattr(plot_arc, "units", None) or [])
            if str(getattr(u, "unit_id", "") or "").strip()
        }
        if not by_id:
            return 0
        changed = 0
        for entry in self.executable_units:
            if entry.status not in ("pending", "reserved"):
                continue
            if not entry.plot_unit_id:
                continue
            unit = by_id.get(entry.plot_unit_id)
            if unit is None:
                continue
            if str(getattr(unit, "status", "") or "") == "done":
                continue
            intent = str(getattr(unit, "intent", "") or "").strip()
            if not intent:
                continue
            script = f"本拍台本：\n- {intent}"
            if script != entry.script_text:
                entry.script_text = script
                changed += 1
        return changed

    def character_script_card(self, *, now: float | None = None) -> str:
        current = time.time() if now is None else float(now)
        due = self.due_units(now=current)
        if due:
            entry = min(
                due,
                key=lambda e: float(
                    e.window_start if e.window_start is not None else e.open_at
                ),
            )
            return entry.render_script_for_character()
        pending = self.pending_units()
        if not pending:
            return ""
        entry = min(
            pending,
            key=lambda e: float(
                e.window_start if e.window_start is not None else e.open_at
            ),
        )
        return entry.render_script_for_character()

    def replace_from_director_payload(
        self,
        payload: dict[str, Any],
        *,
        poll_seq: int,
        now: float | None = None,
    ) -> CharacterRhythmSchedule:
        current = time.time() if now is None else float(now)
        next_table = CharacterRhythmSchedule.from_dict(payload)
        next_table.revised_at = current
        next_table.poll_seq = int(poll_seq)
        next_table.version = int(self.version) + 1

        kept_ids = {
            e.unit_id: e
            for e in self.executable_units
            if e.status in ("reserved", "consumed", "fired", "cancelled")
        }
        merged: list[ExecutableUnit] = []
        seen: set[str] = set()
        seen_plots: set[str] = set()
        for entry in next_table.executable_units:
            if entry.unit_id in kept_ids:
                merged.append(kept_ids[entry.unit_id])
                seen.add(entry.unit_id)
                if entry.plot_unit_id:
                    seen_plots.add(entry.plot_unit_id)
                continue
            # 1:1：同一 plot 只保留一张 live 卡
            if entry.plot_unit_id and entry.plot_unit_id in seen_plots:
                continue
            if entry.status not in ("pending", "reserved", "consumed", "fired", "cancelled"):
                entry.status = "pending"
            merged.append(entry)
            seen.add(entry.unit_id)
            if entry.plot_unit_id:
                seen_plots.add(entry.plot_unit_id)
        for eid, old in kept_ids.items():
            if eid not in seen:
                merged.append(old)
        next_table.executable_units = merged
        next_table.consumption_history = [dict(x) for x in self.consumption_history]
        return next_table
