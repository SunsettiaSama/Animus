from __future__ import annotations

from typing import Any, Protocol


class DronePort(Protocol):
    """无人机交互通道（占位）。"""

    def connect(self, session_id: str, device_id: str) -> None: ...

    def send_command(self, session_id: str, command: dict[str, Any]) -> None: ...

    def read_telemetry(self, session_id: str) -> dict[str, Any]: ...

    def disconnect(self, session_id: str) -> None: ...
