from __future__ import annotations

from collections.abc import Callable
from typing import Any

from agent.soul.speak.io.outbound.stream.parse.model import SpeakAgentOutput
from agent.soul.speak.io.outbound.stream.parse.parser import parse_agent_output
from agent.soul.speak.responders.request_driven.delivery_bridge import timeline_to_delivery_plan
from agent.soul.speak.responders.request_driven.interpreter import interpret_role_packet
from agent.soul.speak.responders.request_driven.orchestrator.assemble import build_turn_system
from agent.soul.speak.responders.request_driven.composer.projectors.dynamic_layer import (
    DynamicLayerMaterials,
    DynamicLayerSchedule,
)
from agent.soul.speak.responders.request_driven.composer.projectors.role_view import (
    RoleContextView,
)
from agent.soul.speak.responders.request_driven.orchestrator.state.core.delivery import (
    DeliveryPlan,
)
from agent.soul.speak.responders.request_driven.prompt import build_role_prompt
from agent.soul.speak.responders.request_driven.responder import SpeakRole

from .consume import resolve_injected_memory_ids, resolve_injected_share
from .context import context_cards_from_narrative
from .contracts import CharacterReplyRequest, CharacterReplyResult
from .host import CharacterAgentHost
from .memory_buffer import CharacterMemoryBuffer

HelpFn = Callable[[str, tuple[str, ...], str], tuple[str, ...]]
PaceFn = Callable[[Any, str], DeliveryPlan]


class CharacterRuntime:
    """角色唯一正文作者：消费 CharacterReplyRequest，产出 CharacterReplyResult。

    角色可沉默、可拒指令；记忆/分享以卡片压入，本轮结束后必须完成消费。
    """

    def __init__(
        self,
        *,
        speak_role: SpeakRole,
        character_agent: CharacterAgentHost | None = None,
        request_helps: HelpFn | None = None,
        pace_delivery: PaceFn | None = None,
    ) -> None:
        self._speak_role = speak_role
        self._character_agent = character_agent
        self._request_helps = request_helps
        self._pace_delivery = pace_delivery
        self._memory_buffer = CharacterMemoryBuffer()

    def bind_character_agent(self, agent: CharacterAgentHost | None) -> None:
        self._character_agent = agent

    @property
    def memory_buffer(self) -> CharacterMemoryBuffer:
        return self._memory_buffer

    def run(
        self,
        request: CharacterReplyRequest,
        *,
        bundle: Any,
        view: RoleContextView,
        materials: DynamicLayerMaterials,
        schedule: DynamicLayerSchedule,
        director_plan: DeliveryPlan | None = None,
        notes: list[str] | None = None,
    ) -> CharacterReplyResult:
        note_buf = notes if notes is not None else []
        note_buf.append(f"character_runtime:origin={request.origin}")
        note_buf.append(f"character_runtime:trigger={request.trigger_id}")
        self._memory_buffer.bind_session(request.session_id)
        note_buf.append(self._memory_buffer.note())

        narrative = request.narrative
        user_text = request.effective_user_text
        base_system = build_turn_system(bundle, for_character=True)
        memory_ids = resolve_injected_memory_ids(schedule, materials)
        share_texts, share_indices = resolve_injected_share(schedule, materials)

        def _build_prompt(obs: tuple[str, ...] = ()) -> Any:
            return build_role_prompt(
                view,
                user_text=user_text,
                materials=materials,
                schedule=schedule,
                help_observations=obs,
                presence_mood=narrative.presence_mood,
                presence_brief=narrative.presence_brief,
                presence_speak_desire=narrative.presence_speak_desire,
                presence_fate_tendency=narrative.presence_fate_tendency,
                user_identity=narrative.user_identity,
                user_activity=narrative.user_activity,
                interaction_channel=narrative.interaction_channel,
                plot_outline_text=narrative.plot_outline_text,
                plot_flow_text=narrative.plot_flow_text,
                scene_event=narrative.scene_event if not narrative.plot_flow_text else "",
                silence_log_text="",
                director_focus=narrative.director_focus,
                director_intent=narrative.director_intent,
                director_direction=narrative.director_direction,
                director_exit=narrative.director_exit,
                director_detail=narrative.director_detail,
                director_inner=narrative.director_inner,
                director_transition=narrative.director_transition,
                director_stance=narrative.director_stance,
                interaction_record_text=narrative.interaction_record_text,
            )

        def _generate_once(obs: tuple[str, ...] = ()) -> tuple[str, Any]:
            role_prompt = _build_prompt(obs)
            system = base_system
            if role_prompt.system_extra.strip():
                system = (
                    f"{system}\n\n{role_prompt.system_extra}".strip()
                    if system
                    else role_prompt.system_extra
                )
            cards = context_cards_from_narrative(
                narrative,
                dialogue_frame=(
                    role_prompt.layers.dialogue_frame
                    if role_prompt.layers is not None
                    else ""
                ),
                memory_texts=schedule.selected_memory_texts(materials),
                share_texts=share_texts,
                user_text=user_text if request.origin == "user" else "",
            )
            if self._character_agent is not None:
                raw_text = self._character_agent.generate(
                    system=system,
                    user_text=user_text,
                    context_cards=cards,
                    help_observations=obs,
                )
            else:
                raw_text = self._speak_role.generate(role_prompt, base_system=base_system)
            return raw_text, role_prompt

        raw, _prompt = _generate_once()
        packet = interpret_role_packet(raw)
        if packet.help_goals and self._request_helps is not None:
            note_buf.append(f"character_ask_help:{len(packet.help_goals)}")
            help_observations = self._request_helps(
                request.session_id,
                packet.help_goals,
                user_text,
            )
            if help_observations:
                note_buf.append("character_help_routed")
                raw, _prompt = _generate_once(help_observations)
                packet = interpret_role_packet(raw)

        timeline = packet.timeline
        paced = timeline_to_delivery_plan(
            timeline,
            turn_index=request.turn_index,
            plan_id=f"role-{request.session_id}-{request.turn_index}",
        )
        answer_text = timeline.answer_text
        if paced.is_empty and answer_text.strip() and self._pace_delivery is not None:
            paced = self._pace_delivery(director_plan, answer_text)
        parsed = parse_agent_output(raw)
        if not parsed.speak.strip() and answer_text.strip():
            body_actions = tuple(
                op.body.strip()
                for op in timeline.ops
                if op.kind == "body" and op.body.strip()
            )
            parsed = SpeakAgentOutput(
                thought="\n".join(
                    op.body.strip()
                    for op in timeline.ops
                    if op.kind == "think" and op.body.strip()
                ),
                speak=answer_text,
                actions=body_actions,
                raw=raw,
            )
        if timeline.ignored:
            note_buf.append(f"role_ignored:{len(timeline.ignored)}")
        if not timeline.ops:
            note_buf.append("role_timeline_empty")
        chose_silence = (not answer_text.strip()) and any(
            op.kind == "silence" for op in timeline.ops
        )
        if chose_silence:
            note_buf.append("character_chose_silence")
        if packet.notes_to_director:
            note_buf.append(f"character_note_director:{len(packet.notes_to_director)}")
        if packet.notes_to_screenwriter:
            note_buf.append(
                f"character_note_screenwriter:{len(packet.notes_to_screenwriter)}"
            )
        note_buf.append(f"dynamic_schedule:{schedule.reason}")
        if memory_ids:
            note_buf.append(f"dynamic_inject_memory:{len(memory_ids)}")
        if share_texts:
            note_buf.append(f"dynamic_inject_share:{len(share_texts)}")
        if schedule.pass_info:
            note_buf.append("dynamic_pass_info")

        return CharacterReplyResult(
            origin=request.origin,
            trigger_id=request.trigger_id,
            session_id=request.session_id,
            turn_index=request.turn_index,
            raw=raw,
            answer_text=answer_text,
            delivery_plan=paced,
            timeline=timeline,
            parsed=parsed,
            notes=list(note_buf),
            consumed_executable_unit_id=request.executable_unit_id,
            consumed_plot_unit_ids=request.plot_unit_ids,
            consumed_memory_unit_ids=memory_ids,
            consumed_share_texts=share_texts,
            consumed_share_indices=share_indices,
            notes_to_director=packet.notes_to_director,
            notes_to_screenwriter=packet.notes_to_screenwriter,
            chose_silence=chose_silence,
        )
