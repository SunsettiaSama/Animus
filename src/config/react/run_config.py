from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass
class _WebUIConfig:
    host: str = "127.0.0.1"
    port: int = 8300


@dataclass
class _SearXNGConfig:
    container_name: str = "react-searxng"
    image: str = "searxng/searxng"
    host_port: int = 8888
    container_port: int = 8080


@dataclass
class RunConfig:
    webui: _WebUIConfig = None
    searxng: _SearXNGConfig = None

    def __post_init__(self) -> None:
        if self.webui is None:
            self.webui = _WebUIConfig()
        if self.searxng is None:
            self.searxng = _SearXNGConfig()

    @classmethod
    def load(cls, path: str | None = None) -> RunConfig:
        if path is None:
            from config import paths
            path = str(paths.run_config_yaml)

        if not os.path.exists(path):
            return cls()

        import yaml

        with open(path, encoding="utf-8") as f:
            data: dict = yaml.safe_load(f) or {}

        w = data.get("webui", {}) or {}
        s = data.get("searxng", {}) or {}

        return cls(
            webui=_WebUIConfig(
                host=w.get("host", "127.0.0.1"),
                port=int(w.get("port", 8300)),
            ),
            searxng=_SearXNGConfig(
                container_name=s.get("container_name", "react-searxng"),
                image=s.get("image", "searxng/searxng"),
                host_port=int(s.get("host_port", 8888)),
                container_port=int(s.get("container_port", 8080)),
            ),
        )
