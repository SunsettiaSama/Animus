from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class RiskLevel(Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"

    def __le__(self, other: "RiskLevel") -> bool:
        order = [RiskLevel.LOW, RiskLevel.MEDIUM, RiskLevel.HIGH]
        return order.index(self) <= order.index(other)

    def __lt__(self, other: "RiskLevel") -> bool:
        order = [RiskLevel.LOW, RiskLevel.MEDIUM, RiskLevel.HIGH]
        return order.index(self) < order.index(other)

    @classmethod
    def from_str(cls, value: str) -> "RiskLevel":
        mapping = {"low": cls.LOW, "medium": cls.MEDIUM, "high": cls.HIGH}
        result = mapping.get(value.lower().strip())
        if result is None:
            raise ValueError(f"未知风险级别: {value!r}，有效值：low / medium / high")
        return result


@dataclass
class OperationRisk:
    tool_name: str
    args: dict
    level: RiskLevel
    reason: str
