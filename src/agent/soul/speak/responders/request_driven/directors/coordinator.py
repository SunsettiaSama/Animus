from __future__ import annotations

import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING, Any

from ..orchestrator.prompt_trace import get_prompt_trace
from ..orchestrator.state.snapshot.builder import SnapshotBuilder
from .domain import InterruptDirector, SocialArmDirector
from .module_inject import ModuleInjectDirector
from ..screenwriter.materials import build_writing_materials
from .next_turn_guide import (
    NextTurnGuideDirector,
    apply_next_turn_guide_output,
    promote_pending_next_turn_guide,
)
from .outline import OutlineDirector, apply_outline_output
from .base import DirectorOutput
from .fallback import fallback_delivery_plan, fallback_delivery_plan_for_silence
from ..screenwriter.writer import Screenwriter
from .rhythm_schedule import RhythmScheduleDirector, apply_rhythm_schedule_output
from .turn_delivery import TurnDeliveryDirector, apply_turn_delivery_output
from .user_intent import UserIntentDirector, apply_user_intent_output
from .agent import build_rhythm_card, inject_director_frame
from .agent.fate import fate_band_label
from .agent.units import (
    AgentDeliveryTraceUnit,
    PollTickUnit,
    UserSilenceUnit,
)
from ..orchestrator.state.core.character_rhythm_schedule import (
    CharacterRhythmSchedule,
)
from ..orchestrator.state.core.delivery import ReplySegment, build_delivery_plan
from ..orchestrator.state.core.interaction_plan import (
    director_needs_init,
    mark_director_plot_aligned,
    plot_units_changed_since_director,
    should_wake_narrative,
)
from ..orchestrator.state.core.speak_dormant import (
    enter_speak_dormant,
    needs_narrative_reinit,
    should_enter_dormant,
    clear_narrative_for_reinit,
)
from ..character.context import build_character_reply_request
from ..character.contracts import DeliveryIntent

if TYPE_CHECKING:
    from ..orchestrator.orchestrator import SpeakOrchestrator
    from ..orchestrator.state import StateStore
    from .base import DirectorLLMCaller
    from .agent import DirectorAgentHost


def _is_system_pseudo_user_text(text: str) -> bool:
    body = text.strip()
    if not body:
        return False
    return "用户进入会话" in body or body.startswith("（系统：")


class DirectorCoordinator:
    """合并各导演决策并写入 StateStore；临场内容由编剧提供。"""

    def __init__(
        self,
        *,
        state_store: StateStore,
        snapshot_builder: SnapshotBuilder,
        llm: DirectorLLMCaller,
        orchestrator: SpeakOrchestrator,
        share_wants_fn=None,
        silence_armed_fn=None,
        social_armed_fn=None,
        director_agent: DirectorAgentHost | None = None,
        materials_refresh_fn: Callable[[str, str], None] | None = None,
        screenwriter: Screenwriter | None = None,
        peek_user_pending_fn: Callable[[str], bool] | None = None,
        is_turn_busy_fn: Callable[[str], bool] | None = None,
        is_pushing_fn: Callable[[str], bool] | None = None,
    ) -> None:
        self._state_store = state_store
        self._snapshot_builder = snapshot_builder
        self._llm = llm
        self._outline = OutlineDirector(llm)
        self._user_intent = UserIntentDirector(llm)
        self._turn_delivery = TurnDeliveryDirector(llm)
        self._rhythm_schedule = RhythmScheduleDirector(llm)
        self._module_inject = ModuleInjectDirector(orchestrator, llm=llm)
        self._screenwriter = screenwriter or Screenwriter(llm=llm)
        self._next_turn_guide = NextTurnGuideDirector(orchestrator, llm=llm)
        self._social = SocialArmDirector()
        self._interrupt = InterruptDirector()
        self._share_wants_fn = share_wants_fn
        self._silence_armed_fn = silence_armed_fn
        self._social_armed_fn = social_armed_fn
        self._director_agent = director_agent
        self._materials_refresh_fn = materials_refresh_fn
        self._peek_user_pending_fn = peek_user_pending_fn
        self._is_turn_busy_fn = is_turn_busy_fn
        self._is_pushing_fn = is_pushing_fn

    @property
    def screenwriter(self) -> Screenwriter:
        return self._screenwriter

    def _refresh_materials(self, session_id: str, user_text: str = "") -> None:
        if self._materials_refresh_fn is None:
            return
        self._materials_refresh_fn(session_id, user_text)

    def _compose_materials(self, snapshot) -> dict[str, Any]:
        """组装编剧书写材料；交互记录向角色侧请求。

        备注：导演每次编排只能向角色请求最新交互记录；请求不到（空账本）就先产出，
        不得阻塞等待角色接口，更不得反向占用 turn_busy 挡住用户→角色热路径。
        """
        from ..character.interaction import export_interaction_record

        meta = getattr(getattr(snapshot, "orchestrator", None), "compose_meta", None) or {}
        base = dict(meta) if isinstance(meta, dict) else {}
        sid = str(getattr(snapshot, "session_id", "") or "").strip()
        dialogue_history = ""
        recent_turns: tuple[str, ...] = ()
        silence_log: tuple[str, ...] = ()
        last_user = ""
        last_user_at = 0.0
        last_agent_at = 0.0
        presence_mood = ""
        presence_brief = ""
        fate_desire = None
        fate_tendency = ""
        seeds: list[str] = []
        feedback: list[str] = []
        if sid:
            state = self._state_store.session(sid)
            fb = state.director_cache.get("character_feedback_to_screenwriter")
            if isinstance(fb, list) and fb:
                base["character_feedback_to_screenwriter"] = list(fb)
                for item in fb:
                    if isinstance(item, dict):
                        text = str(item.get("text") or "").strip()
                    else:
                        text = str(item or "").strip()
                    if text:
                        feedback.append(text)
            notes = state.director_cache.get("screenwriter_character_notes")
            if isinstance(notes, list) and notes:
                base["screenwriter_character_notes"] = list(notes)
            raw_seeds = state.director_cache.get("scene_seeds")
            if isinstance(raw_seeds, list):
                seeds = [str(x).strip() for x in raw_seeds if str(x).strip()]
            if state.presence_card.ready:
                presence_mood = state.presence_card.mood
                presence_brief = state.presence_card.brief
            if state.fate_speak_desire is not None:
                fate_desire = int(state.fate_speak_desire)
            if getattr(state.presence_card, "fate_tendency", ""):
                fate_tendency = str(state.presence_card.fate_tendency or "")
            # 向角色侧请求最新交互（含待承接用户原话）；拿不到就空着继续写
            rec = export_interaction_record(
                state,
                dialogue=getattr(snapshot, "dialogue", None),
            )
            dialogue_history = rec.dialogue_history
            recent_turns = rec.recent_turns
            silence_log = rec.silence_log
            last_user = rec.last_user_text
            last_user_at = rec.last_user_speak_at
            last_agent_at = rec.last_agent_speak_at
            base["character_interaction_source"] = rec.source
            base["character_interaction_pending_user"] = rec.pending_user
        clay = build_writing_materials(
            compose_meta=base,
            fate_speak_desire=fate_desire,
            fate_tendency=fate_tendency,
            presence_mood=presence_mood,
            presence_brief=presence_brief,
            dialogue_history=dialogue_history,
            recent_turns=recent_turns,
            silence_log=silence_log,
            last_user_text=last_user,
            last_user_speak_at=last_user_at,
            last_agent_speak_at=last_agent_at,
            scene_seeds=seeds,
            character_feedback=feedback,
        )
        return clay.as_dict()

    @staticmethod
    def _delivery_trace_unit(state) -> AgentDeliveryTraceUnit | None:
        raw_entries = state.director_cache.get("agent_delivery_trace") or []
        if not isinstance(raw_entries, list):
            return None
        entries = tuple(
            {
                "status": str(entry.get("status") or ""),
                "trigger_id": str(entry.get("trigger_id") or ""),
                "text": str(entry.get("text") or ""),
            }
            for entry in raw_entries
            if isinstance(entry, dict)
        )
        return AgentDeliveryTraceUnit(entries=entries) if entries else None

    def _interaction_evidence_for_plot_progress(self, state, snapshot) -> str:
        """轮询用：向角色侧请求交互记录，供导演判断当前剧情卡是否消费完毕。"""
        from ..character.interaction import export_interaction_record

        rec = export_interaction_record(
            state,
            dialogue=getattr(snapshot, "dialogue", None),
        )
        lines = [rec.render_plot_progress_evidence()]
        delivery_trace = self._delivery_trace_unit(state)
        if delivery_trace is not None:
            rendered = delivery_trace.render().strip()
            if rendered:
                lines.append(rendered)
        # 角色交付记账（尚未导演确认的剧情卡）
        delivery_ev = list(state.director_cache.get("plot_unit_delivery_evidence") or [])
        if delivery_ev:
            lines.append("角色交付记账（待导演确认是否消费剧情卡）：")
            for item in delivery_ev[-4:]:
                if not isinstance(item, dict):
                    continue
                lines.append(
                    f"- unit={item.get('plot_unit_id', '—')} "
                    f"intent={str(item.get('intent') or '')[:80]} "
                    f"reason={item.get('reason', '—')}"
                )
        ledger = list(state.director_cache.get("delivery_step_ledger") or [])[-4:]
        if ledger:
            lines.append("交付账本（近几步）：")
            for item in ledger:
                if not isinstance(item, dict):
                    continue
                lines.append(
                    f"- step={item.get('delivery_step_id', '—')} "
                    f"origin={item.get('origin', '—')} "
                    f"trigger={item.get('trigger_id', '—')} "
                    f"silence={item.get('chose_silence', False)} "
                    f"preview={str(item.get('answer_preview') or item.get('answer_fingerprint') or '')[:120]}"
                )
        rhythm = getattr(state, "character_rhythm_schedule", None)
        history = list(getattr(rhythm, "consumption_history", None) or [])[-6:]
        if history:
            lines.append("可执行 unit 已消费（已向角色发请求）：")
            for item in history:
                if not isinstance(item, dict):
                    continue
                lines.append(
                    f"- id={item.get('unit_id', '')} "
                    f"turn={item.get('turn_index', 0)} "
                    f"trigger={item.get('trigger_id', '')} "
                    f"reason={item.get('reason', '—')}"
                )
        plot_flow = getattr(state, "plot_flow", None)
        if plot_flow is not None and getattr(plot_flow, "ready", False):
            flow_text = str(plot_flow.render_for_inject() or "").strip()
            if flow_text:
                lines.append("[场记进展]")
                lines.append(flow_text[:500])
        if len(lines) == 1:
            lines.append("（尚无用户↔角色交互记录；仅依据场记与沉默进展判断。）")
        return "\n".join(lines)

    def _presence_fate_args(self, state) -> dict[str, Any]:
        desire = state.fate_speak_desire
        if desire is None:
            cache = state.director_cache.get("fate_dice") or {}
            if isinstance(cache, dict) and cache.get("roll") is not None:
                desire = int(cache.get("roll"))
        if desire is None:
            return {"speak_desire": None, "fate_tendency": ""}
        desire_i = max(0, min(100, int(desire)))
        return {
            "speak_desire": desire_i,
            "fate_tendency": fate_band_label(desire_i),
        }

    def _build_poll_tick(self, state) -> PollTickUnit:
        now = time.time()
        sec_user = None
        sec_agent = None
        if float(state.last_user_speak_at or 0.0) > 0:
            sec_user = now - float(state.last_user_speak_at)
        if float(state.last_agent_speak_at or 0.0) > 0:
            sec_agent = now - float(state.last_agent_speak_at)
        idle = state.director_cache.get("last_idle_poll") or {}
        note = ""
        if isinstance(idle, dict) and idle:
            note = str(idle.get("note") or "轮询过，无动作").strip()
        return PollTickUnit(
            poll_seq=int(state.poll_seq or 0),
            now_ts=now,
            sec_since_user=sec_user,
            sec_since_agent=sec_agent,
            last_idle_note=note,
        )

    def _poll_should_abort(self, session_id: str, snapshot) -> str | None:
        if self._peek_user_pending(session_id) or bool(snapshot.runtime.user_queue_pending):
            return "user_queue_pending"
        if snapshot.runtime.typing_active and not snapshot.runtime.typing_idle:
            return "typing_active"
        if self._is_pushing(session_id) or snapshot.runtime.push_phase == "pushing":
            return "pushing"
        if self._is_turn_busy(session_id):
            return "turn_busy"
        social = self._social_armed(session_id)
        if social:
            return f"social_armed:{social}"
        return None

    def _arm_frame(
        self,
        session_id: str,
        *,
        user_text: str = "",
        share_wants: bool,
        silence_armed: bool,
        social_armed: str | None,
        poll: bool = False,
        include_silence_log: bool = False,
    ) -> None:
        state = self._state_store.session(session_id)
        preview = self._snapshot_builder.build(session_id, user_text=user_text)
        rhythm = build_rhythm_card(
            typing_active=preview.runtime.typing_active,
            typing_idle=preview.runtime.typing_idle,
            push_phase=preview.runtime.push_phase,
            brew_queue_depth=preview.runtime.brew_queue_depth,
            share_wants=share_wants,
            silence_armed=silence_armed,
            social_armed=social_armed,
            speak_gate=str(state.speak_gate or ""),
            user_queue_pending=preview.runtime.user_queue_pending,
        )
        poll_tick = self._build_poll_tick(state) if poll else None
        user_silence = None
        if include_silence_log and state.silence_log.ready:
            user_silence = UserSilenceUnit(
                entries=tuple(state.silence_log.entries),
                silence_armed=silence_armed,
            )
        inject_director_frame(
            state,
            session_id=session_id,
            user_text=user_text,
            rhythm_card=rhythm,
            host=self._director_agent,
            signal_summary=(
                f"turn={preview.signals.turn_index} "
                f"share={share_wants} silence={silence_armed} social={social_armed or ''}"
            ),
            user_silence=user_silence,
            presence_unit=self._screenwriter.presence_unit_from_state(state),
            plot_flow=self._screenwriter.plot_flow_unit_from_state(state),
            user_stage=self._screenwriter.user_stage_unit_from_state(state),
            scene_event=self._screenwriter.scene_event_unit_from_state(state),
            poll_tick=poll_tick,
            delivery_trace=self._delivery_trace_unit(state),
        )
        self._screenwriter.soft_merge_fate(
            state,
            speak_desire=int(state.fate_speak_desire)
            if state.fate_speak_desire is not None
            else None,
        )
        # soft_merge 后重刷 presence 渲染
        presence_unit = self._screenwriter.presence_unit_from_state(state)
        base = str(state.director_cache.get("frame_prompt") or "").strip()
        extras: list[str] = []
        if user_silence is not None:
            rendered = user_silence.render().strip()
            if rendered:
                extras.append(rendered)
                state.director_cache["user_silence"] = rendered
        if presence_unit is not None:
            rendered = presence_unit.render().strip()
            if rendered:
                extras.append(rendered)
                state.director_cache["presence_unit"] = rendered
        plot_unit = self._screenwriter.plot_flow_unit_from_state(state)
        if plot_unit is not None:
            rendered = plot_unit.render().strip()
            if rendered:
                extras.append(rendered)
                state.director_cache["plot_flow_unit"] = rendered
                state.director_cache["plot_flow"] = state.plot_flow.snapshot()
                state.director_cache["plot_arc"] = state.plot_arc.snapshot()
        iu = self._screenwriter.interaction_unit_from_state(state)
        if iu is not None:
            rendered = iu.render().strip()
            if rendered:
                extras.append(rendered)
                state.director_cache["interaction_unit"] = rendered
        stage = self._screenwriter.user_stage_unit_from_state(state)
        if stage is not None:
            rendered = stage.render().strip()
            if rendered:
                extras.append(rendered)
                state.director_cache["user_stage"] = rendered
        event = self._screenwriter.scene_event_unit_from_state(state)
        if event is not None:
            rendered = event.render().strip()
            if rendered:
                extras.append(rendered)
                state.director_cache["scene_event"] = rendered
        if poll_tick is not None:
            rendered = poll_tick.render().strip()
            if rendered:
                extras.append(rendered)
                state.director_cache["poll_tick"] = rendered
        delivery_trace = self._delivery_trace_unit(state)
        if delivery_trace is not None:
            rendered = delivery_trace.render().strip()
            if rendered:
                extras.append(rendered)
                state.director_cache["agent_delivery_trace_block"] = rendered
        schedule_text = state.character_rhythm_schedule.render_for_director().strip()
        if schedule_text:
            extras.append(schedule_text)
            state.director_cache["character_rhythm_schedule"] = (
                state.character_rhythm_schedule.snapshot()
            )
        feedback = state.director_cache.get("character_feedback_to_director") or []
        if isinstance(feedback, list) and feedback:
            lines = []
            for item in feedback[-6:]:
                if isinstance(item, dict):
                    text = str(item.get("text") or "").strip()
                else:
                    text = str(item or "").strip()
                if text:
                    lines.append(f"- {text[:160]}")
            if lines:
                block = "[角色反馈｜可拒绝你的嘱托/节奏]\n" + "\n".join(lines)
                extras.append(block)
                state.director_cache["character_feedback_block"] = block
        if extras:
            # inject 已写过一遍；以最新 soft_merge 结果覆盖
            rhythm_block = ""
            if base:
                # 保留命运骰/节奏头（第一段），其后用 extras 替换
                rhythm_block = base.split("\n\n", 1)[0].strip()
            state.director_cache["frame_prompt"] = "\n\n".join(
                [p for p in [rhythm_block, *extras] if p]
            )

    def on_user_input(
        self,
        session_id: str,
        user_text: str,
        *,
        turn_index: int,
        phase: str,
    ) -> dict[str, Any]:
        phase_s = str(phase or "").strip().lower()
        if phase_s == "fast":
            return self.on_user_input_fast(
                session_id,
                user_text,
                turn_index=turn_index,
            )
        if phase_s == "slow":
            return self.on_user_input_slow(
                session_id,
                user_text,
                turn_index=turn_index,
            )
        raise ValueError(f"on_user_input phase must be fast|slow, got {phase!r}")

    def on_user_input_fast(
        self,
        session_id: str,
        user_text: str,
        *,
        turn_index: int,
    ) -> dict[str, Any]:
        """首响应帧：立刻清静默、写 fallback delivery；不跑完整导演树，不催生角色。"""
        from ..character.interaction import note_pending_user

        state = self._state_store.session(session_id)
        state.director_context_frozen = False
        text = user_text.strip()
        if text and not _is_system_pseudo_user_text(text):
            note_pending_user(state, user_text=text)
            state.silence_log.clear()
            state.director_cache.pop("user_silence", None)
            state.notes.append("ingress: silence_log cleared")
            state.narrative_card.interaction_mode = "user_utterance"
            state.narrative_card.user_activity = "正在与你文字往来"
        self._refresh_materials(session_id, user_text)
        share_wants = self._share_wants(session_id)
        silence_armed = self._silence_armed(session_id)
        social_armed = self._social_armed(session_id)
        snapshot_pre = self._snapshot_builder.build(session_id, user_text=user_text)
        materials = self._compose_materials(snapshot_pre)
        if needs_narrative_reinit(state):
            clear_narrative_for_reinit(state)
            state.notes.append("ingress: narrative_reinit after speak_dormant/idle")
        if not state.presence_card.ready or not state.plot_arc.ready:
            self._screenwriter.init_presence(
                state,
                session_id=session_id,
                user_text=user_text,
                turn_index=turn_index,
                materials=materials,
                background_agent=True,
            )
        self._arm_frame(
            session_id,
            user_text=user_text,
            share_wants=share_wants,
            silence_armed=silence_armed,
            social_armed=social_armed,
            poll=False,
            include_silence_log=False,
        )
        snapshot = self._snapshot_builder.build(session_id, user_text=user_text)
        force_social_speak = social_armed in ("enter_greeting", "silence_break")
        force_user_speak = bool(user_text.strip())
        force_speak = force_social_speak or force_user_speak
        state.pending_delivery_plan = fallback_delivery_plan(
            snapshot,
            user_text=user_text,
        )
        state.speak_gate = "speak" if force_speak else state.speak_gate
        ingress_seq = int(state.director_cache.get("ingress_seq") or 0) + 1
        state.director_cache["ingress_seq"] = ingress_seq
        state.director_cache["ingress_phase"] = "fast"
        state.notes.append(f"ingress:fast turn={turn_index} seq={ingress_seq}")
        # 用户首响由 CharacterRuntime(origin=user) 直回；清掉导演主动 handoff 防双推
        state.pending_character_handoff = None
        idle = self._state_store.poll_frame_manager(session_id, "idle")
        idle.reset_decay()
        append = self._state_store.poll_frame_manager(session_id, "append")
        append.reset_decay()
        return {
            "ingress_phase": "fast",
            "ingress_seq": ingress_seq,
            "speak_gate": state.speak_gate,
            "has_delivery_plan": True,
        }

    def sync_before_character_reply(
        self,
        session_id: str,
        user_text: str,
        *,
        turn_index: int,
    ) -> dict[str, Any]:
        """可选慢路径：角色开口前问编剧是否改场记。

        用户热路径故意不调用本方法（避免拖交互）；交互记录仍经由角色侧
        export_interaction_record 同步给编剧/导演。
        """
        state = self._state_store.session(session_id)
        text = str(user_text or "").strip()
        self._refresh_materials(session_id, text)
        snapshot_pre = self._snapshot_builder.build(session_id, user_text=text)
        materials = self._compose_materials(snapshot_pre)
        sw_out = self._screenwriter.sync_on_user_ingress(
            state,
            session_id=session_id,
            user_text=text,
            turn_index=turn_index,
            materials=materials,
        )
        # 导演侧：刷新材料与节奏表台本对齐；不向角色注入节奏嘱托/预测
        rhythm = getattr(state, "character_rhythm_schedule", None)
        if rhythm is not None and hasattr(rhythm, "sync_scripts_from_plot_arc"):
            changed = int(rhythm.sync_scripts_from_plot_arc(state.plot_arc) or 0)
            if changed:
                state.director_cache["character_rhythm_schedule"] = rhythm.snapshot()
                state.notes.append(f"director:sync_scripts changed={changed}")
        state.notes.append("director:sync_before_character")
        return {
            "screenwriter_action": str(
                (sw_out.payload or {}).get("action") if sw_out is not None else ""
            ),
            "screenwriter_reason": str(getattr(sw_out, "reason", "") or ""),
        }

    def maybe_wake_narrative(
        self,
        session_id: str,
        user_text: str = "",
        *,
        turn_index: int = 0,
    ) -> dict[str, Any]:
        """满 K 轮/unit 到点：编剧对齐；导演仅在剧情 unit 变动时醒。开场必醒一次。"""
        state = self._state_store.session(session_id)
        if not should_wake_narrative(state) and not director_needs_init(state):
            state.notes.append(
                "narrative:wake_skip "
                f"exchanges={int(getattr(state, 'interaction_exchange_count', 0) or 0)} "
                f"total={state.plot_arc.total_unit_count() if state.plot_arc.ready else 0}"
            )
            return {
                "woken": False,
                "director_woken": False,
                "reason": "threshold_not_met",
                "exchanges": int(getattr(state, "interaction_exchange_count", 0) or 0),
            }
        needs_init = director_needs_init(state)
        text = str(user_text or "").strip() or str(state.last_real_user_text or "").strip()
        if self._screenwriter is not None:
            snapshot = self._snapshot_builder.build(session_id, user_text=text)
            materials = self._compose_materials(snapshot)
            history = str(
                (materials.get("dialogue_history") if isinstance(materials, dict) else "")
                or snapshot.dialogue.working_memory
                or ""
            ).strip()
            self._screenwriter.maybe_align_after_exchange(
                state,
                session_id=session_id,
                turn_index=turn_index,
                materials=materials,
                dialogue_history=history,
                async_write=True,
            )
        outputs = self._maybe_run_director_on_unit_change(
            session_id,
            text,
            turn_index=turn_index,
        )
        director_woken = outputs is not None
        reason = "units_unchanged"
        if director_woken:
            reason = "init" if needs_init else "plot_units_changed"
        return {
            "woken": director_woken,
            "director_woken": director_woken,
            "reason": reason,
            "outputs": outputs or {},
        }

    def ensure_director_init(
        self,
        session_id: str,
        user_text: str = "",
        *,
        turn_index: int = 0,
    ) -> dict[str, Any]:
        """开场：剧情弧就绪且导演从未对齐时，醒一次导演树。"""
        state = self._state_store.session(session_id)
        if not director_needs_init(state):
            return {"woken": False, "reason": "already_aligned"}
        if bool(state.director_cache.get("director_init_scheduled")):
            return {"woken": False, "reason": "init_scheduled"}
        state.director_cache["director_init_scheduled"] = True
        text = str(user_text or "").strip() or str(state.last_real_user_text or "").strip()
        outputs = self._run_director_slow_tree(
            session_id,
            text,
            turn_index=turn_index,
        )
        mark_director_plot_aligned(state)
        state.director_cache.pop("director_init_scheduled", None)
        state.notes.append("director:wake_on_init")
        return {"woken": True, "reason": "init", "outputs": outputs}

    def on_user_input_slow(
        self,
        session_id: str,
        user_text: str,
        *,
        turn_index: int,
    ) -> dict[str, Any]:
        """用户入站不再每次唤醒；只在满 K 轮/unit 门槛时检查，unit 变动才醒导演。"""
        return self.maybe_wake_narrative(
            session_id,
            user_text,
            turn_index=turn_index,
        )

    def _maybe_run_director_on_unit_change(
        self,
        session_id: str,
        user_text: str,
        *,
        turn_index: int,
    ) -> dict[str, Any] | None:
        """到点检查之后调用：剧情 unit 相对上次导演对齐有变动才跑导演树。"""
        state = self._state_store.session(session_id)
        if bool(state.director_cache.get("director_init_scheduled")):
            return None
        if not plot_units_changed_since_director(state):
            state.notes.append(
                "director:wake_skip units_unchanged "
                f"exchanges={int(getattr(state, 'interaction_exchange_count', 0) or 0)}"
            )
            return None
        outputs = self._run_director_slow_tree(
            session_id,
            user_text,
            turn_index=turn_index,
        )
        mark_director_plot_aligned(state)
        state.notes.append("director:wake_on_plot_units")
        return outputs

    def _run_director_slow_tree(
        self,
        session_id: str,
        user_text: str,
        *,
        turn_index: int,
    ) -> dict[str, Any]:
        """完整导演编排：只服务下一轮；不催生本拍角色回复。"""
        state = self._state_store.session(session_id)
        ingress_seq = int(state.director_cache.get("ingress_seq") or 0)
        active_guide = promote_pending_next_turn_guide(state)
        share_wants = self._share_wants(session_id)
        silence_armed = self._silence_armed(session_id)
        social_armed = self._social_armed(session_id)
        snapshot = self._snapshot_builder.build(
            session_id,
            user_text=user_text,
        )

        with ThreadPoolExecutor(max_workers=4, thread_name_prefix="speak-director-ingress") as pool:
            outline_future = pool.submit(
                self._outline.run,
                snapshot,
                user_text=user_text,
            )
            intent_future = pool.submit(
                self._user_intent.run,
                snapshot,
                user_text=user_text,
            )
            delivery_future = pool.submit(
                self._turn_delivery.run,
                snapshot,
                user_text=user_text,
            )
            guide_future = pool.submit(
                self._next_turn_guide.run,
                snapshot,
                user_text=user_text,
            )
            outline_out = outline_future.result()
            intent_out = intent_future.result()
            delivery_out = delivery_future.result()
            guide_out = guide_future.result()
        # 若期间又有新的用户入站，拦住并丢弃过期 slow，交由新一轮决策
        if int(state.director_cache.get("ingress_seq") or 0) != ingress_seq:
            state.notes.append(
                f"ingress:slow_stale_redecide seq={ingress_seq} "
                f"current={state.director_cache.get('ingress_seq')}"
            )
            return {
                "ingress_phase": "slow_stale",
                "ingress_seq": ingress_seq,
                "redecide": True,
            }
        apply_next_turn_guide_output(state, guide_out)
        module_out = self._module_inject.run(
            snapshot,
            user_text=user_text,
            social_armed=social_armed,
            silence_armed=silence_armed,
            share_wants=share_wants,
        )
        # 记忆/分享调度已迁至编剧→剧情流；导演席不再挑选或盲注
        social_out = self._social.run(
            snapshot,
            silence_armed=silence_armed,
            social_armed=social_armed,
        )

        apply_outline_output(state, outline_out)
        apply_user_intent_output(state, intent_out)
        # slow 只更新 pending plan 供下一拍；不覆盖当前已在途的用户首响
        apply_turn_delivery_output(state, delivery_out, pending=True)

        materials = self._compose_materials(snapshot)
        history = str(
            (materials.get("dialogue_history") if isinstance(materials, dict) else "")
            or snapshot.dialogue.working_memory
            or ""
        ).strip()
        iu = self._screenwriter.interaction_unit_from_state(state)
        evidence = self._interaction_evidence_for_plot_progress(state, snapshot)
        schedule_out = self._rhythm_schedule.run(
            snapshot,
            current=state.character_rhythm_schedule,
            user_text=user_text,
            dialogue_history=history,
            force_open_now=False,
            poll=False,
            interaction_unit_brief=iu.render() if iu is not None else "",
            interaction_evidence=evidence,
            plot_arc=state.plot_arc,
            agenda=getattr(state, "speak_agenda", None),
        )
        apply_rhythm_schedule_output(state, schedule_out)
        gate_out = DirectorOutput(
            director="speak_gate",
            payload={
                "action": state.speak_gate,
                "reason": "rhythm_schedule",
            },
            reason="rhythm_schedule",
        )

        outputs = {
            outline_out.director: outline_out.snapshot(),
            intent_out.director: intent_out.snapshot(),
            delivery_out.director: delivery_out.snapshot(),
            module_out.director: module_out.snapshot(),
            social_out.director: social_out.snapshot(),
            "screenwriter": dict(state.director_cache.get("screenwriter") or {}),
            "plot_flow": state.plot_flow.snapshot() if state.plot_flow is not None else {},
            guide_out.director: guide_out.snapshot(),
            schedule_out.director: schedule_out.snapshot(),
            gate_out.director: gate_out.snapshot(),
        }
        state.director_cache = {**state.director_cache, **outputs}
        if active_guide is not None:
            state.director_cache["active_next_turn_guide"] = active_guide.snapshot()
        if state.presence_card.ready:
            state.director_cache["presence_card_state"] = state.presence_card.snapshot()
        if state.narrative_card.ready:
            state.director_cache["narrative_card_state"] = state.narrative_card.snapshot()
        state.director_cache["ingress_phase"] = "slow_done"
        state.notes.append(f"ingress:slow turn={turn_index} seq={ingress_seq}")
        # 用户首响已发生：只排后续 ladder，不在本拍立刻 handoff
        state.pending_character_handoff = None
        get_prompt_trace().emit_event(
            session_id,
            label="director_ingress_outputs",
            turn_index=turn_index,
            payload={
                "user_text": user_text,
                "share_wants": share_wants,
                "silence_armed": silence_armed,
                "social_armed": social_armed,
                "speak_gate": state.speak_gate,
                "ingress_seq": ingress_seq,
                "ingress_phase": "slow",
                "character_rhythm_schedule": state.character_rhythm_schedule.snapshot(),
                "active_next_turn_guide": state.active_next_turn_guide,
                "pending_next_turn_guide": state.pending_next_turn_guide,
                "presence_card": state.presence_card.snapshot(),
                "narrative_card": state.narrative_card.snapshot(),
                "outputs": outputs,
            },
        )
        self._arm_poll(session_id, "idle")
        return outputs

    def on_poll_tick(self, session_id: str, *, trigger: str) -> dict[str, Any]:
        snapshot = self._snapshot_builder.build(session_id)
        state = self._state_store.session(session_id)
        if trigger == "interrupt" or snapshot.runtime.push_phase == "pushing":
            interrupt_out = self._interrupt.run(snapshot)
            state.director_cache["interrupt"] = interrupt_out.snapshot()
            if interrupt_out.payload.get("cancel_unsent"):
                if state.pending_delivery_plan is not None:
                    state.pending_delivery_plan = None
                if state.delivery_plan is not None:
                    state.delivery_plan = None
            get_prompt_trace().emit_event(
                session_id,
                label="director_poll_interrupt",
                turn_index=snapshot.signals.turn_index,
                payload={
                    "trigger": trigger,
                    "push_phase": snapshot.runtime.push_phase,
                    "interrupt": interrupt_out.snapshot(),
                },
            )
            self._arm_poll(session_id, "idle")
            return {"interrupt": interrupt_out.snapshot()}

        abort_reason = self._poll_should_abort(session_id, snapshot)
        if abort_reason:
            state.director_cache["last_idle_poll"] = {
                "note": f"轮询早退：{abort_reason}",
                "trigger": trigger,
                "poll_seq": state.poll_seq,
                "at": time.time(),
            }
            state.director_cache["poll"] = {
                "trigger": trigger,
                "aborted": True,
                "reason": abort_reason,
            }
            state.notes.append(f"poll: abort {abort_reason}")
            get_prompt_trace().emit_event(
                session_id,
                label="director_poll_aborted",
                turn_index=snapshot.signals.turn_index,
                payload=state.director_cache["poll"],
            )
            self._arm_poll(session_id, "idle")
            return state.director_cache["poll"]

        share_wants = self._share_wants(session_id)
        social_armed = self._social_armed(session_id)
        silence_armed = self._silence_armed(session_id)

        state.director_context_frozen = False
        # Speak 独立：超时无交互 → 静默停主动，等下次接入再初始化
        if should_enter_dormant(state):
            payload = enter_speak_dormant(state, reason="idle_30m")
            state.director_cache["poll"] = {
                "trigger": trigger,
                "dormant": True,
                **payload,
            }
            get_prompt_trace().emit_event(
                session_id,
                label="speak_dormant",
                turn_index=snapshot.signals.turn_index,
                payload=state.director_cache["poll"],
            )
            return state.director_cache["poll"]
        if state.speak_dormant:
            state.director_cache["poll"] = {
                "trigger": trigger,
                "aborted": True,
                "reason": "speak_dormant",
            }
            return state.director_cache["poll"]

        # 每拍无输入：累加沉默日志（零 LLM）+ 递增 poll_seq（编剧按 K 拍续写）
        # 用户刚发过言：宽限期内禁止立刻重建静默事实，避免 mode 又掉回 user_silent
        recent_user_speak = False
        last_speak = float(state.last_user_speak_at or 0.0)
        if last_speak > 0.0 and (time.time() - last_speak) < 30.0:
            recent_user_speak = True
        if recent_user_speak:
            state.notes.append(
                "poll: skip silence_log append "
                f"(user spoke {time.time() - last_speak:.1f}s ago)"
            )
        else:
            state.silence_log.append_now()
        state.poll_seq = int(state.poll_seq or 0) + 1
        if state.plot_arc.ready:
            state.plot_arc.note_poll(poll_seq=state.poll_seq)
        state.notes.append(
            f"poll: silence_log append count={len(state.silence_log.entries)} seq={state.poll_seq}"
        )

        fuel = str(state.last_real_user_text or "").strip() or "silence"
        self._refresh_materials(session_id, fuel)
        snapshot = self._snapshot_builder.build(session_id)
        materials = self._compose_materials(snapshot)
        history = str(
            (materials.get("dialogue_history") if isinstance(materials, dict) else "")
            or snapshot.dialogue.working_memory
            or ""
        ).strip()

        if not state.presence_card.ready or not state.plot_arc.ready:
            self._screenwriter.init_presence(
                state,
                session_id=session_id,
                user_text=fuel,
                turn_index=snapshot.signals.turn_index,
                materials=materials,
                background_agent=True,
            )
        # 满 K 轮/unit 到点，或导演尚未初始化：先编剧对齐，再按 unit 是否变动决定导演
        due = should_wake_narrative(state) or director_needs_init(state)
        self._screenwriter.tick_on_poll(
            state,
            session_id=session_id,
            turn_index=snapshot.signals.turn_index,
            materials=materials,
            dialogue_history=history,
            async_write=True,
        )
        if due:
            self._maybe_run_director_on_unit_change(
                session_id,
                fuel,
                turn_index=snapshot.signals.turn_index,
            )
        # 角色后台预约轮询：独立计数器，不复用导演唤醒
        from agent.soul.speak.responders.request_driven.character.book_poll import (
            maybe_poll_character_book,
        )

        book_llm = self._llm
        maybe_poll_character_book(
            book_llm,
            state,
            session_id=session_id,
            turn_index=int(snapshot.signals.turn_index or 0),
        )

        self._arm_frame(
            session_id,
            user_text="",
            share_wants=share_wants,
            silence_armed=silence_armed,
            social_armed=social_armed,
            poll=True,
            include_silence_log=True,
        )
        snapshot = self._snapshot_builder.build(session_id)

        # 节奏扩充：活队列不足才补仓；有角色反馈则修订。不问完备。
        iu = self._screenwriter.interaction_unit_from_state(state)
        iu_brief = iu.render() if iu is not None else ""
        evidence = self._interaction_evidence_for_plot_progress(state, snapshot)
        feedback_block = str(state.director_cache.get("character_feedback_block") or "").strip()
        pending_fb = list(state.director_cache.get("character_feedback_to_director") or [])
        revise = bool(pending_fb)
        schedule_out = self._rhythm_schedule.run(
            snapshot,
            current=state.character_rhythm_schedule,
            user_text="",
            dialogue_history=history,
            force_open_now=False,
            poll=True,
            interaction_unit_brief=iu_brief,
            interaction_evidence=evidence,
            plot_arc=state.plot_arc,
            agenda=getattr(state, "speak_agenda", None),
            character_feedback=feedback_block if revise else "",
            revise=revise,
        )
        apply_rhythm_schedule_output(state, schedule_out)
        if revise:
            state.director_cache["character_feedback_to_director"] = []
            state.director_cache.pop("character_feedback_block", None)
            state.notes.append("poll: character_feedback_consumed")
        self._maybe_consume_pair_by_window(state)
        state.director_cache["plot_progress_check"] = {
            "complete_check_retired": True,
            "active_unit_id": (
                state.plot_arc.active_unit().unit_id
                if state.plot_arc.ready and state.plot_arc.active_unit() is not None
                else ""
            ),
            "poll_seq": int(getattr(state, "poll_seq", 0) or 0),
            "agenda": (
                state.speak_agenda.snapshot()
                if getattr(state, "speak_agenda", None) is not None
                else {}
            ),
        }

        # 记忆/分享已由编剧写入剧情流；轮询不再跑 DynamicLayerDirector
        state.director_context_frozen = False
        state.director_cache.pop("dynamic_layer", None)
        state.director_cache["rhythm_schedule"] = schedule_out.snapshot()
        state.director_cache["plot_flow"] = (
            state.plot_flow.snapshot() if state.plot_flow is not None else {}
        )
        if state.presence_card.ready:
            state.director_cache["presence_card_state"] = state.presence_card.snapshot()
        if state.narrative_card.ready:
            state.director_cache["narrative_card_state"] = state.narrative_card.snapshot()
        state.director_cache["silence_log"] = state.silence_log.render()
        if getattr(state, "speak_agenda", None) is not None:
            state.director_cache["speak_agenda"] = state.speak_agenda.snapshot()

        delivery_out = self._turn_delivery.run(snapshot)
        apply_turn_delivery_output(state, delivery_out, pending=True)
        has_plan = state.pending_delivery_plan is not None and not state.pending_delivery_plan.is_empty

        gate_out = DirectorOutput(
            director="speak_gate",
            payload={
                "action": state.speak_gate,
                "reason": "rhythm_schedule",
            },
            reason="rhythm_schedule",
        )
        action = str(state.speak_gate or "hold").strip().lower()

        if action in ("speak", "brew") and not has_plan:
            state.pending_delivery_plan = fallback_delivery_plan_for_silence(snapshot)
            has_plan = (
                state.pending_delivery_plan is not None
                and not state.pending_delivery_plan.is_empty
            )
            state.notes.append("poll: silence fallback delivery")

        # handoff 前再 peek：若已有真实输入则放弃本拍
        if self._peek_user_pending(session_id) or bool(
            self._snapshot_builder.build(session_id).runtime.user_queue_pending
        ):
            state.pending_delivery_plan = None
            state.pending_character_handoff = None
            state.speak_gate = "hold"
            state.director_cache["last_idle_poll"] = {
                "note": "轮询放弃 handoff：用户队列已有输入",
                "trigger": trigger,
                "poll_seq": state.poll_seq,
                "at": time.time(),
            }
            state.director_cache["poll"] = {
                "trigger": trigger,
                "aborted": True,
                "reason": "user_pending_before_handoff",
            }
            self._arm_poll(session_id, "idle")
            return state.director_cache["poll"]

        # 角色主动开口只认 speak_agenda 到期；poll_finish 不再自动交角色
        state.director_cache["poll"] = {
            "trigger": trigger,
            "terminated": False,
            "silence_log_count": len(state.silence_log.entries),
            "delivery": delivery_out.snapshot(),
            "gate": gate_out.snapshot(),
            "rhythm_schedule": schedule_out.snapshot(),
            "plot_flow": state.plot_flow.snapshot() if state.plot_flow is not None else {},
            "character_handoff": state.pending_character_handoff,
            "character_rhythm_schedule": state.character_rhythm_schedule.snapshot(),
            "note": "poll_finish_no_auto_handoff",
        }
        get_prompt_trace().emit_event(
            session_id,
            label="director_poll_outputs",
            turn_index=snapshot.signals.turn_index,
            payload={
                "trigger": trigger,
                "speak_gate": state.speak_gate,
                "has_delivery_plan": has_plan,
                "poll": state.director_cache["poll"],
            },
        )
        if has_plan and action in ("speak", "brew"):
            state.director_cache.pop("last_idle_poll", None)
            # 开口交付中：不在此升阶；等 on_delivery_done 再约下一拍
            return state.director_cache["poll"]
        state.pending_delivery_plan = None
        if action not in ("speak", "brew"):
            if state.pending_character_handoff is None:
                state.director_cache["last_idle_poll"] = {
                    "note": f"轮询过，gate={action}，无动作",
                    "trigger": trigger,
                    "poll_seq": state.poll_seq,
                    "at": time.time(),
                }
        self._arm_poll(session_id, "idle")
        return state.director_cache.get("poll", {})

    def dispatch_due_handoff(self, session_id: str) -> dict[str, Any] | None:
        """到期议程条目走快速交接；只认 speak_agenda due，不再因 window_due 拉角色。"""
        state = self._state_store.session(session_id)
        if state.pending_character_handoff is not None:
            return dict(state.pending_character_handoff)
        agenda = getattr(state, "speak_agenda", None)
        due_entry = agenda.peek_due() if agenda is not None else None
        if due_entry is None:
            return None
        if not bool(state.director_cache.get("narrative_opening_ready")):
            state.notes.append("rhythm_schedule: hold_handoff_wait_opening")
            return None
        self._mark_schedule_speak_handoff(
            state,
            user_text="",
            turn_index=int(self._snapshot_builder.build(session_id).signals.turn_index or 0),
            reason="agenda_due",
            agenda_entry=due_entry,
        )
        handoff = state.pending_character_handoff
        return dict(handoff) if isinstance(handoff, dict) and handoff else None

    def on_character_feedback(self, session_id: str) -> dict[str, Any]:
        """角色 note_director 异步唤醒：修订节奏扩充与时间轴。"""
        state = self._state_store.session(session_id)
        feedback = state.director_cache.get("character_feedback_to_director") or []
        if not isinstance(feedback, list) or not feedback:
            return {"woke": False}
        lines: list[str] = []
        for item in feedback[-6:]:
            if isinstance(item, dict):
                text = str(item.get("text") or "").strip()
            else:
                text = str(item or "").strip()
            if text:
                lines.append(f"- {text[:160]}")
        if not lines:
            return {"woke": False}
        block = "[角色反馈｜修订节奏与时间轴]\n" + "\n".join(lines)
        state.director_cache["character_feedback_block"] = block
        snapshot = self._snapshot_builder.build(session_id)
        materials = self._compose_materials(snapshot)
        history = str(
            (materials.get("dialogue_history") if isinstance(materials, dict) else "")
            or snapshot.dialogue.working_memory
            or ""
        ).strip()
        iu = self._screenwriter.interaction_unit_from_state(state)
        schedule_out = self._rhythm_schedule.run(
            snapshot,
            current=state.character_rhythm_schedule,
            user_text="",
            dialogue_history=history,
            poll=False,
            interaction_unit_brief=iu.render() if iu is not None else "",
            plot_arc=state.plot_arc,
            agenda=getattr(state, "speak_agenda", None),
            character_feedback=block,
            revise=True,
        )
        apply_rhythm_schedule_output(state, schedule_out)
        state.director_cache["character_feedback_to_director"] = []
        state.director_cache.pop("character_feedback_block", None)
        state.notes.append("director:character_feedback_wake")
        return {"woke": True, "action": schedule_out.payload.get("action")}

    def _consume_active_pair(self, state, *, reason: str) -> bool:
        """同步消费当前剧情+节奏对。"""
        if not state.plot_arc.ready:
            return False
        active = state.plot_arc.active_unit()
        if active is None:
            return False
        unit_id = str(active.unit_id or "").strip()
        rhythm = state.character_rhythm_schedule.unit_for_plot(unit_id)
        state.director_cache["pending_unit_complete"] = {
            "reason": reason,
            "poll_seq": int(getattr(state, "poll_seq", 0) or 0),
            "unit_id": unit_id,
        }
        self._apply_pending_unit_complete(state)
        if rhythm is not None and rhythm.status in ("pending", "reserved"):
            state.character_rhythm_schedule.mark_consumed(
                rhythm.unit_id,
                trigger_id=reason,
                plot_fingerprint=unit_id,
            )
            state.director_cache["character_rhythm_schedule"] = (
                state.character_rhythm_schedule.snapshot()
            )
        state.notes.append(f"pair_consume: {reason} plot={unit_id}")
        return True

    def _maybe_consume_pair_by_window(self, state) -> None:
        """窗口结束：同步消费剧情+节奏对。"""
        if not state.plot_arc.ready:
            return
        active = state.plot_arc.active_unit()
        if active is None:
            return
        rhythm = state.character_rhythm_schedule.unit_for_plot(active.unit_id)
        if rhythm is None or rhythm.window_end is None:
            return
        if float(rhythm.window_end) > time.time():
            return
        self._consume_active_pair(state, reason="window_end")

    def _maybe_consume_pair_on_next_plot(
        self,
        state,
        *,
        next_plot_unit_id: str,
        reason: str,
    ) -> None:
        """预约绑到下一对剧情卡时：先消费当前对。"""
        nxt = str(next_plot_unit_id or "").strip()
        if not nxt or not state.plot_arc.ready:
            return
        active = state.plot_arc.active_unit()
        if active is None:
            return
        current_id = str(active.unit_id or "").strip()
        if not current_id or current_id == nxt:
            return
        self._consume_active_pair(state, reason=reason)

    def on_delivery_done(self, session_id: str) -> None:
        state = self._state_store.session(session_id)
        state.delivery_plan = None
        state.pending_delivery_plan = None
        # 不 reset_decay：延续 5→15→30 阶梯；用户入站才清零
        self._arm_poll(session_id, "idle")

    def take_character_handoff(self, session_id: str) -> dict[str, Any] | None:
        state = self._state_store.session(session_id)
        handoff = state.pending_character_handoff
        state.pending_character_handoff = None
        if not isinstance(handoff, dict) or not handoff:
            return None
        executable_unit_id = str(handoff.get("executable_unit_id") or "").strip()
        if executable_unit_id:
            reserved = state.character_rhythm_schedule.mark_reserved(executable_unit_id)
            if reserved is None:
                return None
            state.director_cache["character_rhythm_schedule"] = (
                state.character_rhythm_schedule.snapshot()
            )
            state.notes.append(
                "rhythm_schedule: reserved "
                f"exec_unit={executable_unit_id} trigger={handoff.get('trigger_id', '')}"
            )
        agenda_entry_id = str(handoff.get("agenda_entry_id") or "").strip()
        agenda = getattr(state, "speak_agenda", None)
        if agenda is not None and agenda_entry_id:
            agenda.mark_fired(agenda_entry_id)
            state.director_cache["speak_agenda"] = agenda.snapshot()
        return dict(handoff)

    def peek_character_handoff(self, session_id: str) -> dict[str, Any] | None:
        state = self._state_store.session(session_id)
        handoff = state.pending_character_handoff
        if not isinstance(handoff, dict) or not handoff:
            return None
        return dict(handoff)

    def _apply_pending_unit_complete(self, state) -> None:
        """导演确认 → 编剧唯一落账（角色 delivery 不得直推进 plot_arc）。"""
        pending = state.director_cache.pop("pending_unit_complete", None)
        if not isinstance(pending, dict) or not pending:
            return
        sid = str(getattr(state, "session_id", "") or "").strip()
        unit_id = str(pending.get("unit_id") or "").strip()
        if not unit_id:
            active = (
                state.plot_arc.active_unit()
                if getattr(state, "plot_arc", None) is not None and state.plot_arc.ready
                else None
            )
            unit_id = str(getattr(active, "unit_id", "") or "").strip() if active else ""
        self._screenwriter.confirm_interaction_unit_complete(
            state,
            poll_seq=int(pending.get("poll_seq") or getattr(state, "poll_seq", 0) or 0),
            reason=str(pending.get("reason") or "").strip(),
            session_id=sid,
            unit_id=unit_id,
        )

    def _mark_schedule_speak_handoff(
        self,
        state,
        *,
        user_text: str,
        turn_index: int,
        reason: str,
        agenda_entry=None,
    ) -> None:
        """议程/窗口到期 → 发出 booked/director CharacterReplyRequest。

        导演不写台词。开口权在角色决策；此处只交一对剧情+节奏卡。
        """
        del user_text
        schedule: CharacterRhythmSchedule = state.character_rhythm_schedule
        schedule.sync_scripts_from_plot_arc(state.plot_arc)
        if any(e.status == "reserved" for e in schedule.executable_units):
            state.pending_character_handoff = None
            state.notes.append(
                "rhythm_schedule: skip_handoff_already_reserved "
                f"reason={reason}"
            )
            return

        plot_id = ""
        agenda_id = ""
        origin = "booked"
        if agenda_entry is not None:
            plot_id = str(getattr(agenda_entry, "plot_unit_id", "") or "").strip()
            agenda_id = str(getattr(agenda_entry, "entry_id", "") or "").strip()
            if str(getattr(agenda_entry, "source", "") or "") == "director":
                origin = "director"
        entry = None
        if plot_id:
            entry = schedule.unit_for_plot(plot_id)
        if entry is None:
            due = schedule.due_units()
            if due:
                entry = min(
                    due,
                    key=lambda e: float(
                        e.window_start if e.window_start is not None else e.open_at
                    ),
                )
            elif schedule.pending_units():
                entry = min(
                    schedule.pending_units(),
                    key=lambda e: float(
                        e.window_start if e.window_start is not None else e.open_at
                    ),
                )
        if entry is None and agenda_entry is None:
            state.pending_character_handoff = None
            return

        exec_id = entry.unit_id if entry is not None else f"agenda-{agenda_id or 'due'}"
        plot_ids = entry.plot_unit_ids if entry is not None else ((plot_id,) if plot_id else ())
        # 同对可多次开口；翻卡只走窗口结束 / 预约绑下一对，不再用指纹闸拦 handoff。
        if agenda_entry is not None and plot_id:
            self._maybe_consume_pair_on_next_plot(
                state,
                next_plot_unit_id=plot_id,
                reason="agenda_next_plot",
            )

        state.speak_gate = "speak"
        if state.pending_delivery_plan is None or state.pending_delivery_plan.is_empty:
            state.pending_delivery_plan = build_delivery_plan(
                segments=[
                    ReplySegment(text="…", wait_ms=120, continuity="finish"),
                ],
                continuity="finish",
                plan_id=f"schedule-{exec_id}",
                turn_index=int(turn_index or 0),
            )
        request = build_character_reply_request(
            origin=origin,
            session_id=str(getattr(state, "session_id", "") or ""),
            turn_index=int(turn_index or 0),
            state=state,
            director_cue="",
            reason=reason,
            executable_unit_id=exec_id if entry is not None else "",
            plot_unit_ids=plot_ids,
            delivery_intent=DeliveryIntent(
                speak_gate="speak",
                continuity="finish",
                plan_id=f"schedule-{exec_id}",
                wait_ms=120,
            ),
        )
        payload = request.to_dict()
        if agenda_id:
            payload["agenda_entry_id"] = agenda_id
        state.pending_character_handoff = payload
        state.notes.append(
            f"rhythm_schedule: handoff exec_unit={exec_id} "
            f"trigger={request.trigger_id} reason={reason} origin={origin}"
        )

    def _mark_character_handoff(
        self,
        state,
        *,
        user_text: str,
        turn_index: int,
        reason: str,
    ) -> None:
        self._mark_schedule_speak_handoff(
            state,
            user_text=user_text,
            turn_index=turn_index,
            reason=reason,
        )

    def _arm_poll_for_schedule(
        self,
        session_id: str,
        schedule: CharacterRhythmSchedule,
    ) -> None:
        """醒拍间隔统一走帧数管理器阶梯（5→15→30…）。"""
        del schedule
        self._arm_poll(session_id, "idle")

    def _arm_poll(self, session_id: str, trigger: str) -> None:
        frame_mgr = self._state_store.poll_frame_manager(session_id, trigger)
        frame_mgr.schedule_next()
        other = "append" if trigger == "idle" else "idle"
        other_mgr = self._state_store.poll_frame_manager(session_id, other)
        other_mgr.armed = False
        other_mgr.next_fire_at = 0.0

    def _share_wants(self, session_id: str) -> bool:
        if self._share_wants_fn is None:
            return False
        return bool(self._share_wants_fn(session_id))

    def _silence_armed(self, session_id: str) -> bool:
        if self._silence_armed_fn is None:
            return False
        return bool(self._silence_armed_fn(session_id))

    def _social_armed(self, session_id: str) -> str | None:
        if self._social_armed_fn is None:
            return None
        return self._social_armed_fn(session_id)

    def _peek_user_pending(self, session_id: str) -> bool:
        if self._peek_user_pending_fn is None:
            return False
        return bool(self._peek_user_pending_fn(session_id))

    def _is_turn_busy(self, session_id: str) -> bool:
        if self._is_turn_busy_fn is None:
            return False
        return bool(self._is_turn_busy_fn(session_id))

    def _is_pushing(self, session_id: str) -> bool:
        if self._is_pushing_fn is None:
            return False
        return bool(self._is_pushing_fn(session_id))
