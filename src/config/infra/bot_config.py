from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class BotConfig:
    transport: str = "forward_ws"
    ws_url: str = "ws://127.0.0.1:3001"
    access_token: str = ""
    reconnect_interval_sec: float = 5.0
    allowed_private_users: list[int] = field(default_factory=list)
    allowed_groups: list[int] = field(default_factory=list)
    command_prefix: str = ""
    max_sessions: int = 100
    session_ttl_hours: float = 24.0

    @classmethod
    def load(cls, path: str | Path | None = None) -> BotConfig:
        import yaml

        if path is None:
            from config import paths
            path = paths.root / "config" / "infra" / "bot_config.yaml"

        path = Path(path)
        if not path.exists():
            return cls()
        with open(path, encoding="utf-8") as f:
            data: dict = yaml.safe_load(f) or {}
        return cls(
            transport=str(data.get("transport", "forward_ws")),
            ws_url=str(data.get("ws_url", "ws://127.0.0.1:3001")),
            access_token=str(data.get("access_token", "")),
            reconnect_interval_sec=float(data.get("reconnect_interval_sec", 5.0)),
            allowed_private_users=[
                int(x) for x in data.get("allowed_private_users") or []
            ],
            allowed_groups=[
                int(x) for x in data.get("allowed_groups") or []
            ],
            command_prefix=str(data.get("command_prefix", "")),
            max_sessions=int(data.get("max_sessions", 100)),
            session_ttl_hours=float(data.get("session_ttl_hours", 24.0)),
        )
