from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Literal

# 每个交互单元覆盖的轮询拍数 k；角色可见开口约 k/2 轮
DEFAULT_UNIT_SPAN_POLLS = 2
_MAX_LIVE_UNITS = 12
_MAX_UNIT_HISTORY = 24
# 兼容旧名
_MAX_UNITS = _MAX_LIVE_UNITS
# 用户↔角色往来满 3 轮，或剧情 unit 总数超过 5：到点检查；编剧对齐，导演仅在 unit 变动时醒
INTERACTION_ROUNDS_BEFORE_WAKE = 3
MIN_TOTAL_UNITS_BEFORE_ALIGN = 5
# 活队列不足时唤醒编剧/导演补仓（节奏卡与剧情卡共用）
MIN_LIVE_UNITS_BEFORE_WAKE = 5


def plot_units_fingerprint(arc: Any) -> str:
    """剧情 unit 指纹：活队列 status·intent + 历史长度。不含 id/version/poll。"""
    if arc is None or not getattr(arc, "ready", False):
        return ""
    chunks: list[str] = []
    for unit in list(getattr(arc, "units", None) or []):
        status = str(getattr(unit, "status", "") or "").strip()
        intent = str(getattr(unit, "intent", "") or "").strip()
        chunks.append(f"{status}:{intent}")
    history = list(getattr(arc, "unit_history", None) or [])
    chunks.append(f"h{len(history)}")
    if history:
        last = history[-1]
        if isinstance(last, dict):
            tail = str(last.get("intent") or "").strip()
        else:
            tail = str(getattr(last, "intent", "") or "").strip()
        if tail:
            chunks.append(tail)
    return "|".join(chunks)


def plot_units_changed_since_director(state: Any) -> bool:
    current = plot_units_fingerprint(getattr(state, "plot_arc", None))
    last = str(getattr(state, "director_aligned_plot_fingerprint", "") or "").strip()
    return bool(current) and current != last


def mark_director_plot_aligned(state: Any) -> None:
    state.director_aligned_plot_fingerprint = plot_units_fingerprint(
        getattr(state, "plot_arc", None)
    )


def should_wake_narrative(state: Any) -> bool:
    """到点检查：满 K 轮往来，或 unit 总数比上次检查多出超过阈值。"""
    arc = getattr(state, "plot_arc", None)
    if arc is None or not getattr(arc, "ready", False):
        return False
    return arc.needs_screenwriter_align(
        exchange_count=int(getattr(state, "interaction_exchange_count", 0) or 0),
        aligned_at_exchange=int(
            getattr(state, "screenwriter_aligned_at_exchange", 0) or 0
        ),
        aligned_at_total=int(getattr(state, "screenwriter_aligned_at_total", 0) or 0),
    )


def director_needs_init(state: Any) -> bool:
    """导演从未对齐过，且剧情弧已就绪：开场必须醒一次。"""
    last = str(getattr(state, "director_aligned_plot_fingerprint", "") or "").strip()
    if last:
        return False
    arc = getattr(state, "plot_arc", None)
    return bool(arc is not None and getattr(arc, "ready", False))


def should_wake_director(state: Any) -> bool:
    """开场必醒一次；之后计数器到点且剧情 unit 有变动才醒。"""
    if director_needs_init(state):
        return True
    if not should_wake_narrative(state):
        return False
    return plot_units_changed_since_director(state)


def reset_narrative_wake_counters(state: Any) -> None:
    """到点检查落账后清空往来计数，并把 unit 水位标到当前总数。"""
    state.interaction_exchange_count = 0
    state.screenwriter_aligned_at_exchange = 0
    arc = getattr(state, "plot_arc", None)
    total = 0
    if arc is not None and getattr(arc, "ready", False):
        total = int(arc.total_unit_count())
    state.screenwriter_aligned_at_total = total

InteractionUnitStatus = Literal["pending", "active", "done"]


def _new_unit_id() -> str:
    return f"iu-{uuid.uuid4().hex[:10]}"


@dataclass
class InteractionUnit:
    """角色议程中的一步（给角色看；与用户无关）。

    覆盖接下来 k 拍轮询（约 k/2 次可见开口）。动宾短句，对应故事线中的可执行节点。
    """

    intent: str
    evidence: str = ""
    span_polls: int = DEFAULT_UNIT_SPAN_POLLS
    status: InteractionUnitStatus = "pending"
    polls_consumed: int = 0
    unit_id: str = ""
    activated_at_poll: int = 0
    completed_at_poll: int = 0

    def __post_init__(self) -> None:
        if not self.unit_id.strip():
            self.unit_id = _new_unit_id()
        self.intent = str(self.intent or "").strip()
        self.evidence = str(self.evidence or "").strip()
        self.span_polls = max(1, int(self.span_polls or DEFAULT_UNIT_SPAN_POLLS))
        status = str(self.status or "pending").strip().lower()
        if status not in ("pending", "active", "done"):
            status = "pending"
        self.status = status  # type: ignore[assignment]

    @property
    def ready(self) -> bool:
        return bool(self.intent)

    @property
    def expected_speak_turns(self) -> int:
        return max(1, self.span_polls // 2)

    def snapshot(self) -> dict[str, Any]:
        return {
            "unit_id": self.unit_id,
            "intent": self.intent,
            "evidence": self.evidence,
            "span_polls": int(self.span_polls),
            "expected_speak_turns": self.expected_speak_turns,
            "status": self.status,
            "polls_consumed": int(self.polls_consumed),
            "activated_at_poll": int(self.activated_at_poll),
            "completed_at_poll": int(self.completed_at_poll),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> InteractionUnit | None:
        if not isinstance(data, dict):
            return None
        intent = str(data.get("intent") or data.get("text") or "").strip()
        if not intent:
            return None
        return cls(
            unit_id=str(data.get("unit_id") or "").strip(),
            intent=intent,
            evidence=str(data.get("evidence") or "").strip(),
            span_polls=int(data.get("span_polls") or DEFAULT_UNIT_SPAN_POLLS),
            status=str(data.get("status") or "pending"),  # type: ignore[arg-type]
            polls_consumed=int(data.get("polls_consumed") or 0),
            activated_at_poll=int(data.get("activated_at_poll") or 0),
            completed_at_poll=int(data.get("completed_at_poll") or 0),
        )


@dataclass
class PlotArc:
    """角色剧情弧（给角色看）：本场完整故事线与 units 活队列。

    备注：summary 是客观、冷静、真实的完整故事线（起因→经过→转折→收束）；
    受众是角色上下文，不是用户 UI；开场旁白另见 screenwriter opening。
    导演消费 unit 后抛入 unit_history；往来满 3 轮或 unit 总数超过 5 时由编剧对齐后续步骤。
    """

    summary: str = ""
    evidence: str = ""
    units: list[InteractionUnit] = field(default_factory=list)
    unit_history: list[dict[str, Any]] = field(default_factory=list)
    current_index: int = 0
    version: int = 1
    initialized_at: float = 0.0
    revised_at: float = 0.0

    @property
    def ready(self) -> bool:
        return bool(self.summary.strip() or self.units or self.unit_history)

    def live_unit_count(self) -> int:
        """活队列长度（pending+active，不含已归档）。"""
        return len([u for u in self.units if u.status != "done" and u.intent.strip()])

    def total_unit_count(self) -> int:
        """活队列 + 已消费历史。"""
        return self.live_unit_count() + len(self.unit_history)

    def needs_screenwriter_align(
        self,
        *,
        exchange_count: int,
        aligned_at_exchange: int = 0,
        aligned_at_total: int = 0,
        rounds: int = INTERACTION_ROUNDS_BEFORE_WAKE,
        min_total: int = MIN_TOTAL_UNITS_BEFORE_ALIGN,
    ) -> bool:
        """往来计数达到 rounds，或剧情 unit 总数比上次唤醒时多出超过 min_total。"""
        rounds_due = int(exchange_count) - int(aligned_at_exchange) >= max(1, int(rounds))
        units_due = self.total_unit_count() - int(aligned_at_total) > max(0, int(min_total))
        return rounds_due or units_due

    def active_unit(self) -> InteractionUnit | None:
        if not self.units:
            return None
        idx = max(0, min(int(self.current_index), len(self.units) - 1))
        unit = self.units[idx]
        if unit.status == "done":
            for i, u in enumerate(self.units):
                if u.status != "done":
                    self.current_index = i
                    return u
            return None
        return unit

    def pending_intents(self) -> list[str]:
        return [u.intent for u in self.units if u.status != "done" and u.intent]

    def snapshot(self) -> dict[str, Any]:
        active = self.active_unit()
        return {
            "summary": self.summary,
            "evidence": self.evidence,
            "units": [u.snapshot() for u in self.units],
            "unit_history": list(self.unit_history[-_MAX_UNIT_HISTORY:]),
            "current_index": int(self.current_index),
            "active_unit_id": active.unit_id if active is not None else "",
            "active_intent": active.intent if active is not None else "",
            "live_unit_count": self.live_unit_count(),
            "version": int(self.version),
            "initialized_at": float(self.initialized_at),
            "revised_at": float(self.revised_at),
            "ready": self.ready,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> PlotArc:
        if not isinstance(data, dict):
            return cls()
        units: list[InteractionUnit] = []
        for item in data.get("units") or []:
            unit = InteractionUnit.from_dict(item if isinstance(item, dict) else None)
            if unit is not None and unit.status != "done":
                units.append(unit)
        history: list[dict[str, Any]] = []
        for item in data.get("unit_history") or []:
            if isinstance(item, dict) and str(item.get("intent") or "").strip():
                history.append(dict(item))
        # 兼容旧快照：done 仍躺在 units 里 → 挪进历史
        for item in data.get("units") or []:
            if not isinstance(item, dict):
                continue
            if str(item.get("status") or "").strip().lower() != "done":
                continue
            if str(item.get("intent") or "").strip():
                history.append(dict(item))
        return cls(
            summary=str(data.get("summary") or "").strip(),
            evidence=str(data.get("evidence") or "").strip(),
            units=units[:_MAX_LIVE_UNITS],
            unit_history=history[-_MAX_UNIT_HISTORY:],
            current_index=max(0, int(data.get("current_index") or 0)),
            version=max(1, int(data.get("version") or 1)),
            initialized_at=float(data.get("initialized_at") or 0.0),
            revised_at=float(data.get("revised_at") or 0.0),
        )

    def render_for_inject(self, *, max_pending: int = 4) -> str:
        """面向角色 agent：冷静客观的故事线与步骤（不含导演节奏用语）。"""
        if not self.ready:
            return ""
        lines = ["[故事线]"]
        if self.summary.strip():
            lines.append(f"本场故事线：{self.summary.strip()}")
        active = self.active_unit()
        if active is not None and active.intent.strip():
            lines.append(f"当前步骤：{active.intent.strip()}")
        pending = [
            u for u in self.units
            if u.status == "pending" and u.intent.strip()
        ][: max(0, int(max_pending))]
        if pending:
            lines.append("后续步骤：")
            for u in pending:
                lines.append(f"- {u.intent.strip()}")
        return "\n".join(lines)

    def render_for_screenwriter(self) -> str:
        lines = [
            "[角色剧情弧·当前]",
            f"version={self.version} index={self.current_index} "
            f"live={self.live_unit_count()} history={len(self.unit_history)}",
            "说明：summary 是完整故事线；units 是覆盖故事线的可执行步骤；已消费 unit 在历史。",
        ]
        body = self.render_for_inject(max_pending=6)
        if body:
            lines.append(body)
        else:
            lines.append("步骤暂无——请从完整故事线与角色下一步动作写起。")
        if self.unit_history:
            lines.append("已消费历史（近几条）：")
            for item in self.unit_history[-6:]:
                intent = str(item.get("intent") or "").strip()
                if intent:
                    lines.append(f"- {intent}")
        return "\n".join(lines)

    def replace_from_payload(
        self,
        payload: dict[str, Any] | None,
        *,
        now: float | None = None,
        default_span: int = DEFAULT_UNIT_SPAN_POLLS,
    ) -> PlotArc:
        """初始化/重写整条剧情弧与交互单元队列。"""
        current = time.time() if now is None else float(now)
        if not isinstance(payload, dict):
            return self
        summary = str(payload.get("summary") or payload.get("arc_summary") or "").strip()
        evidence = str(payload.get("evidence") or "").strip()
        raw_units = payload.get("units") or payload.get("interaction_units") or []
        units: list[InteractionUnit] = []
        if isinstance(raw_units, list):
            for item in raw_units:
                if isinstance(item, str):
                    intent = item.strip()
                    if not intent:
                        continue
                    units.append(
                        InteractionUnit(
                            intent=intent,
                            evidence=evidence,
                            span_polls=default_span,
                            status="pending",
                        )
                    )
                    continue
                unit = InteractionUnit.from_dict(item if isinstance(item, dict) else None)
                if unit is None:
                    continue
                if not unit.evidence and evidence:
                    unit.evidence = evidence
                unit.status = "pending"
                unit.polls_consumed = 0
                units.append(unit)
        units = units[:_MAX_LIVE_UNITS]
        if not units and not summary:
            return self
        arc = PlotArc(
            summary=summary or (units[0].intent if units else ""),
            evidence=evidence,
            units=units,
            unit_history=list(self.unit_history[-_MAX_UNIT_HISTORY:]),
            current_index=0,
            version=int(self.version) + 1 if self.ready else 1,
            initialized_at=current if not self.initialized_at else self.initialized_at,
            revised_at=current,
        )
        if not arc.initialized_at:
            arc.initialized_at = current
        arc._activate_head(poll_seq=0)
        return arc

    def append_units_from_payload(
        self,
        payload: dict[str, Any] | None,
        *,
        now: float | None = None,
        default_span: int = DEFAULT_UNIT_SPAN_POLLS,
        poll_seq: int = 0,
    ) -> PlotArc:
        """续写补仓：追加 pending units，不整表推翻；可轻改 summary。"""
        current = time.time() if now is None else float(now)
        if not isinstance(payload, dict):
            return self
        summary = str(payload.get("summary") or payload.get("arc_summary") or "").strip()
        evidence = str(payload.get("evidence") or "").strip()
        raw_units = payload.get("units") or payload.get("append_units") or []
        added = 0
        if isinstance(raw_units, list):
            for item in raw_units:
                if self.live_unit_count() >= _MAX_LIVE_UNITS:
                    break
                if isinstance(item, str):
                    intent = item.strip()
                    if not intent:
                        continue
                    unit = InteractionUnit(
                        intent=intent,
                        evidence=evidence or self.evidence,
                        span_polls=default_span,
                        status="pending",
                    )
                elif isinstance(item, dict):
                    unit = InteractionUnit.from_dict(item)
                    if unit is None:
                        continue
                    unit.status = "pending"
                    unit.polls_consumed = 0
                    unit.activated_at_poll = 0
                    unit.completed_at_poll = 0
                    if not unit.evidence and (evidence or self.evidence):
                        unit.evidence = evidence or self.evidence
                else:
                    continue
                # 跳过与活队列末尾重复的 intent
                if self.units and self.units[-1].intent == unit.intent:
                    continue
                self.units.append(unit)
                added += 1
        if summary:
            self.summary = summary
        if evidence:
            self.evidence = evidence
        if added or summary or evidence:
            self.revised_at = current
            self.version = int(self.version) + 1
        if self.active_unit() is None and self.units:
            self._activate_head(poll_seq=int(poll_seq))
        return self

    def realign_pending_from_payload(
        self,
        payload: dict[str, Any] | None,
        *,
        now: float | None = None,
        default_span: int = DEFAULT_UNIT_SPAN_POLLS,
        poll_seq: int = 0,
    ) -> PlotArc:
        """对齐：保留当前 active，丢掉其余 pending，换上按交互修正后的后续步骤。"""
        current = time.time() if now is None else float(now)
        if not isinstance(payload, dict):
            return self
        summary = str(payload.get("summary") or payload.get("arc_summary") or "").strip()
        evidence = str(payload.get("evidence") or "").strip()
        raw_units = payload.get("units") or payload.get("append_units") or []
        active = self.active_unit()
        kept: list[InteractionUnit] = []
        if active is not None:
            kept.append(active)
        added: list[InteractionUnit] = []
        if isinstance(raw_units, list):
            for item in raw_units:
                if len(kept) + len(added) >= _MAX_LIVE_UNITS:
                    break
                if isinstance(item, str):
                    intent = item.strip()
                    if not intent:
                        continue
                    unit = InteractionUnit(
                        intent=intent,
                        evidence=evidence or self.evidence,
                        span_polls=default_span,
                        status="pending",
                    )
                elif isinstance(item, dict):
                    unit = InteractionUnit.from_dict(item)
                    if unit is None:
                        continue
                    unit.status = "pending"
                    unit.polls_consumed = 0
                    unit.activated_at_poll = 0
                    unit.completed_at_poll = 0
                    if not unit.evidence and (evidence or self.evidence):
                        unit.evidence = evidence or self.evidence
                else:
                    continue
                if active is not None and unit.intent == active.intent:
                    continue
                added.append(unit)
        self.units = kept + added
        self.current_index = 0 if kept else 0
        if summary:
            self.summary = summary
        if evidence:
            self.evidence = evidence
        self.revised_at = current
        self.version = int(self.version) + 1
        if self.active_unit() is None and self.units:
            self._activate_head(poll_seq=int(poll_seq))
        return self

    def note_poll(self, *, poll_seq: int) -> InteractionUnit | None:
        """轮询记账：只累计消耗拍数，不自动完成。完成权在导演确认。"""
        if not self.units:
            return None
        active = self.active_unit()
        if active is None:
            return None
        if active.status == "pending":
            self._activate_unit(active, poll_seq=poll_seq)
        active.polls_consumed = int(active.polls_consumed) + 1
        self.revised_at = time.time()
        return active

    def tick_poll(self, *, poll_seq: int) -> InteractionUnit | None:
        """兼容旧名：等价 note_poll（不再按 k 自动完成）。"""
        return self.note_poll(poll_seq=poll_seq)

    def complete_active(self, *, poll_seq: int = 0, reason: str = "") -> InteractionUnit | None:
        """导演消费当前 unit：抛入历史并移出活队列，再激活下一个。"""
        active = self.active_unit()
        if active is None:
            return None
        archived = active.snapshot()
        archived["status"] = "done"
        archived["completed_at_poll"] = int(poll_seq)
        archived["archived_reason"] = str(reason or "").strip()
        archived["archived_at"] = time.time()
        self.unit_history.append(archived)
        if len(self.unit_history) > _MAX_UNIT_HISTORY:
            self.unit_history = self.unit_history[-_MAX_UNIT_HISTORY:]
        self.units = [u for u in self.units if u.unit_id != active.unit_id]
        self.revised_at = time.time()
        self.version = int(self.version) + 1
        if self.units:
            self._activate_head(poll_seq=poll_seq)
        else:
            self.current_index = 0
        return self.active_unit()

    def _activate_head(self, *, poll_seq: int) -> None:
        if not self.units:
            return
        self.current_index = 0
        self._activate_unit(self.units[0], poll_seq=poll_seq)

    def _activate_next(self, *, poll_seq: int) -> None:
        for i, unit in enumerate(self.units):
            if unit.status != "done":
                self.current_index = i
                self._activate_unit(unit, poll_seq=poll_seq)
                return
        self.current_index = max(0, len(self.units) - 1) if self.units else 0

    def _activate_unit(self, unit: InteractionUnit, *, poll_seq: int) -> None:
        if unit.status == "done":
            return
        unit.status = "active"
        if unit.activated_at_poll <= 0:
            unit.activated_at_poll = int(poll_seq)


def build_grounded_heuristic_arc(
    *,
    evidence: str,
    seeds: list[str] | None = None,
    span_polls: int = DEFAULT_UNIT_SPAN_POLLS,
    now: float | None = None,
) -> PlotArc:
    """无 LLM 时的有据兜底：只写角色侧具体动作，不用元话语。"""
    current = time.time() if now is None else float(now)
    ev = evidence.strip()
    seed_list = [
        str(x).strip()
        for x in (seeds or [])
        if str(x).strip() and 2 <= len(str(x).strip()) <= 12
    ]
    object_hint = ""
    for token in seed_list:
        if not token.endswith("角色"):
            object_hint = token
            break
    if object_hint:
        summary = f"角色在场，围绕眼前的{object_hint}做手头整理"
        units = [
            InteractionUnit(
                intent=f"停在{object_hint}旁，先看清摆放",
                evidence=ev or object_hint,
                span_polls=span_polls,
            ),
            InteractionUnit(
                intent=f"把{object_hint}再确认或整理一遍",
                evidence=ev or object_hint,
                span_polls=span_polls,
            ),
            InteractionUnit(
                intent=f"记下{object_hint}眼下的状态",
                evidence=ev or object_hint,
                span_polls=span_polls,
            ),
        ]
    elif ev:
        summary = "角色在场，继续手头未完成的活计"
        units = [
            InteractionUnit(
                intent="留意眼前物件与光线",
                evidence=ev,
                span_polls=span_polls,
            ),
            InteractionUnit(
                intent="把眼前物件再确认一遍",
                evidence=ev,
                span_polls=span_polls,
            ),
        ]
    else:
        summary = "角色在场，手上有未完成的活计"
        units = [
            InteractionUnit(
                intent="停在原处，继续手头活计",
                evidence="（依据不足）",
                span_polls=span_polls,
            ),
        ]
    arc = PlotArc(
        summary=summary,
        evidence=ev or object_hint or "（依据不足）",
        units=units,
        initialized_at=current,
        revised_at=current,
    )
    arc._activate_head(poll_seq=0)
    return arc
