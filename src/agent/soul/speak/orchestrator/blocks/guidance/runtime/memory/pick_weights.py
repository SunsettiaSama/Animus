from __future__ import annotations

from typing import Protocol

PICK_WEIGHT_DEFAULT = 1.0
PICK_PENALTY_FACTOR = 0.38
PICK_WEIGHT_FLOOR = 0.15


class RecallPickWeightPort(Protocol):
    """会话内回忆候选抽样权重（上轮入选的 unit 下轮降权，不置零）。"""

    def recall_pick_weight(self, session_id: str, unit_id: str) -> float:
        ...

    def record_recall_pick(self, session_id: str, unit_id: str) -> None:
        ...
