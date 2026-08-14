from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from ..blocks.persona import collect_director_portrait
from ..state.core.types import SessionSnapshot
from .base import DirectorLLMCaller, DirectorOutput, extract_json_object
from .think_trace import (
    DIRECTOR_THINK_COMPRESS_RULES,
    DirectorThinkCompressor,
    DirectorThinkStep,
)

if TYPE_CHECKING:
    from ..orchestrator import SpeakOrchestrator

_MAX_REACT_STEPS = 3
_ALLOWED_ACTIONS = frozenset({"lookup_persona", "lookup_scene", "predict"})


@dataclass(frozen=True)
class NextTurnGuide:
    """导演产出：始终指向下一轮，供后续轮次消费。"""

    behavior_guide: str = ""
    script_hint: str = ""
    produced_at_turn: int = 0
    target_turn: int = 0
    think_trace: tuple[str, ...] = ()
    lookups: tuple[str, ...] = ()

    def snapshot(self) -> dict[str, Any]:
        return {
            "horizon": "next_turn",
            "behavior_guide": self.behavior_guide,
            "script_hint": self.script_hint,
            "produced_at_turn": self.produced_at_turn,
            "target_turn": self.target_turn,
            "think_trace": list(self.think_trace),
            "lookups": list(self.lookups),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> NextTurnGuide | None:
        if not isinstance(data, dict):
            return None
        behavior = str(data.get("behavior_guide") or "").strip()
        script = str(data.get("script_hint") or "").strip()
        if not behavior and not script:
            return None
        think_raw = data.get("think_trace") or ()
        lookup_raw = data.get("lookups") or ()
        return cls(
            behavior_guide=behavior,
            script_hint=script,
            produced_at_turn=int(data.get("produced_at_turn") or 0),
            target_turn=int(data.get("target_turn") or 0),
            think_trace=tuple(str(x) for x in think_raw if str(x).strip()),
            lookups=tuple(str(x) for x in lookup_raw if str(x).strip()),
        )


class NextTurnGuideDirector:
    """小 ReAct 导演：查角色/场景设定，产出下一轮行为与剧本预测。"""

    name = "next_turn_guide"

    _SYSTEM = (
        "你是不说话的对话导演，运行短小的 ReAct 循环：Think → Action → Observation。\n"
        "你只能预测「下一轮」角色行为与剧本走向，不得写当前轮台词或当前轮交付。\n"
        "可用 action：lookup_persona（查精简角色设定）、lookup_scene（查场景/世界观）、"
        "predict（结束并给出下一轮预测）。\n"
        f"{DIRECTOR_THINK_COMPRESS_RULES}\n"
        "每步只输出 JSON："
        '{"think":"...","action":"lookup_persona|lookup_scene|predict",'
        '"behavior_guide":"...","script_hint":"..."}\n'
        "predict 时必须填写 behavior_guide；script_hint 可选。"
    )

    def __init__(
        self,
        orchestrator: SpeakOrchestrator,
        *,
        llm: DirectorLLMCaller | None = None,
        think_compressor: DirectorThinkCompressor | None = None,
        max_steps: int = _MAX_REACT_STEPS,
    ) -> None:
        self._orchestrator = orchestrator
        self._llm = llm
        self._think = think_compressor or DirectorThinkCompressor()
        self._max_steps = max(1, max_steps)

    @property
    def think_compressor(self) -> DirectorThinkCompressor:
        return self._think

    def run(
        self,
        snapshot: SessionSnapshot,
        *,
        user_text: str = "",
    ) -> DirectorOutput:
        turn = int(snapshot.signals.turn_index)
        text = user_text.strip() or snapshot.dialogue.user_text.strip()
        observations: list[str] = []
        think_trace: list[str] = []
        lookups: list[str] = []
        persona_cache = ""
        scene_cache = ""

        if self._llm is not None and self._llm.available:
            for _ in range(self._max_steps):
                step = self._react_step(
                    snapshot,
                    user_text=text,
                    observations=observations,
                )
                think = str(step.get("think") or "").strip()
                action = str(step.get("action") or "").strip().lower()
                if action not in _ALLOWED_ACTIONS:
                    action = "predict"
                result = ""
                if action == "lookup_persona":
                    persona_cache = persona_cache or self._lookup_persona(snapshot.session_id)
                    result = persona_cache or "（无角色设定）"
                    observations.append(f"persona={result[:240]}")
                    lookups.append("persona")
                elif action == "lookup_scene":
                    scene_cache = scene_cache or self._lookup_scene(
                        snapshot.session_id,
                        query=text,
                    )
                    result = scene_cache or "（无场景设定）"
                    observations.append(f"scene={result[:240]}")
                    lookups.append("scene")
                else:
                    behavior = str(step.get("behavior_guide") or "").strip()
                    script = str(step.get("script_hint") or "").strip()
                    if not behavior:
                        if not persona_cache:
                            persona_cache = self._lookup_persona(snapshot.session_id)
                            lookups.append("persona")
                        behavior = self._heuristic_behavior(persona_cache, text)
                    guide = NextTurnGuide(
                        behavior_guide=behavior,
                        script_hint=script,
                        produced_at_turn=turn,
                        target_turn=turn + 1,
                        think_trace=tuple(think_trace + ([think] if think else [])),
                        lookups=tuple(dict.fromkeys(lookups)),
                    )
                    self._record_think(
                        snapshot.session_id,
                        DirectorThinkStep(think=think, action="predict", result="ok"),
                    )
                    return DirectorOutput(
                        director=self.name,
                        payload=guide.snapshot(),
                        reason="next_turn_predict",
                    )
                if think:
                    think_trace.append(think)
                self._record_think(
                    snapshot.session_id,
                    DirectorThinkStep(think=think, action=action, result=result[:160]),
                )

        persona_cache = persona_cache or self._lookup_persona(snapshot.session_id)
        scene_cache = scene_cache or self._lookup_scene(snapshot.session_id, query=text)
        if persona_cache:
            lookups.append("persona")
        if scene_cache:
            lookups.append("scene")
        guide = NextTurnGuide(
            behavior_guide=self._heuristic_behavior(persona_cache, text),
            script_hint=scene_cache[:200] if scene_cache else "",
            produced_at_turn=turn,
            target_turn=turn + 1,
            think_trace=tuple(think_trace),
            lookups=tuple(dict.fromkeys(lookups)),
        )
        self._record_think(
            snapshot.session_id,
            DirectorThinkStep(
                think="heuristic next-turn guide",
                action="predict",
                result="heuristic",
            ),
        )
        return DirectorOutput(
            director=self.name,
            payload=guide.snapshot(),
            reason="next_turn_heuristic",
            used_fallback=True,
        )

    def _react_step(
        self,
        snapshot: SessionSnapshot,
        *,
        user_text: str,
        observations: list[str],
    ) -> dict[str, Any]:
        lines = [
            f"session={snapshot.session_id}",
            f"current_turn={snapshot.signals.turn_index}",
            f"predict_target_turn={snapshot.signals.turn_index + 1}",
            f"user_text={user_text[:400]}",
            "horizon=next_turn（禁止当前轮台词）",
        ]
        manager_brief = str(
            snapshot.orchestrator.compose_meta.get("compose_manager_director_brief") or ""
        ).strip()
        if manager_brief:
            lines.append(f"compose_manager={manager_brief[:400]}")
        if observations:
            lines.append("observations:\n- " + "\n- ".join(observations[-4:]))
        raw = self._llm.generate_json(
            system=self._SYSTEM,
            user="\n".join(lines),
            session_id=snapshot.session_id,
            director=self.name,
            turn_index=snapshot.signals.turn_index,
        )
        return extract_json_object(raw) or {"action": "predict", "think": "empty_llm"}

    def _lookup_persona(self, session_id: str) -> str:
        snap = self._orchestrator.persona_compose.query_persona_snapshot(session_id)
        return collect_director_portrait(persona_snap=snap)

    def _lookup_scene(self, session_id: str, *, query: str) -> str:
        return self._orchestrator.scene_compose.director_scene_brief(
            session_id,
            query=query,
        )

    def _heuristic_behavior(self, persona: str, user_text: str) -> str:
        base = persona.strip() or "保持角色稳定姿态与边界。"
        cue = user_text.strip()
        if cue:
            return f"下一轮延续角色设定：{base} 对用户「{cue[:80]}」作自然回应，不抢当前轮。"
        return f"下一轮延续角色设定：{base}"

    def _record_think(self, session_id: str, step: DirectorThinkStep) -> None:
        self._think.record(session_id, step)


def apply_next_turn_guide_output(state, output: DirectorOutput) -> NextTurnGuide | None:
    guide = NextTurnGuide.from_dict(output.payload)
    if guide is None:
        return None
    state.pending_next_turn_guide = guide.snapshot()
    return guide


def promote_pending_next_turn_guide(state) -> NextTurnGuide | None:
    """入站时：上轮 pending → 本轮 active（角色消费）；再清空 pending 等待新预测。"""
    guide = NextTurnGuide.from_dict(getattr(state, "pending_next_turn_guide", None))
    state.active_next_turn_guide = guide.snapshot() if guide is not None else {}
    state.pending_next_turn_guide = {}
    return guide
