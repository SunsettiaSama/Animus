from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass
class BarkConfig:
    enabled: bool = False
    server_url: str = "https://api.day.app"
    device_key: str = ""
    sound: str = ""
    group: str = "ReAct"

    def to_yaml(self, path: str | Path) -> None:
        import yaml
        import os
        path = Path(path)
        os.makedirs(path.parent, exist_ok=True)
        data = {
            "enabled":    self.enabled,
            "server_url": self.server_url,
            "device_key": self.device_key,
            "sound":      self.sound,
            "group":      self.group,
        }
        with open(path, "w", encoding="utf-8") as f:
            yaml.safe_dump(data, f, allow_unicode=True)

    @classmethod
    def load(cls, path: str | Path | None = None) -> BarkConfig:
        import yaml
        if path is None:
            from config import paths
            path = paths.bark_config_yaml
        path = Path(path)
        if not path.exists():
            return cls()
        with open(path, encoding="utf-8") as f:
            data: dict = yaml.safe_load(f) or {}
        return cls(
            enabled=bool(data.get("enabled", False)),
            server_url=str(data.get("server_url", "https://api.day.app")),
            device_key=str(data.get("device_key", "")),
            sound=str(data.get("sound", "")),
            group=str(data.get("group", "ReAct")),
        )
