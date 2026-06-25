from __future__ import annotations

from dataclasses import dataclass

from infra.llm import BaseLLM

DIRECTOR_AUX_NAME = "speak_director"
DIRECTOR_TIMEOUT_SEC = 8.0
DIRECTOR_MAX_CONCURRENT = 4


@dataclass(frozen=True)
class DirectorLLMChannelConfig:
    aux_name: str = DIRECTOR_AUX_NAME
    timeout_sec: float = DIRECTOR_TIMEOUT_SEC
    max_concurrent: int = DIRECTOR_MAX_CONCURRENT


def build_director_llm_caller(llm: BaseLLM | None) -> "DirectorLLMCaller":
    from agent.soul.speak.pipelines.request_driven.orchestrator.directors.base import DirectorLLMCaller

    return DirectorLLMCaller(
        llm=llm,
        timeout_sec=DIRECTOR_TIMEOUT_SEC,
        max_concurrent=DIRECTOR_MAX_CONCURRENT,
    )
