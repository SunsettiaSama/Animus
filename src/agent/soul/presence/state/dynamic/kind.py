from __future__ import annotations

from enum import Enum


class Expectation(str, Enum):
    """Agent 对「用户下一话语」的立场。"""

    none = "none"
    optional = "optional"
    required = "required"
    clarify = "clarify"
    deferred = "deferred"
