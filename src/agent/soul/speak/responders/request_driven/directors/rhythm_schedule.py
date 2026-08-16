from __future__ import annotations

import logging
import time
from typing import Any

from ..orchestrator.state.core.character_rhythm_schedule import (
    CharacterRhythmSchedule,
    DirectorPrivateNote,
    ExecutableUnit,
)
from ..orchestrator.state.core.interaction_plan import MIN_LIVE_UNITS_BEFORE_WAKE
from ..orchestrator.state.core.speak_agenda import (
    BOOKING_GAP_MIN_SEC,
    CharacterSpeakAgenda,
)
from ..orchestrator.state.core.types import SessionSnapshot
from .agent import append_frame_prompt
from .base import DIRECTOR_VOICE, DirectorLLMCaller, DirectorOutput, extract_json_object

logger = logging.getLogger(__name__)


_DIRECTOR_VOICE = (
    "你是导演，指导角色，不代替角色说话。"
    "对方在远程通过文字与角色通信，不在她身边；这个端口是她对外发短消息的渠道。"
    "角色对外只写 <speak>，每次一条短消息，不写动作。"
    "这一拍手头的动作、过渡和姿态，需要由你写具体，形成一个连续过程——包括手头细节、内心倾向、过渡和姿态，并写入现实时间轴。"
    "动作不能留空，也不能让角色自己编，否则她会凭空编造。"
    "不要演独角戏，也不要把整段探索讲完。"
    "你只写处境，不写角色台词，也不用第一人称「我」去演角色；台词由角色 agent 负责。"
    "不需要询问剧情是否进行完。"
)

_ENRICH_RULE = (
    "一张节奏卡对应一个剧情 unit。"
    "用第二人称「你」扩充这张剧情卡：写这一拍的动作、情感和过渡，形成连续过程。"
    "角色通过端口给对方发短消息，不写动作；动作写进这张卡里。"
    "detail 写物件、手势、光线、位置，让角色清楚自己在做什么。\n"
    "不写角色台词，不演独角戏，不把后续步骤一次讲完。"
    "你只写处境。\n"
    "detail：手头具体的动作细节。\n"
    "inner：当下的情感或想法。\n"
    "transition：动作之间的衔接方式。\n"
    "stance：态度——犹豫、拒绝，还是直接做。\n"
    "duration_sec：这个动作在现实里完成需要的时间。"
    "不同动作耗时不同，按实际情况估算。\n"
    "window_start_sec：相对现在，这一步何时开始；window_end = 开始 + duration_sec。\n"
    "timeline 里每条是开口预约：at_sec 是距现在的秒数，plot_unit_id 绑定对应的剧情卡。"
    "下一次开口至少等上一动作做完；系统硬间隔约 25 秒是下限，实际间隔按动作时长往后排。\n"
    "reason 写清这个动作为什么需要这么长时间。\n"
)

_UNIT_JSON = (
    '"plot_unit_id":"","detail":"","inner":"","transition":"","stance":"",'
    '"duration_sec":40,"window_start_sec":0,"reason":""'
)


class RhythmScheduleDirector:
    """节奏扩充导演：1:1 扩剧情卡 + 写墙钟时间轴；不问完备。"""

    name = "rhythm_schedule"

    _SYSTEM_REFILL = (
        f"{_DIRECTOR_VOICE}\n"
        "维护节奏扩充表与现实时间轴。当可用队列不足时，给还没有节奏卡的剧情 unit 写扩充。\n"
        f"{_ENRICH_RULE}"
        "timeline 按动作时长串联：后一条 at_sec ≥ 前一条 at_sec + 前一条 duration_sec。\n"
        "输出 JSON："
        '{"action":"refill",'
        f'"executable_units":[{{{_UNIT_JSON}}}],'
        '"timeline":[{"at_sec":40,"plot_unit_id":"","reason":""}],'
        '"private":{"thinking":"…","noticing":"…","wanting":"…"}}'
    )

    _SYSTEM_REVISE = (
        f"{_DIRECTOR_VOICE}\n"
        "角色给了反馈，或时间轴需要调整。修订节奏扩充与时间轴。\n"
        f"{_ENRICH_RULE}"
        "action=keep：只改 private；update：修改已有节奏卡（带 unit_id）；"
        "refill：给缺少节奏卡的剧情 unit 补扩充。\n"
        "输出 JSON："
        '{"action":"keep|update|refill",'
        f'"executable_units":[{{"unit_id":"",{_UNIT_JSON}}}],'
        '"timeline":[{"at_sec":40,"plot_unit_id":"","reason":""}],'
        '"private":{"thinking":"…","noticing":"…","wanting":"…"}}'
    )

    def __init__(self, llm: DirectorLLMCaller) -> None:
        self._llm = llm

    def run(
        self,
        snapshot: SessionSnapshot,
        *,
        current: CharacterRhythmSchedule,
        user_text: str = "",
        dialogue_history: str = "",
        force_open_now: bool = False,
        poll: bool = False,
        interaction_unit_brief: str = "",
        interaction_evidence: str = "",
        plot_arc=None,
        agenda: CharacterSpeakAgenda | None = None,
        character_feedback: str = "",
        revise: bool = False,
    ) -> DirectorOutput:
        del force_open_now  # 开口权在议程/角色决策，不再 force ladder
        is_revise = bool(revise) or bool(str(character_feedback or "").strip())
        need_refill = current.needs_refill(min_live=MIN_LIVE_UNITS_BEFORE_WAKE)
        if plot_arc is not None and getattr(plot_arc, "ready", False):
            uncovered = self._uncovered_plot_units(plot_arc, current)
            need_refill = need_refill or bool(uncovered)
        # poll 且不需补仓、无反馈：跳过 LLM
        if poll and not is_revise and not need_refill:
            nxt = CharacterRhythmSchedule.from_dict(current.snapshot())
            nxt.poll_seq = int(current.poll_seq or 0) + 1
            nxt.revised_at = time.time()
            if plot_arc is not None:
                nxt.sync_scripts_from_plot_arc(plot_arc)
            return DirectorOutput(
                director=self.name,
                payload={
                    "action": "keep",
                    "schedule": nxt.snapshot(),
                    "timeline": [],
                },
                reason="poll_skip_no_refill",
            )

        system = self._SYSTEM_REVISE if is_revise else self._SYSTEM_REFILL
        if plot_arc is not None:
            current.sync_scripts_from_plot_arc(plot_arc)
        prompt = self._build_prompt(
            snapshot,
            current=current,
            user_text=user_text,
            dialogue_history=dialogue_history,
            interaction_unit_brief=interaction_unit_brief,
            interaction_evidence=interaction_evidence,
            plot_arc=plot_arc,
            agenda=agenda,
            character_feedback=character_feedback,
            need_refill=need_refill,
        )
        raw = self._llm.generate_json(
            system=system,
            user=prompt,
            session_id=snapshot.session_id,
            director=self.name,
            turn_index=snapshot.signals.turn_index,
        )
        payload = extract_json_object(raw)
        if not payload:
            schedule = self._fallback_enrich(
                current,
                plot_arc=plot_arc,
                poll_seq=int(current.poll_seq or 0) + 1,
            )
            return DirectorOutput(
                director=self.name,
                payload={
                    "action": "refill",
                    "schedule": schedule.snapshot(),
                    "timeline": self._fallback_timeline(schedule),
                },
                reason="fallback_enrich",
                used_fallback=True,
            )

        action = str(payload.get("action") or "refill").strip().lower()
        if action not in ("keep", "update", "refill", "rewrite"):
            action = "refill"
        if action == "rewrite":
            action = "refill"

        if action == "keep":
            schedule = self._apply_keep(current, payload, plot_arc=plot_arc)
        elif action == "update":
            schedule = self._apply_update(
                current,
                payload,
                poll_seq=int(current.poll_seq or 0) + 1,
                plot_arc=plot_arc,
            )
        else:
            schedule = self._apply_refill(
                current,
                payload,
                poll_seq=int(current.poll_seq or 0) + 1,
                plot_arc=plot_arc,
            )

        timeline = self._parse_timeline(payload, now=time.time(), schedule=schedule)
        logger.info(
            "[rhythm_schedule] ok session=%s action=%s live=%d timeline=%d thinking=%r",
            snapshot.session_id,
            action,
            schedule.live_unit_count(),
            len(timeline),
            (schedule.private.thinking or "")[:80],
        )
        return DirectorOutput(
            director=self.name,
            payload={
                "action": action,
                "schedule": schedule.snapshot(),
                "timeline": timeline,
            },
            reason="enrich_ok",
        )

    def _build_prompt(
        self,
        snapshot: SessionSnapshot,
        *,
        current: CharacterRhythmSchedule,
        user_text: str,
        dialogue_history: str,
        interaction_unit_brief: str,
        interaction_evidence: str,
        plot_arc,
        agenda: CharacterSpeakAgenda | None,
        character_feedback: str,
        need_refill: bool,
    ) -> str:
        lines: list[str] = [
            f"turn_index={snapshot.signals.turn_index}",
            f"now_epoch={time.time():.3f}",
            f"need_refill={need_refill}",
            f"live_rhythm={current.live_unit_count()} min={MIN_LIVE_UNITS_BEFORE_WAKE}",
        ]
        lines.append("不要问剧情卡是否完备。只扩充、补仓、改时间轴。")
        lines.append(
            "每张卡先估 duration_sec：角色做完这一步实际要多久。"
            "下一开口至少排在上一动作做完之后，不要用同一秒数填所有卡。"
        )
        if character_feedback.strip():
            lines.append("[角色反馈｜据此修订]")
            lines.append(character_feedback.strip()[:1200])
        lines.append(current.render_for_director())
        if agenda is not None:
            lines.append(agenda.render_for_director())
        if plot_arc is not None and getattr(plot_arc, "ready", False):
            lines.append("[叙事剧情 unit｜缺卡的请补节奏扩充]")
            lines.append(plot_arc.render_for_inject(max_pending=8))
            uncovered = self._uncovered_plot_units(plot_arc, current)
            if uncovered:
                lines.append("尚未有节奏卡的剧情 unit：")
                for unit in uncovered:
                    lines.append(
                        f"- id={unit.unit_id} intent={getattr(unit, 'intent', '')}"
                    )
        brief = interaction_unit_brief.strip()
        if brief:
            lines.append("[当前交互单元]")
            lines.append(brief)
        evidence = interaction_evidence.strip()
        if evidence:
            lines.append(evidence)
        history = dialogue_history.strip()
        if history:
            lines.append("[用户交互历史]")
            lines.append(history[:1200])
        text = user_text.strip() or snapshot.dialogue.user_text.strip()
        if text:
            lines.append(f"user_text={text[:400]}")
        return append_frame_prompt("\n".join(lines), snapshot)

    def _uncovered_plot_units(self, plot_arc, current: CharacterRhythmSchedule) -> list[Any]:
        covered = current.covered_plot_ids()
        out: list[Any] = []
        for unit in list(getattr(plot_arc, "units", None) or []):
            status = str(getattr(unit, "status", "") or "").strip().lower()
            if status == "done":
                continue
            uid = str(getattr(unit, "unit_id", "") or "").strip()
            intent = str(getattr(unit, "intent", "") or "").strip()
            if uid and intent and uid not in covered:
                out.append(unit)
        return out

    def _apply_private(
        self,
        nxt: CharacterRhythmSchedule,
        payload: dict[str, Any],
    ) -> None:
        private = payload.get("private")
        if isinstance(private, dict):
            note = DirectorPrivateNote.from_dict(private)
            if note.thinking or note.noticing or note.wanting:
                nxt.private = note

    def _parse_unit_item(
        self,
        item: dict[str, Any],
        *,
        now: float,
        plot_arc=None,
        default_reason: str = "",
    ) -> ExecutableUnit | None:
        plot_id = str(item.get("plot_unit_id") or "").strip()
        if not plot_id:
            raw_ids = item.get("plot_unit_ids") or ()
            if isinstance(raw_ids, str) and raw_ids.strip():
                plot_id = raw_ids.strip()
            elif isinstance(raw_ids, (list, tuple)):
                for x in raw_ids:
                    if str(x).strip():
                        plot_id = str(x).strip()
                        break
        if not plot_id and plot_arc is not None and getattr(plot_arc, "ready", False):
            active = plot_arc.active_unit()
            if active is not None and str(active.unit_id or "").strip():
                plot_id = str(active.unit_id).strip()
        if "window_start" in item and item.get("window_start") is not None:
            window_start = float(item.get("window_start"))
        else:
            window_start = now + max(0.0, float(item.get("window_start_sec") or 0.0))
        detail = str(item.get("detail") or item.get("focus") or "").strip()
        inner = str(item.get("inner") or item.get("intent") or "").strip()
        transition = str(item.get("transition") or item.get("direction") or "").strip()
        stance = str(item.get("stance") or item.get("exit") or "").strip()
        script = str(item.get("script_text") or "").strip()
        duration = _resolve_action_duration_sec(
            item,
            window_start=window_start,
            now=now,
            text=" ".join((detail, inner, script)),
        )
        window_end = window_start + duration
        return ExecutableUnit(
            unit_id=str(item.get("unit_id") or "").strip(),
            plot_unit_id=plot_id,
            script_text=script,
            reason=str(item.get("reason") or default_reason).strip(),
            status="pending",
            detail=detail,
            inner=inner,
            transition=transition,
            stance=stance,
            window_start=window_start,
            window_end=window_end,
            open_at=window_start,
        )

    def _apply_keep(
        self,
        current: CharacterRhythmSchedule,
        payload: dict[str, Any],
        *,
        plot_arc=None,
    ) -> CharacterRhythmSchedule:
        nxt = CharacterRhythmSchedule.from_dict(current.snapshot())
        self._apply_private(nxt, payload)
        nxt.poll_seq = int(current.poll_seq or 0) + 1
        nxt.revised_at = time.time()
        if plot_arc is not None:
            nxt.sync_scripts_from_plot_arc(plot_arc)
        return nxt

    def _apply_update(
        self,
        current: CharacterRhythmSchedule,
        payload: dict[str, Any],
        *,
        poll_seq: int,
        plot_arc=None,
    ) -> CharacterRhythmSchedule:
        now = time.time()
        nxt = CharacterRhythmSchedule.from_dict(current.snapshot())
        self._apply_private(nxt, payload)
        by_id = {e.unit_id: e for e in nxt.executable_units}
        raw = payload.get("executable_units")
        if isinstance(raw, list):
            for item in raw:
                if not isinstance(item, dict):
                    continue
                uid = str(item.get("unit_id") or "").strip()
                entry = by_id.get(uid)
                if entry is None or entry.status not in ("pending", "reserved"):
                    continue
                parsed = self._parse_unit_item(
                    item, now=now, plot_arc=plot_arc, default_reason=entry.reason
                )
                if parsed is None:
                    continue
                # 禁止把节奏卡绑回已完成的剧情 unit
                target_plot = parsed.plot_unit_id or entry.plot_unit_id
                if plot_arc is not None and target_plot and getattr(plot_arc, "ready", False):
                    done_ids = {
                        str(getattr(u, "unit_id", "") or "").strip()
                        for u in list(getattr(plot_arc, "units", None) or [])
                        if str(getattr(u, "status", "") or "").strip().lower() == "done"
                    }
                    if target_plot in done_ids:
                        continue
                if parsed.plot_unit_id:
                    entry.plot_unit_id = parsed.plot_unit_id
                entry.apply_enrichment(parsed.snapshot())
                if parsed.reason:
                    entry.reason = parsed.reason
                if parsed.script_text:
                    entry.script_text = parsed.script_text
        nxt.poll_seq = int(poll_seq)
        nxt.version = int(current.version) + 1
        nxt.revised_at = now
        if plot_arc is not None:
            nxt.sync_scripts_from_plot_arc(plot_arc)
        return nxt

    def _apply_refill(
        self,
        current: CharacterRhythmSchedule,
        payload: dict[str, Any],
        *,
        poll_seq: int,
        plot_arc=None,
    ) -> CharacterRhythmSchedule:
        now = time.time()
        nxt = CharacterRhythmSchedule.from_dict(current.snapshot())
        self._apply_private(nxt, payload)
        covered = nxt.covered_plot_ids()
        raw = payload.get("executable_units")
        if isinstance(raw, list):
            for item in raw:
                if not isinstance(item, dict):
                    continue
                entry = self._parse_unit_item(
                    item, now=now, plot_arc=plot_arc, default_reason="refill"
                )
                if entry is None or not entry.plot_unit_id:
                    continue
                if entry.plot_unit_id in covered:
                    # 已有卡：轻刷扩充
                    existing = nxt.unit_for_plot(entry.plot_unit_id)
                    if existing is not None and existing.status == "pending":
                        existing.apply_enrichment(entry.snapshot())
                    continue
                if not entry.has_enrichment():
                    entry.detail = entry.detail or "你按台本把手头这一步做扎实"
                    entry.inner = entry.inner or "你留意对方有没有搭话"
                    entry.transition = entry.transition or "你先做完眼前的，再决定开不开口"
                    entry.stance = entry.stance or "你自然推进，不强求对方立刻回"
                nxt.executable_units.append(entry)
                covered.add(entry.plot_unit_id)
        # 仍缺卡：启发式补
        if plot_arc is not None:
            delay = 0.0
            for unit in self._uncovered_plot_units(plot_arc, nxt):
                entry = _heuristic_enrich_unit(
                    unit, now=now, delay=delay, index=nxt.live_unit_count()
                )
                nxt.executable_units.append(entry)
                delay += entry.action_duration_sec() or BOOKING_GAP_MIN_SEC
        nxt.poll_seq = int(poll_seq)
        nxt.version = int(current.version) + 1
        nxt.revised_at = now
        if plot_arc is not None:
            nxt.sync_scripts_from_plot_arc(plot_arc)
        return nxt

    def _parse_timeline(
        self,
        payload: dict[str, Any],
        *,
        now: float,
        schedule: CharacterRhythmSchedule | None = None,
    ) -> list[dict[str, Any]]:
        raw = payload.get("timeline") or payload.get("speak_timeline") or []
        if not isinstance(raw, list):
            return []
        out: list[dict[str, Any]] = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            if item.get("at") is not None:
                at = float(item.get("at"))
            else:
                at = now + max(0.0, float(item.get("at_sec") or 0.0))
            plot_id = str(item.get("plot_unit_id") or "").strip()
            duration = _duration_for_plot(schedule, plot_id)
            if item.get("duration_sec") is not None:
                duration = _clamp_duration_sec(float(item.get("duration_sec") or 0.0))
            out.append(
                {
                    "at": at,
                    "plot_unit_id": plot_id,
                    "reason": str(item.get("reason") or "").strip()[:240],
                    "duration_sec": duration,
                    "source": "director",
                }
            )
        return _chain_timeline_by_duration(out)

    def _fallback_enrich(
        self,
        current: CharacterRhythmSchedule,
        *,
        plot_arc,
        poll_seq: int,
    ) -> CharacterRhythmSchedule:
        now = time.time()
        nxt = CharacterRhythmSchedule.from_dict(current.snapshot())
        if plot_arc is not None:
            delay = 0.0
            for index, unit in enumerate(self._uncovered_plot_units(plot_arc, nxt)):
                entry = _heuristic_enrich_unit(unit, now=now, delay=delay, index=index)
                nxt.executable_units.append(entry)
                delay += entry.action_duration_sec() or BOOKING_GAP_MIN_SEC
            nxt.sync_scripts_from_plot_arc(plot_arc)
        nxt.poll_seq = int(poll_seq)
        nxt.version = int(current.version) + 1
        nxt.revised_at = now
        return nxt

    def _fallback_timeline(self, schedule: CharacterRhythmSchedule) -> list[dict[str, Any]]:
        now = time.time()
        out: list[dict[str, Any]] = []
        cursor = now
        for entry in schedule.pending_units():
            start = float(
                entry.window_start if entry.window_start is not None else entry.open_at
            )
            if start < cursor:
                start = cursor
            duration = entry.action_duration_sec() or estimate_action_duration_sec(
                " ".join((entry.detail, entry.script_text, entry.reason))
            )
            out.append(
                {
                    "at": start,
                    "plot_unit_id": entry.plot_unit_id,
                    "reason": entry.reason or "window_open",
                    "duration_sec": duration,
                    "source": "director",
                }
            )
            cursor = start + max(BOOKING_GAP_MIN_SEC, duration)
        return out


def _heuristic_enrich_unit(
    unit: Any, *, now: float, delay: float, index: int
) -> ExecutableUnit:
    intent = str(getattr(unit, "intent", "") or "").strip()
    uid = str(getattr(unit, "unit_id", "") or "").strip()
    duration = estimate_action_duration_sec(intent)
    return ExecutableUnit(
        plot_unit_id=uid,
        reason=f"heuristic_enrich_{index}",
        status="pending",
        detail=(
            f"你正做到这一步：{intent}。手碰到什么、光线和位置按这一步写实。"
            if intent
            else "你把眼前这一步的手和物件走实，不要空演。"
        ),
        inner="你留意手头触感，也留意对方有没有回消息",
        transition="你先把这一步做完，再决定要不要发一条短消息",
        stance="你按自己的节奏来，不朝空气演独角戏",
        window_start=now + delay,
        window_end=now + delay + duration,
        open_at=now + delay,
        script_text=f"本拍台本：\n- {intent}" if intent else "",
    )


def _clamp_duration_sec(value: float) -> float:
    return max(8.0, min(240.0, float(value)))


def estimate_action_duration_sec(text: str) -> float:
    """按动作本身估现实时长：短动作短约，读/比对/寻找更久。"""
    blob = str(text or "")
    if any(mark in blob for mark in ("读", "看完", "比对", "抄", "写", "寻找", "翻找", "核对")):
        return 75.0
    if any(mark in blob for mark in ("翻开", "整理", "蹲", "检查", "确认", "辨认")):
        return 40.0
    if any(mark in blob for mark in ("吹", "抽", "取下", "抬眼", "拂", "拍")):
        return 18.0
    return 35.0


def _resolve_action_duration_sec(
    item: dict[str, Any],
    *,
    window_start: float,
    now: float,
    text: str,
) -> float:
    if item.get("duration_sec") is not None:
        return _clamp_duration_sec(float(item.get("duration_sec") or 0.0))
    if "window_end" in item and item.get("window_end") is not None:
        return _clamp_duration_sec(float(item.get("window_end")) - window_start)
    if item.get("window_end_sec") is not None:
        end = now + max(0.0, float(item.get("window_end_sec") or 0.0))
        return _clamp_duration_sec(end - window_start)
    return estimate_action_duration_sec(text)


def _duration_for_plot(schedule: CharacterRhythmSchedule | None, plot_id: str) -> float:
    if schedule is None or not plot_id:
        return BOOKING_GAP_MIN_SEC
    entry = schedule.unit_for_plot(plot_id)
    if entry is None:
        return BOOKING_GAP_MIN_SEC
    held = entry.action_duration_sec()
    return held if held > 0 else BOOKING_GAP_MIN_SEC


def _chain_timeline_by_duration(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not items:
        return []
    ordered = sorted(items, key=lambda item: float(item.get("at") or 0.0))
    prev_at: float | None = None
    prev_duration = 0.0
    out: list[dict[str, Any]] = []
    for item in ordered:
        at = float(item.get("at") or 0.0)
        duration = _clamp_duration_sec(float(item.get("duration_sec") or 0.0))
        if prev_at is not None:
            floor = prev_at + max(BOOKING_GAP_MIN_SEC, prev_duration)
            if at < floor:
                at = floor
        nxt = dict(item)
        nxt["at"] = at
        nxt["duration_sec"] = duration
        out.append(nxt)
        prev_at = at
        prev_duration = duration
    return out


def seed_plot_unit_consumption_queue(
    current: CharacterRhythmSchedule,
    *,
    now: float | None = None,
    plot_arc=None,
) -> CharacterRhythmSchedule:
    """按 plot_arc 为缺卡剧情 unit 补启发式节奏卡（1:1）。"""
    current_ts = time.time() if now is None else float(now)
    nxt = CharacterRhythmSchedule.from_dict(current.snapshot())
    if plot_arc is None or not getattr(plot_arc, "ready", False):
        return nxt
    covered = nxt.covered_plot_ids()
    index = 0
    delay = 0.0
    for unit in list(getattr(plot_arc, "units", None) or []):
        status = str(getattr(unit, "status", "") or "").strip().lower()
        if status == "done":
            continue
        uid = str(getattr(unit, "unit_id", "") or "").strip()
        intent = str(getattr(unit, "intent", "") or "").strip()
        if not uid or not intent or uid in covered:
            continue
        entry = _heuristic_enrich_unit(
            unit, now=current_ts, delay=delay, index=index
        )
        nxt.executable_units.append(entry)
        delay += entry.action_duration_sec() or BOOKING_GAP_MIN_SEC
        covered.add(uid)
        index += 1
    nxt.sync_scripts_from_plot_arc(plot_arc)
    nxt.revised_at = current_ts
    nxt.version = int(current.version or 1) + 1
    return nxt


def seed_ladder_executable_units(
    current: CharacterRhythmSchedule,
    *,
    now: float | None = None,
    plot_arc=None,
) -> CharacterRhythmSchedule:
    return seed_plot_unit_consumption_queue(current, now=now, plot_arc=plot_arc)


def apply_rhythm_schedule_output(state, output: DirectorOutput) -> CharacterRhythmSchedule:
    payload = output.payload.get("schedule")
    schedule = CharacterRhythmSchedule.from_dict(
        payload if isinstance(payload, dict) else None
    )
    if not schedule.revised_at:
        schedule.revised_at = time.time()
    if getattr(state, "plot_arc", None) is not None:
        schedule.sync_scripts_from_plot_arc(state.plot_arc)
    state.character_rhythm_schedule = schedule
    state.director_cache["character_rhythm_schedule"] = schedule.snapshot()
    state.director_cache["rhythm_schedule_private"] = schedule.private.snapshot()
    state.director_cache.pop("pending_unit_complete", None)

    # 导演时间轴写入议程（过硬间隔）
    timeline = output.payload.get("timeline")
    if isinstance(timeline, list):
        agenda = getattr(state, "speak_agenda", None)
        if agenda is None:
            agenda = CharacterSpeakAgenda()
            state.speak_agenda = agenda
        for item in timeline:
            if not isinstance(item, dict):
                continue
            at = float(item.get("at") or 0.0)
            if at <= 0:
                continue
            agenda.add_speak(
                at=at,
                source="director",
                plot_unit_id=str(item.get("plot_unit_id") or "").strip(),
                reason=str(item.get("reason") or "").strip(),
                duration_sec=float(item.get("duration_sec") or 0.0),
                enforce=True,
            )
            agenda.cancel_character_overlapping(around=at)
        state.director_cache["speak_agenda"] = agenda.snapshot()

    due = schedule.due_units()
    soon = [
        {
            "unit_id": e.unit_id,
            "plot_unit_id": e.plot_unit_id,
            "window_start": e.window_start,
            "window_end": e.window_end,
        }
        for e in due[:4]
    ]
    state.director_cache["rhythm_due_preview"] = soon
    return schedule
