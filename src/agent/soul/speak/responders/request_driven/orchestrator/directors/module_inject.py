from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ..director.decide import decide_plan
from ..director.types import DirectorPlan
from ..state.core.types import SessionSnapshot
from .base import DirectorLLMCaller, DirectorOutput, extract_json_object
from .fallback import parse_module_inject_payload

if TYPE_CHECKING:
    from ..orchestrator import SpeakOrchestrator


class ModuleInjectDirector:
    """接管 block 注入计划，替代 ComposeDirector 决策入口。"""

    name = "module_inject"

    def __init__(
        self,
        orchestrator: SpeakOrchestrator,
        *,
        llm: DirectorLLMCaller | None = None,
    ) -> None:
        self._orchestrator = orchestrator
        self._llm = llm
        self._store = orchestrator.compose_director.store

    def run(
        self,
        snapshot: SessionSnapshot,
        *,
        user_text: str = "",
        social_armed: str | None = None,
        silence_armed: bool = False,
        share_wants: bool = False,
    ) -> DirectorOutput:
        sid = snapshot.session_id
        turn_index = snapshot.signals.turn_index
        generation = snapshot.signals.generation
        meta = self._orchestrator.compose_cache(sid).meta_snapshot()
        plan = decide_plan(
            self._orchestrator,
            session_id=sid,
            target_turn_index=turn_index,
            user_text=user_text.strip() or snapshot.dialogue.user_text.strip(),
            generation=generation,
            bundle_meta=meta,
            cold_start=self._store.load(sid, turn_index - 1) is None,
            social_armed=social_armed,  # type: ignore[arg-type]
            silence_armed=silence_armed,
            share_wants=share_wants,
        )
        if self._llm is not None and self._llm.available:
            tuned = self._maybe_tune_modules(snapshot, plan, user_text=user_text)
            if tuned is not None:
                plan = tuned
        self._store.save(plan)
        return DirectorOutput(
            director=self.name,
            payload={"director_plan": plan.snapshot()},
            reason="module_inject_ok",
        )

    def load_plan(self, session_id: str, turn_index: int) -> DirectorPlan | None:
        return self._store.load(session_id, turn_index)

    def _maybe_tune_modules(
        self,
        snapshot: SessionSnapshot,
        plan: DirectorPlan,
        *,
        user_text: str,
    ) -> DirectorPlan | None:
        prompt = (
            f"user_text={user_text.strip()[:200]}\n"
            f"current_refresh={plan.refresh_flags()}\n"
            '输出 JSON：{"modules":{"persona":true,"context":false,...}}'
        )
        raw = self._llm.generate_json(
            system="你是模块注入导演，只输出 modules refresh 布尔映射 JSON。",
            user=prompt,
            session_id=snapshot.session_id,
            director=self.name,
            turn_index=snapshot.signals.turn_index,
        )
        payload = extract_json_object(raw)
        modules = parse_module_inject_payload(payload)
        if not modules:
            return None
        from ..director.types import ModuleDecision

        updated: list[ModuleDecision] = []
        for item in plan.modules:
            override = modules.get(item.block)
            if override is None:
                updated.append(item)
                continue
            updated.append(
                ModuleDecision(
                    block=item.block,
                    refresh=override,
                    include=item.include,
                    reason=f"module_inject_override:{override}",
                    guidance_trigger=item.guidance_trigger,
                ),
            )
        plan.modules = tuple(updated)
        return plan
