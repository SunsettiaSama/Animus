from __future__ import annotations

from react.action.risk.level import RiskLevel


class AllowList:
    """
    Static per-tool risk-level override.

    When a tool name appears in the allow list its risk level is forced to the
    configured value, bypassing the assessor entirely.  This lets users
    permanently trust specific tools without editing rule tables.
    """

    def __init__(self, entries: dict[str, str] | None = None) -> None:
        self._entries: dict[str, RiskLevel] = {}
        if entries:
            for name, level_str in entries.items():
                self._entries[name] = RiskLevel.from_str(level_str)

    def get(self, tool_name: str) -> RiskLevel | None:
        return self._entries.get(tool_name)

    def set(self, tool_name: str, level: RiskLevel) -> None:
        self._entries[tool_name] = level

    def remove(self, tool_name: str) -> None:
        self._entries.pop(tool_name, None)

    def to_dict(self) -> dict[str, str]:
        return {name: level.value for name, level in self._entries.items()}
