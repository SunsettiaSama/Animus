from __future__ import annotations

import os
from dataclasses import dataclass, field

from config.storage import StorageConfig
from config.llm_core.config import LLMConfig
from config.agent.tao_config import TaoConfig


@dataclass
class AppConfig:
    storage: StorageConfig = field(default_factory=StorageConfig)
    llm: LLMConfig = field(default_factory=lambda: LLMConfig(model=""))
    react: TaoConfig = field(default_factory=TaoConfig)

    @classmethod
    def from_dict(cls, data: dict, base_dir: str | None = None) -> AppConfig:
        storage_data = dict(data.get("cache", {}))
        root = storage_data.get("root", ".react")
        if base_dir and not os.path.isabs(root):
            root = os.path.join(base_dir, root)
        storage_data["root"] = root
        storage = StorageConfig.from_dict(storage_data)

        llm = LLMConfig.from_dict(data.get("llm", {}))
        react = TaoConfig.from_dict(data.get("react", {}), storage=storage)
        return cls(storage=storage, llm=llm, react=react)

    @classmethod
    def load(cls, path: str, base_dir: str | None = None) -> AppConfig:
        _base = base_dir or os.path.dirname(os.path.abspath(path))
        if not os.path.exists(path):
            return cls.from_dict({}, base_dir=_base)
        import yaml

        with open(path, encoding="utf-8") as f:
            data: dict = yaml.safe_load(f) or {}
        return cls.from_dict(data, base_dir=_base)

    @staticmethod
    def update_section(yaml_path: str, section: str, data: dict) -> None:
        import yaml

        existing: dict = {}
        if os.path.exists(yaml_path):
            with open(yaml_path, encoding="utf-8") as f:
                existing = yaml.safe_load(f) or {}
        existing[section] = data
        os.makedirs(os.path.dirname(os.path.abspath(yaml_path)), exist_ok=True)
        with open(yaml_path, "w", encoding="utf-8") as f:
            yaml.dump(existing, f, allow_unicode=True, default_flow_style=False)
