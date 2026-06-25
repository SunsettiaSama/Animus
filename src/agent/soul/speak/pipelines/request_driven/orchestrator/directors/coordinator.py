from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING, Any

from ..prompt_trace import get_prompt_trace
from ..state.snapshot.builder import SnapshotBuilder
from .domain import InterruptDirector, MemoryInjectDirector, ShareImpulseDirector, SocialArmDirector
from .module_inject import ModuleInjectDirector
from .outline import OutlineDirector, apply_outline_output
from .speak_gate import SpeakGateDirector, apply_speak_gate_output
from .turn_delivery import TurnDeliveryDirector, apply_turn_delivery_output
from .user_intent import UserIntentDirector, apply_user_intent_output

if TYPE_CHECKING:
    from ..orchestrator import SpeakOrchestrator
    from ..state import StateStore
    from .base import DirectorLLMCaller


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
    ) -> None:
        self._state_store = state_store
        self._snapshot_builder = snapshot_builder
        self._outline = OutlineDirector(llm)
        self._user_intent = UserIntentDirector(llm)
        self._turn_delivery = TurnDeliveryDirector(llm)
        self._speak_gate = SpeakGateDirector(llm)
        self._module_inject = ModuleInjectDirector(orchestrator, llm=llm)
        self._memory = MemoryInjectDirector()
        self._share = ShareImpulseDirector()
        self._social = SocialArmDirector()
        self._interrupt = InterruptDirector()
        self._share_wants_fn = share_wants_fn
        self._silence_armed_fn = silence_armed_fn
        self._social_armed_fn = social_armed_fn

    def on_user_input(
        self,
        session_id: str,
        user_text: str,
        *,
        turn_index: int,
    ) -> dict[str, Any]:
        snapshot = self._snapshot_builder.build(
            session_id,
            user_text=user_text,
        )
        state = self._state_store.session(session_id)
        share_wants = self._share_wants(session_id)
        silence_armed = self._silence_armed(session_id)
        social_armed = self._social_armed(session_id)

        # 入站第一批导演请求并行：Outline + UserIntent + TurnDelivery
        with ThreadPoolExecutor(max_workers=3, thread_name_prefix="speak-director-ingress") as pool:
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
            outline_out = outline_future.result()
            intent_out = intent_future.result()
            delivery_out = delivery_future.result()
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

        apply_outline_output(state, outline_out)
        apply_user_intent_output(state, intent_out)
        apply_turn_delivery_output(state, delivery_out, pending=True)
        has_plan = state.pending_delivery_plan is not None and not state.pending_delivery_plan.is_empty
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
            gate_out.director: gate_out.snapshot(),
        }
        state.director_cache = outputs
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
                "outputs": outputs,
            },
        )

        if gate_out.payload.get("action") == "speak" and has_plan:
            self._arm_poll(session_id, "append")
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
            return {"interrupt": interrupt_out.snapshot()}

        delivery_out = self._turn_delivery.run(snapshot)
        apply_turn_delivery_output(state, delivery_out, pending=True)
        has_plan = state.pending_delivery_plan is not None and not state.pending_delivery_plan.is_empty
        gate_out = self._speak_gate.run(snapshot, has_delivery_plan=has_plan)
        apply_speak_gate_output(state, gate_out)
        state.director_cache["poll"] = {
            "trigger": trigger,
            "delivery": delivery_out.snapshot(),
            "gate": gate_out.snapshot(),
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
        if has_plan and gate_out.payload.get("action") in ("speak", "brew"):
            return state.director_cache["poll"]
        self._arm_poll(session_id, trigger)
        return state.director_cache.get("poll", {})

    def on_delivery_done(self, session_id: str) -> None:
        state = self._state_store.session(session_id)
        state.delivery_plan = None
        cursor = self._state_store.poll_cursor(session_id, "append")
        cursor.armed = True
        cursor.schedule_next()

    def should_continue_delivery(self, session_id: str) -> bool:
        snapshot = self._snapshot_builder.build(session_id)
        return self._turn_delivery.should_continue_on_disconnect(snapshot)

    def _arm_poll(self, session_id: str, trigger: str) -> None:
        cursor = self._state_store.poll_cursor(session_id, trigger)
        cursor.armed = True
        cursor.schedule_next()

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
