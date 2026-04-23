from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class DownloadConfig:
    repo_id: str = ""
    filename: str = ""
    repo_type: str = "model"
    revision: str = "main"
    local_dir: str = ""
    token: str = ""
    endpoint: str = ""
    ignore_patterns: list[str] = field(default_factory=list)

    @classmethod
    def from_yaml(cls, path: str) -> DownloadConfig:
        import yaml

        with open(path, encoding="utf-8") as f:
            data: dict = yaml.safe_load(f) or {}
        return cls(
            repo_id=data.get("repo_id", ""),
            filename=data.get("filename", ""),
            repo_type=data.get("repo_type", "model"),
            revision=data.get("revision", "main"),
            local_dir=data.get("local_dir", ""),
            token=data.get("token", ""),
            endpoint=data.get("endpoint", ""),
            ignore_patterns=list(data.get("ignore_patterns") or []),
        )
