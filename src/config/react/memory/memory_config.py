from __future__ import annotations

from dataclasses import dataclass, field

from config.react.memory.retrieve_config import RetrieveConfig


@dataclass
class LongTermMemoryConfig:
    enabled: bool = False
    memory_dir: str = ""
    load_from_disk: bool = True
    top_k: int = 5
    model_name_or_path: str = "BAAI/bge-small-zh-v1.5"
    query_prefix: str = "query: "
    passage_prefix: str = ""
    use_fp16: bool = True
    device: str = "auto"
    consolidation_k: int = 0
    max_entry_chars: int = 2000
    max_recall_chars: int = 3000
    # Distillation: if enabled, LLM extracts a knowledge summary before writing.
    # If disabled, only the raw answer text is stored (question kept as metadata).
    distill_enabled: bool = False
    max_distill_tokens: int = 400
    retrieve: RetrieveConfig = field(default_factory=RetrieveConfig)

    @classmethod
    def from_yaml(cls, path: str) -> LongTermMemoryConfig:
        import yaml

        with open(path, encoding="utf-8") as f:
            data: dict = yaml.safe_load(f) or {}
        return cls.from_dict(data)

    @classmethod
    def from_dict(cls, d: dict) -> LongTermMemoryConfig:
        retrieve_d = d.get("retrieve", {}) or {}
        return cls(
            enabled=bool(d.get("enabled", False)),
            memory_dir=d.get("memory_dir", ""),
            load_from_disk=bool(d.get("load_from_disk", True)),
            top_k=int(d.get("top_k", 5)),
            model_name_or_path=d.get("model_name_or_path", "BAAI/bge-small-zh-v1.5"),
            query_prefix=d.get("query_prefix", "query: "),
            passage_prefix=d.get("passage_prefix", ""),
            use_fp16=bool(d.get("use_fp16", True)),
            device=d.get("device", "auto"),
            consolidation_k=int(d.get("consolidation_k", 0)),
            max_entry_chars=int(d.get("max_entry_chars", 2000)),
            max_recall_chars=int(d.get("max_recall_chars", 3000)),
            distill_enabled=bool(d.get("distill_enabled", False)),
            max_distill_tokens=int(d.get("max_distill_tokens", 400)),
            retrieve=RetrieveConfig.from_dict(retrieve_d),
        )


@dataclass
class MemoryConfig:
    short_term: "ShortTermMemoryConfig" = field(
        default_factory=lambda: _import_short_term()
    )
    medium_term: "MediumTermMemoryConfig" = field(
        default_factory=lambda: _import_medium_term()
    )
    long_term: LongTermMemoryConfig = field(default_factory=LongTermMemoryConfig)
    milestone: "MilestoneConfig" = field(
        default_factory=lambda: _import_milestone()
    )

    @classmethod
    def from_yaml(cls, path: str) -> MemoryConfig:
        import yaml

        with open(path, encoding="utf-8") as f:
            data: dict = yaml.safe_load(f) or {}
        return cls.from_dict(data)

    @classmethod
    def from_dict(cls, data: dict) -> MemoryConfig:
        from config.react.memory.short_term_config import ShortTermMemoryConfig
        from config.react.memory.medium_term_config import MediumTermMemoryConfig
        from config.react.memory.milestone_config import MilestoneConfig

        return cls(
            short_term=ShortTermMemoryConfig.from_dict(data.get("short_term", {}) or {}),
            medium_term=MediumTermMemoryConfig.from_dict(data.get("medium_term", {}) or {}),
            long_term=LongTermMemoryConfig.from_dict(data.get("long_term", {}) or {}),
            milestone=MilestoneConfig.from_dict(data.get("milestone", {}) or {}),
        )


def _import_short_term():
    from config.react.memory.short_term_config import ShortTermMemoryConfig
    return ShortTermMemoryConfig()


def _import_medium_term():
    from config.react.memory.medium_term_config import MediumTermMemoryConfig
    return MediumTermMemoryConfig()


def _import_milestone():
    from config.react.memory.milestone_config import MilestoneConfig
    return MilestoneConfig()
