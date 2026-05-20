"""对话 — Agent 与外界交互的一种形式（与 virtual_world / drone / robot_dog 并列）。"""

from .kernel import DialogueKernel
from .port import DialoguePort

__all__ = [
    "DialogueKernel",
    "DialoguePort",
]
