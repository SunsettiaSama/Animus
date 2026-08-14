from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING, Any

from ..prompt_trace import get_prompt_trace
from ..state.snapshot.builder import SnapshotBuilder
from .domain import InterruptDirector, MemoryInjectDirector, ShareImpulseDirector, SocialArmDirector
from .dynamic_layer import DynamicLayerDirector, apply_dynamic_layer_terminate
from .module_inject import ModuleInjectDirector
from .next_turn_guide import (
    NextTurnGuideDirector,
    apply_next_turn_guide_output,
    promote_pending_next_turn_guide,
)
from .outline import OutlineDirector, apply_outline_output
from .base import DirectorOutput
from .fallback import fallback_delivery_plan
from .presence_card import PresenceCardDirector, apply_presence_card_output
from .speak_gate import SpeakGateDirector, apply_speak_gate_output
from .turn_delivery import TurnDeliveryDirector, apply_turn_delivery_output
from .user_intent import UserIntentDirector, apply_user_intent_output
from .agent import build_rhythm_card, inject_director_frame

if TYPE_CHECKING:
    from ..orchestrator import SpeakOrchestrator
    from ..state import StateStore
    from .base import DirectorLLMCaller
    from .agent import DirectorAgentHost


class DirectorCoordinator:
    """合并各导演决策并写入 StateStore。"""

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
    ) -> None:
        self._state_store = state_store
        self._snapshot_builder = snapshot_builder
        self._outline = OutlineDirector(llm)
        self._user_intent = UserIntentDirector(llm)
        self._turn_delivery = TurnDeliveryDirector(llm)
        self._speak_gate = SpeakGateDirector(llm)
        self._module_inject = ModuleInjectDirector(orchestrator, llm=llm)
        self._memory = MemoryInjectDirector(llm=llm)
        self._dynamic_layer = DynamicLayerDirector(llm=llm)
        self._presence_card = PresenceCardDirector(llm=llm)
        self._next_turn_guide = NextTurnGuideDirector(orchestrator, llm=llm)
        self._share = ShareImpulseDirector()
        self._social = SocialArmDirector()
        self._interrupt = InterruptDirector()
        self._share_wants_fn = share_wants_fn
        self._silence_armed_fn = silence_armed_fn
        self._social_armed_fn = social_armed_fn
        self._director_agent = director_agent

    def _arm_frame(
        self,
        session_id: str,
        *,
        user_text: str = "",
        share_wants: bool,
        silence_armed: bool,
        social_armed: str | None,
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
        )

    def on_user_input(
        self,
        session_id: str,
        user_text: str,
        *,
        turn_index: int,
    ) -> dict[str, Any]:
        state = self._state_store.session(session_id)
        # 用户入站解锁：导演可重新改写/重排上下文
        state.director_context_frozen = False
        # 上轮预测 → 本轮 active；本轮导演只写下一轮 pending，避免当前轮等待
        active_guide = promote_pending_next_turn_guide(state)
        share_wants = self._share_wants(session_id)
        silence_armed = self._silence_armed(session_id)
        social_armed = self._social_armed(session_id)
        self._arm_frame(
            session_id,
            user_text=user_text,
            share_wants=share_wants,
            silence_armed=silence_armed,
            social_armed=social_armed,
        )
        snapshot = self._snapshot_builder.build(
            session_id,
            user_text=user_text,
        )

        # 入站第一批并行：Outline / UserIntent / TurnDelivery / NextTurnGuide / PresenceCard
        # NextTurnGuide 只写下一轮 pending，本轮角色只消费已 promote 的 active
        with ThreadPoolExecutor(max_workers=5, thread_name_prefix="speak-director-ingress") as pool:
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
            presence_future = pool.submit(
                self._presence_card.run,
                snapshot,
                user_text=user_text,
                previous=state.presence_card,
                poll=False,
            )
            outline_out = outline_future.result()
            intent_out = intent_future.result()
            delivery_out = delivery_future.result()
            guide_out = guide_future.result()
            presence_out = presence_future.result()
        apply_next_turn_guide_output(state, guide_out)
        apply_presence_card_output(state, presence_out, turn_index=turn_index)
        module_out = self._module_inject.run(
            snapshot,
            user_text=user_text,
            social_armed=social_armed,
            silence_armed=silence_armed,
            share_wants=share_wants,
        )
        memory_out = self._memory.run(snapshot, user_text=user_text)
        share_out = self._share.run(snapshot, share_wants=share_wants)
        social_out = self._social.run(
            snapshot,
            silence_armed=silence_armed,
            social_armed=social_armed,
        )
        dynamic_out = self._dynamic_layer.run(
            snapshot,
            user_text=user_text,
            share_wants=share_wants,
            poll=False,
        )
        apply_dynamic_layer_terminate(state, dynamic_out)

        apply_outline_output(state, outline_out)
        apply_user_intent_output(state, intent_out)
        apply_turn_delivery_output(state, delivery_out, pending=True)
        has_plan = state.pending_delivery_plan is not None and not state.pending_delivery_plan.is_empty
        # 主动社交 / 真实用户输入：必须开口，避免 gate 误判 hold/listen 导致前端空回合
        force_social_speak = social_armed in ("enter_greeting", "silence_break")
        force_user_speak = bool(user_text.strip())
        force_speak = force_social_speak or force_user_speak
        if force_speak and not has_plan:
            state.pending_delivery_plan = fallback_delivery_plan(
                snapshot,
                user_text=user_text,
            )
            has_plan = (
                state.pending_delivery_plan is not None
                and not state.pending_delivery_plan.is_empty
            )
            reason = social_armed or "user_input"
            state.notes.append(f"ingress: fallback delivery for {reason}")
        if force_speak:
            reason = social_armed or "user_input"
            state.speak_gate = "speak"
            gate_out = DirectorOutput(
                director="speak_gate",
                payload={"action": "speak", "reason": f"forced:{reason}"},
                reason=f"forced:{reason}",
            )
            state.notes.append(f"ingress: force speak for {reason}")
        else:
            gate_out = self._speak_gate.run(
                snapshot,
                user_text=user_text,
                has_delivery_plan=has_plan,
            )
            apply_speak_gate_output(state, gate_out)

        outputs = {
            outline_out.director: outline_out.snapshot(),
            intent_out.director: intent_out.snapshot(),
            delivery_out.director: delivery_out.snapshot(),
            module_out.director: module_out.snapshot(),
            memory_out.director: memory_out.snapshot(),
            share_out.director: share_out.snapshot(),
            social_out.director: social_out.snapshot(),
            dynamic_out.director: dynamic_out.snapshot(),
            presence_out.director: presence_out.snapshot(),
            guide_out.director: guide_out.snapshot(),
            gate_out.director: gate_out.snapshot(),
        }
        state.director_cache = outputs
        if active_guide is not None:
            state.director_cache["active_next_turn_guide"] = active_guide.snapshot()
        if state.presence_card.ready:
            state.director_cache["presence_card_state"] = state.presence_card.snapshot()
        state.notes.append(f"ingress:user_input turn={turn_index}")
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
                "has_delivery_plan": has_plan,
                "active_next_turn_guide": state.active_next_turn_guide,
                "pending_next_turn_guide": state.pending_next_turn_guide,
                "presence_card": state.presence_card.snapshot(),
                "outputs": outputs,
            },
        )

        if state.speak_gate == "speak" and has_plan and not force_speak:
            self._arm_poll(session_id, "append")
        elif force_speak:
            # 真实开口后转入 idle 衰减轮询（间隔拉长），不靠短时狂刷
            idle = self._state_store.poll_cursor(session_id, "idle")
            idle.reset_decay()
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

        share_wants = self._share_wants(session_id)
        social_armed = self._social_armed(session_id)
        silence_armed = self._silence_armed(session_id)
        # idle 空转：无分享/社交信号时跳过昂贵导演 LLM，只按衰减续表
        if (
            trigger == "idle"
            and not share_wants
            and not social_armed
            and not silence_armed
            and not snapshot.runtime.typing_active
        ):
            state.speak_gate = "hold"
            state.pending_delivery_plan = None
            state.director_cache["poll"] = {
                "trigger": trigger,
                "skipped": "idle_quiet",
                "reason": "no share/social signal; decay only",
            }
            get_prompt_trace().emit_event(
                session_id,
                label="director_poll_quiet",
                turn_index=snapshot.signals.turn_index,
                payload=state.director_cache["poll"],
            )
            self._arm_poll(session_id, "idle")
            return state.director_cache["poll"]

        # 新一轮询解锁：允许导演再次改写上下文；本拍内若 terminate 再冻结
        state.director_context_frozen = False

        self._arm_frame(
            session_id,
            user_text=snapshot.dialogue.user_text,
            share_wants=share_wants,
            silence_armed=silence_armed,
            social_armed=social_armed,
        )
        snapshot = self._snapshot_builder.build(session_id)

        # 指挥顺序：临场卡 → 动态层组装 →（可选终止）→ 交付/门控
        presence_out = self._presence_card.run(
            snapshot,
            user_text=snapshot.dialogue.user_text,
            previous=state.presence_card,
            poll=True,
        )
        apply_presence_card_output(
            state,
            presence_out,
            turn_index=snapshot.signals.turn_index,
        )
        dynamic_out = self._dynamic_layer.run(
            snapshot,
            user_text=snapshot.dialogue.user_text,
            share_wants=share_wants,
            poll=True,
        )
        terminated = apply_dynamic_layer_terminate(state, dynamic_out)
        state.director_cache["presence_card"] = presence_out.snapshot()
        state.director_cache["dynamic_layer"] = dynamic_out.snapshot()
        if state.presence_card.ready:
            state.director_cache["presence_card_state"] = state.presence_card.snapshot()

        if terminated:
            # 终止导演本轮动作：不再改写/重排上下文，hold 等待用户或下次轮询
            state.speak_gate = "hold"
            state.pending_delivery_plan = None
            state.director_cache["poll"] = {
                "trigger": trigger,
                "terminated": True,
                "presence_card": presence_out.snapshot(),
                "dynamic_layer": dynamic_out.snapshot(),
                "reason": "director_terminate_round",
            }
            get_prompt_trace().emit_event(
                session_id,
                label="director_poll_terminated",
                turn_index=snapshot.signals.turn_index,
                payload=state.director_cache["poll"],
            )
            self._arm_poll(session_id, "idle")
            return state.director_cache["poll"]

        delivery_out = self._turn_delivery.run(snapshot)
        apply_turn_delivery_output(state, delivery_out, pending=True)
        has_plan = state.pending_delivery_plan is not None and not state.pending_delivery_plan.is_empty
        gate_out = self._speak_gate.run(snapshot, has_delivery_plan=has_plan)
        apply_speak_gate_output(state, gate_out)
        state.director_cache["poll"] = {
            "trigger": trigger,
            "terminated": False,
            "presence_card": presence_out.snapshot(),
            "delivery": delivery_out.snapshot(),
            "gate": gate_out.snapshot(),
            "dynamic_layer": dynamic_out.snapshot(),
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
        action = str(gate_out.payload.get("action") or "hold").strip().lower()
        if has_plan and action in ("speak", "brew"):
            # 可见正文不走占位 async push；清掉占位 plan，继续 idle 衰减（避免停表假死）
            state.pending_delivery_plan = None
            self._arm_poll(session_id, "idle")
            return state.director_cache["poll"]
        # hold/listen：丢掉刚生成的占位 plan，按衰减续 idle（勿与 append 双开）
        state.pending_delivery_plan = None
        self._arm_poll(session_id, "idle")
        return state.director_cache.get("poll", {})

    def on_delivery_done(self, session_id: str) -> None:
        state = self._state_store.session(session_id)
        state.delivery_plan = None
        state.pending_delivery_plan = None
        idle = self._state_store.poll_cursor(session_id, "idle")
        idle.reset_decay()
        self._arm_poll(session_id, "idle")

    def should_continue_delivery(self, session_id: str) -> bool:
        snapshot = self._snapshot_builder.build(session_id)
        return self._turn_delivery.should_continue_on_disconnect(snapshot)

    def _arm_poll(self, session_id: str, trigger: str) -> None:
        cursor = self._state_store.poll_cursor(session_id, trigger)
        cursor.schedule_next()
        # 互斥：同时只保留一类 poll，消除 append+idle 双轨竞态
        other = "append" if trigger == "idle" else "idle"
        other_cursor = self._state_store.poll_cursor(session_id, other)
        other_cursor.armed = False
        other_cursor.next_fire_at = 0.0

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
