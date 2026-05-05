from __future__ import annotations

from typing import TYPE_CHECKING

from config.agent.memory.milestone_config import MilestoneConfig
from ...memory.memory import Step
from ...memory.milestone.entry import MilestoneEntry
from ...memory.milestone.retriever import MilestoneRetriever
from ...memory.milestone.scorer import ImportanceScorer
from ...memory.milestone.store import MilestoneStore

if TYPE_CHECKING:
    from llm_core.llm import BaseLLM


def _fmt_ts(iso: str) -> str:
    return iso[:16].replace("T", " ") + " UTC"


class MilestoneMemory:
    """L2 里程碑记忆：按需检索，不自动全量注入上下文。"""

    def __init__(
        self,
        store: MilestoneStore,
        cfg: MilestoneConfig,
        llm: BaseLLM | None = None,
    ) -> None:
        self._store = store
        self._cfg = cfg
        self._retriever = MilestoneRetriever()
        self._scorer: ImportanceScorer | None = (
            ImportanceScorer(llm, cfg) if llm is not None else None
        )

    def retrieve(self, query: str) -> str:
        """Return relevant milestones for the query formatted as prompt text.

        When ``cfg.inject_detail`` is True the full Q&A detail is included
        beneath each summary line; otherwise only the one-line summary is shown.

        Returns empty string when no matches are found.
        """
        hits = self._retriever.retrieve(
            self._store.entries, query, self._cfg.top_k_retrieve
        )
        if not hits:
            return ""

        parts = [self._cfg.prompt_header]
        for e in hits:
            ts = _fmt_ts(e.created_at)
            emotion_tag = f"[{e.emotion}]" if e.emotion != "neutral" else ""
            header = f"[{ts}]{emotion_tag} {e.summary}"
            if self._cfg.inject_detail and e.detail:
                parts.append(header)
                parts.append(e.detail)
                parts.append("")          # blank line between entries
            else:
                parts.append(header)

        return "\n".join(parts).rstrip()

    def try_add(
        self,
        question: str,
        answer: str,
        steps: list[Step],
    ) -> tuple[bool, list[MilestoneEntry]]:
        """Score importance and add to store if above threshold.

        Returns:
            (was_added, evicted_entries)
            ``evicted_entries`` is the list of entries displaced from the store
            due to capacity overflow; callers should migrate them to L3.
        """
        if self._scorer is None:
            return False, []
        entry = self._scorer.score(question, answer, steps)
        if entry is None:
            return False, []
        evicted = self._store.add(entry)
        return True, evicted

    def save(self) -> None:
        self._store.save()

    @property
    def store(self) -> MilestoneStore:
        return self._store
