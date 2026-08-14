from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from agent.soul.speak.responders.request_driven.orchestrator.compose_manager.projectors.dynamic_layer import (
    DynamicLayerMaterials,
    DynamicLayerSchedule,
)
from agent.soul.speak.responders.request_driven.orchestrator.compose_manager.projectors.role_view import (
    RoleContextView,
)

from .delivery_bridge import RoleTurnResult, execute_timeline_sync, timeline_to_delivery_plan
from .interpreter import interpret_role_output, interpret_role_packet
from .prompt import RolePrompt, build_role_prompt
from .timeline import RoleTimeline


GenerateFn = Callable[[str, str], str]


@dataclass
class SpeakRole:
    """显式角色运行时：prepare → generate → interpret → execute。"""

    generate_fn: GenerateFn | None = None

    def prepare(
        self,
        view: RoleContextView,
        *,
        user_text: str,
        materials: DynamicLayerMaterials | None = None,
        schedule: DynamicLayerSchedule | None = None,
        help_observations: tuple[str, ...] = (),
        behavior_guide: str = "",
        script_hint: str = "",
    ) -> RolePrompt:
        return build_role_prompt(
            view,
            user_text=user_text,
            materials=materials,
            schedule=schedule,
            behavior_guide=behavior_guide,
            script_hint=script_hint,
            help_observations=help_observations,
        )

    def generate(self, prompt: RolePrompt, *, base_system: str = "") -> str:
        if self.generate_fn is None:
            raise RuntimeError("SpeakRole.generate_fn 未绑定")
        system = base_system.strip()
        if prompt.system_extra.strip():
            system = f"{system}\n\n{prompt.system_extra}".strip() if system else prompt.system_extra
        return self.generate_fn(system, prompt.user_text)

    def interpret(self, raw: str) -> RoleTimeline:
        return interpret_role_output(raw)

    def interpret_packet(self, raw: str):
        return interpret_role_packet(raw)

    def execute(
        self,
        timeline: RoleTimeline,
        *,
        turn_index: int = 0,
        plan_id: str = "role-timeline",
        sleep_fn=None,
    ) -> RoleTurnResult:
        result = execute_timeline_sync(timeline, sleep_fn=sleep_fn or (lambda _s: None))
        result.delivery_plan = timeline_to_delivery_plan(
            timeline,
            turn_index=turn_index,
            plan_id=plan_id,
        )
        return result

    def run_turn(
        self,
        view: RoleContextView,
        *,
        user_text: str,
        base_system: str = "",
        turn_index: int = 0,
        plan_id: str = "role-timeline",
        raw_override: str | None = None,
        materials: DynamicLayerMaterials | None = None,
        schedule: DynamicLayerSchedule | None = None,
    ) -> tuple[RolePrompt, str, RoleTimeline, RoleTurnResult]:
        prompt = self.prepare(
            view,
            user_text=user_text,
            materials=materials,
            schedule=schedule,
        )
        raw = raw_override if raw_override is not None else self.generate(prompt, base_system=base_system)
        timeline = self.interpret(raw)
        result = self.execute(timeline, turn_index=turn_index, plan_id=plan_id)
        return prompt, raw, timeline, result
