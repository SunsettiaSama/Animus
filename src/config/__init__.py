from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

# src/config/__init__.py  →  .parent = src/config/  →  .parent = src/  →  .parent = repo root
_REPO_ROOT: Path = Path(__file__).resolve().parent.parent.parent


class AppPaths:
    """Standard file and directory paths relative to the repository root.

    Centralises all path computation so that no other module needs to
    hard-code path fragments.  Instantiate with a custom *root* to
    override the default (useful for tests or non-standard layouts).
    """

    def __init__(self, root: Path | str | None = None) -> None:
        self.root: Path = Path(root) if root is not None else _REPO_ROOT

    # ── Config YAMLs ──────────────────────────────────────────────────────────

    @property
    def llm_config_yaml(self) -> Path:
        return self.root / "config" / "llm_core" / "config.yaml"

    @property
    def memory_config_yaml(self) -> Path:
        return self.root / "config" / "agent" / "memory.yaml"

    @property
    def long_term_config_yaml(self) -> Path:
        return self.root / "config" / "agent" / "memory" / "long_term.yaml"

    @property
    def embedding_model_yaml(self) -> Path:
        return self.root / "config" / "embedding" / "model.yaml"

    @property
    def web_search_config_yaml(self) -> Path:
        return self.root / "config" / "network" / "web_search.yaml"

    @property
    def searxng_settings_yml(self) -> Path:
        return self.root / "config" / "network" / "searxng" / "settings.yml"

    @property
    def hf_download_yaml(self) -> Path:
        return self.root / "config" / "hf_download" / "run.yaml"

    @property
    def run_config_yaml(self) -> Path:
        return self.root / "config" / "agent" / "run.yaml"

    @property
    def vllm_config_yaml(self) -> Path:
        return self.root / "config" / "llm_core" / "vllm.yaml"

    @property
    def tts_config_yaml(self) -> Path:
        return self.root / "config" / "tts" / "tts.yaml"

    @property
    def stt_config_yaml(self) -> Path:
        return self.root / "config" / "tts" / "stt.yaml"

    @property
    def sandbox_config_yaml(self) -> Path:
        return self.root / "config" / "infra" / "sandbox.yaml"

    @property
    def webui_settings_json(self) -> Path:
        return self.root / "config" / "webui" / "settings.json"

    # ── Runtime cache dirs ────────────────────────────────────────────────────

    @property
    def cache_root(self) -> Path:
        return self.root / ".react"


# Module-level singleton — import as ``from config import paths``
paths = AppPaths()


# ── AppConfig ─────────────────────────────────────────────────────────────────

@dataclass
class AppConfig:
    """Top-level config bundle.

    Usage::

        from config import AppConfig
        cfg = AppConfig.from_disk()          # load all YAML files from disk
        cfg = AppConfig.from_disk(root="/x") # custom repo root
    """

    paths: AppPaths = field(default_factory=AppPaths)
    llm: "LLMConfig" = field(default_factory=lambda: _lazy_llm())
    tao: "TaoConfig" = field(default_factory=lambda: _lazy_tao())

    @classmethod
    def from_disk(cls, root: Path | str | None = None) -> AppConfig:
        from config.storage import StorageConfig
        from config.llm_core.config import LLMConfig
        from config.agent.memory.memory_config import MemoryConfig, LongTermMemoryConfig
        from config.agent.memory.embedding_config import EmbeddingConfig
        from config.agent.tao_config import TaoConfig

        p = AppPaths(root)

        llm = LLMConfig.from_yaml(str(p.llm_config_yaml)) if p.llm_config_yaml.exists() else LLMConfig()

        storage = StorageConfig(root=str(p.cache_root))
        memory = (
            MemoryConfig.from_yaml(str(p.memory_config_yaml))
            if p.memory_config_yaml.exists()
            else MemoryConfig()
        )
        if p.long_term_config_yaml.exists():
            memory.long_term = LongTermMemoryConfig.from_yaml(str(p.long_term_config_yaml))
        if p.embedding_model_yaml.exists():
            emb = EmbeddingConfig.from_yaml(str(p.embedding_model_yaml))
            lt = memory.long_term
            lt.model_name_or_path = emb.model_name_or_path
            lt.use_fp16 = emb.use_fp16
            lt.device = emb.device
            lt.query_prefix = emb.query_prefix
            lt.passage_prefix = emb.passage_prefix
        tao = TaoConfig(storage=storage, memory=memory)

        return cls(paths=p, llm=llm, tao=tao)


def _lazy_llm():
    from config.llm_core.config import LLMConfig
    return LLMConfig()


def _lazy_tao():
    from config.agent.tao_config import TaoConfig
    return TaoConfig()


__all__ = ["AppPaths", "AppConfig", "paths"]
