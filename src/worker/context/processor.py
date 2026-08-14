from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from config.agent.memory.memory_config import MemoryConfig
from .medium_term.memory import RecentHistoryMemory
from .memory import Step

if TYPE_CHECKING:
    from infra.llm import LLM


@dataclass
class MemoryResult:
    short_term: list[Step] = field(default_factory=list)
    medium_term: str = ""


class MemoryProcessor:
    """会话上下文处理器，仅负责当前会话范围内的信息。

    - short_term：当前问题下的步骤轨迹（工作记忆）
    - medium_term：近期对话摘要窗口（会话情节记忆）

    长期记忆的读取由 memory_recall 工具主动触发；
    长期记忆的写入由 Life.record_turn → 体验擢升 → MemoryService.ingest_experience 完成。
    """

    def __init__(
        self,
        cfg: MemoryConfig,
        llm: LLM | None = None,
        medium_term: RecentHistoryMemory | None = None,
    ):
        self._cfg = cfg
        self._llm = llm
        self._trace: list[Step] = []

        self._medium: RecentHistoryMemory | None = medium_term
        if self._medium is None and cfg.medium_term.enabled:
            self._medium = RecentHistoryMemory(cfg.medium_term, llm=llm)

    def add(self, step: Step) -> None:
        self._trace.append(step)

    def recall(self, query: str = "") -> MemoryResult:
        """返回当前会话的上下文（工作记忆 + 近期对话摘要）。

        长期记忆不在此处读取——由 Agent 通过 memory_recall 工具主动激活。
        """
        medium_text = self._medium.render() if self._medium is not None else ""
        return MemoryResult(short_term=list(self._trace), medium_term=medium_text)

    def commit(self, question: str, answer: str) -> None:
        """轮结束后追加近期对话摘要窗口。在 post_process() 后台线程中调用。"""
        if self._medium is not None:
            self._medium.append(question, answer)

    def clear(self) -> None:
        self._trace.clear()

    @property
    def trace(self) -> list[Step]:
        return list(self._trace)
