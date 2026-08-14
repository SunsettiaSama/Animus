from __future__ import annotations

from dataclasses import replace
from typing import Any

from agent.soul.presence import PresenceService
from agent.soul.speak.io.inbound.unit import SpeakExchange, SpeakQuestion
from agent.soul.speak.io.outbound.unit import SpeakAnswer
from agent.soul.speak.llm.director_engine import SpeakDirectorLLMEngine
from agent.soul.speak.llm.engine import SpeakLLMEngine
from agent.soul.speak.service import SpeakService
from agent.soul.speak.session import (
    SpeakTurnChunk,
    resolve_feeling,
    resolve_subjective,
)
from config.llm_core.config import LLMConfig
from infra.llm import LLM

from .judge import CategoricalDialogueJudge
from .simulation import (
    DialogueSimulator,
    DynamicUserSimulator,
    SpeakServiceTurnPort,
)


class _WorkbenchPersona:
    def get_persona_snapshot(self, *, session_id: str = "") -> dict[str, Any]:
        _ = session_id
        return {
            "profile": {
                "name": "Lina",
                "core_traits": ["calm", "observant", "restrained"],
                "built": True,
                "built_at": "speak-turing-workbench",
            },
            "self_concept": {
                "narrative": "I accompany people with attention and continuity.",
                "beliefs": [],
            },
            "attention_keywords": [],
            "persona_distill": {
                "schema_version": 1,
                "source_revision": "speak-turing-v1",
                "distilled_at": "2026-08-02T00:00:00+00:00",
                "slices": {
                    "general": "Lina is calm, observant, and not performative.",
                    "dialogue": (
                        "Respond naturally and concretely. Do not over-explain, "
                        "interrogate, or summarize every user message."
                    ),
                    "story": "No fixed story context.",
                    "reasoning": "Notice subtext before choosing what to say.",
                    "memory_anchor": "Carry forward details from this conversation.",
                },
            },
        }


class _RecordingLifeOutbound:
    def __init__(self) -> None:
        self.recorded: list[dict[str, Any]] = []

    def touch_dialogue(self, session_id: str) -> None:
        _ = session_id

    def emit_dialogue_turn(self, chunk: SpeakTurnChunk) -> None:
        feeling = resolve_feeling(chunk)
        self.recorded.append(
            {
                "session_id": chunk.session_id,
                "user_text": chunk.user_text,
                "agent_text": chunk.agent_text,
                "emotion_label": feeling.emotion_label,
            }
        )

    def record_turn_exchange(self, chunk: SpeakTurnChunk) -> SpeakExchange:
        self.emit_dialogue_turn(chunk)
        return SpeakExchange(
            session_id=chunk.session_id,
            question=SpeakQuestion(text=chunk.user_text),
            answer=SpeakAnswer(text=chunk.agent_text),
            subjective=resolve_subjective(chunk),
            feeling=chunk.feeling,
        )


def _role_config(base: LLMConfig, *, temperature: float, max_tokens: int) -> LLMConfig:
    return replace(
        base,
        temperature=temperature,
        max_tokens=max_tokens,
    )


class LiveSpeakTuringRuntime:
    def __init__(
        self,
        *,
        llm_config_path: str,
        judge_llm_config_path: str | None = None,
        judge_repeats: int = 3,
        seed: int = 20260802,
    ) -> None:
        base = LLMConfig.from_yaml(llm_config_path)
        judge_base = LLMConfig.from_yaml(
            judge_llm_config_path or llm_config_path
        )
        speak_llm = LLM(_role_config(base, temperature=0.8, max_tokens=768))
        director_llm = LLM(_role_config(base, temperature=0.3, max_tokens=512))
        simulator_llm = LLM(_role_config(base, temperature=0.9, max_tokens=256))
        judge_llm = LLM(
            _role_config(judge_base, temperature=0.2, max_tokens=256)
        )

        self.life = _RecordingLifeOutbound()
        self.service = SpeakService(
            persona=_WorkbenchPersona(),
            presence=PresenceService(),
            llm_engine=SpeakLLMEngine(speak_llm),
            director_llm_engine=SpeakDirectorLLMEngine(director_llm),
            life_outbound=self.life,
            life_lifecycle=None,
            keyword_wait_ms=0,
            portrait_wait_ms=0,
            typing_idle_ms=50,
        )
        self.service.start()
        self.simulator = DialogueSimulator(
            user_simulator=DynamicUserSimulator(simulator_llm),
            speak=SpeakServiceTurnPort(self.service),
        )
        self.judge = CategoricalDialogueJudge(
            judge_llm,
            repeats=judge_repeats,
            seed=seed,
        )

    def close(self) -> None:
        self.service.stop()
