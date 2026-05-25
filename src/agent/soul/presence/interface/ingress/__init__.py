"""interface 入站：trigger / capture / 演化冲动。"""

from .evolution import apply_evolution_impulse
from .facade import PresenceInterface
from .result import PresenceTriggerResult

__all__ = [
    "PresenceInterface",
    "PresenceTriggerResult",
    "apply_evolution_impulse",
]
