"""FSM 初始化转移：起床 / 休眠。"""

from .result import SleepResult, WakeResult
from .sleep import apply_sleep
from .wake import PresenceWakeEngine, WakeContext

__all__ = [
    "PresenceWakeEngine",
    "SleepResult",
    "WakeContext",
    "WakeResult",
    "apply_sleep",
]
