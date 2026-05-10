from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass
class NtfyConfig:
    enabled: bool = False
    server_url: str = "https://ntfy.sh"
    topic: str = ""
    username: str = ""
    password: str = ""
    priority: int = 3   # 1(min) ~ 5(urgent)

    def to_yaml(self, path: str | Path) -> None:
        import yaml
        import os
        path = Path(path)
        os.makedirs(path.parent, exist_ok=True)
        data = {
            "enabled":    self.enabled,
            "server_url": self.server_url,
            "topic":      self.topic,
            "username":   self.username,
            "password":   self.password,
            "priority":   self.priority,
        }
        with open(path, "w", encoding="utf-8") as f:
            yaml.safe_dump(data, f, allow_unicode=True)

    @classmethod
    def load(cls, path: str | Path | None = None) -> NtfyConfig:
        import yaml
        if path is None:
            from config import paths
            path = paths.ntfy_config_yaml
        path = Path(path)
        if not path.exists():
            return cls()
        with open(path, encoding="utf-8") as f:
            data: dict = yaml.safe_load(f) or {}
        return cls(
            enabled=bool(data.get("enabled", False)),
            server_url=str(data.get("server_url", "https://ntfy.sh")),
            topic=str(data.get("topic", "")),
            username=str(data.get("username", "")),
            password=str(data.get("password", "")),
            priority=int(data.get("priority", 3)),
        )
