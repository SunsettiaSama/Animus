"""拟人度管线：多轮对话模拟 × 记忆基座（与检索评测管线职能分离）。"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .judge_dialogue import (
        DIALOGUE_DIMENSIONS, ExpertDialogueJudge, HeuristicDialogueJudge,
    )
    from .persona import PERSONA_ID, PERSONA_NAME, PERSONA_PROFILE, USER_SIDE_BRIEF
    from .scenarios import Scenario, build_scenarios, load_scenarios, validate_scenarios
    from .simulator import DialogueRecord, DialogueSimulator, LLMUser, ScriptedUser

_LAZY: dict[str, tuple[str, str]] = {
    "PERSONA_ID": ("evals.memory_humaneness.dialogue.persona", "PERSONA_ID"),
    "PERSONA_NAME": ("evals.memory_humaneness.dialogue.persona", "PERSONA_NAME"),
    "PERSONA_PROFILE": ("evals.memory_humaneness.dialogue.persona", "PERSONA_PROFILE"),
    "USER_SIDE_BRIEF": ("evals.memory_humaneness.dialogue.persona", "USER_SIDE_BRIEF"),
    "Scenario": ("evals.memory_humaneness.dialogue.scenarios", "Scenario"),
    "build_scenarios": ("evals.memory_humaneness.dialogue.scenarios", "build_scenarios"),
    "load_scenarios": ("evals.memory_humaneness.dialogue.scenarios", "load_scenarios"),
    "validate_scenarios": ("evals.memory_humaneness.dialogue.scenarios", "validate_scenarios"),
    "DialogueRecord": ("evals.memory_humaneness.dialogue.simulator", "DialogueRecord"),
    "DialogueSimulator": ("evals.memory_humaneness.dialogue.simulator", "DialogueSimulator"),
    "ScriptedUser": ("evals.memory_humaneness.dialogue.simulator", "ScriptedUser"),
    "LLMUser": ("evals.memory_humaneness.dialogue.simulator", "LLMUser"),
    "ExpertDialogueJudge": ("evals.memory_humaneness.dialogue.judge_dialogue", "ExpertDialogueJudge"),
    "HeuristicDialogueJudge": ("evals.memory_humaneness.dialogue.judge_dialogue", "HeuristicDialogueJudge"),
    "DIALOGUE_DIMENSIONS": ("evals.memory_humaneness.dialogue.judge_dialogue", "DIALOGUE_DIMENSIONS"),
}

__all__ = list(_LAZY)


def __getattr__(name: str):
    entry = _LAZY.get(name)
    if entry is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    import importlib

    module_name, attr = entry
    value = getattr(importlib.import_module(module_name), attr)
    globals()[name] = value
    return value
