from __future__ import annotations

"""对 test.workbench.speak_turing 骨架的统一转发。

评测复用其对话模拟器（盲聊用户模拟 + 控制标签泄漏检查）与图灵分类评委，
集中在一个模块 import，避免 evals 各文件散落依赖 test 包。
"""

from test.workbench.speak_turing.dataset import SpeakTuringCase, load_cases
from test.workbench.speak_turing.judge import CategoricalDialogueJudge, ProtocolVerdict
from test.workbench.speak_turing.simulation import (
    DialogueSimulator,
    DialogueTranscript,
    DialogueTurn,
    DynamicUserSimulator,
    SpeakTurnPort,
)

__all__ = [
    "CategoricalDialogueJudge",
    "DialogueSimulator",
    "DialogueTranscript",
    "DialogueTurn",
    "DynamicUserSimulator",
    "ProtocolVerdict",
    "SpeakTuringCase",
    "SpeakTurnPort",
    "load_cases",
]
