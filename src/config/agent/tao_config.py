from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from config.storage import StorageConfig
from config.agent.memory.memory_config import MemoryConfig
from config.agent.persona_config import PersonaConfig
from config.agent.prompt_config import PromptConfig
from config.agent.trace_config import TraceConfig
from config.infra.db_config import DBConfig

if TYPE_CHECKING:
    from config.knowledge.config import KnowledgeConfig
    from config.llm_core.config import LLMConfig
    from runtime.scheduler.config import SchedulerConfig
    from agent.profile import SubAgentConfig
    from agent.flow.cluster.config import FlowConfig


@dataclass
class TaoConfig:
    max_steps: int = 10
    storage: StorageConfig = field(default_factory=StorageConfig)
    prompt: PromptConfig = field(default_factory=PromptConfig)
    memory: MemoryConfig = field(default_factory=MemoryConfig)
    persona: PersonaConfig = field(default_factory=PersonaConfig)
    trace: TraceConfig = field(default_factory=TraceConfig)
    knowledge: KnowledgeConfig | None = field(default=None)
    repair_llm: LLMConfig | None = field(default=None)
    scheduler: SchedulerConfig | None = field(default=None)
    agent: SubAgentConfig | None = field(default=None)
    flow: FlowConfig | None = field(default=None)
    db: DBConfig | None = field(default=None)

    def __post_init__(self) -> None:
        self._propagate_dirs()

    def _propagate_dirs(self) -> None:
        if not self.memory.medium_term.memory_dir:
            self.memory.medium_term.memory_dir = self.storage.memory_dir
        if not self.memory.long_term.memory_dir:
            self.memory.long_term.memory_dir = self.storage.memory_dir
        if not self.memory.milestone.milestone_dir:
            self.memory.milestone.milestone_dir = self.storage.milestones_dir
        if not self.persona.persona_dir:
            self.persona.persona_dir = self.storage.persona_dir
        if not self.trace.trace_dir:
            self.trace.trace_dir = self.storage.traces_dir
