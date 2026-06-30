from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from storyview.types import SceneGroundingPolicy, SceneGroundingResult

from ..contracts import ChronicleLookupPort, JournalLookupPort, MemoryRecallPort
from ..legacy.journal import LifeJournal
from ...chronicle import VirtualChronicleStore


class LifeJournalLookupAdapter:
    def __init__(self, journal: LifeJournal) -> None:
        self._journal = journal

    def recent_done(self, *, limit: int = 5) -> list[str]:
        return self._journal.recent_done_intent_lines(limit)

    def digest(self, *, days: int = 7) -> str:
        return self._journal.to_digest()

    def all_intents(self) -> list[str]:
        return [
            lm.intention.strip()
            for lm in self._journal.all_landmarks()
            if lm.intention.strip()
        ]


class VirtualChronicleLookupAdapter:
    def __init__(
        self,
        chronicle: VirtualChronicleStore,
        hot_supplier: Callable[..., list] | None = None,
    ) -> None:
        self._chronicle = chronicle
        self._hot_supplier = hot_supplier

    def recent_entries(self, *, tail: int = 20) -> list[str]:
        entries = self._chronicle.recent(n=tail)
        lines: list[str] = []
        for entry in entries:
            text = entry.summary.strip()
            if text:
                lines.append(text)
        return lines

    def hot_experiences(self, *, hours: int = 48) -> list[str]:
        if self._hot_supplier is None:
            return []
        raw = self._hot_supplier(hours=hours)
        lines: list[str] = []
        for item in raw:
            if isinstance(item, dict):
                text = str(item.get("narration", "")).strip() or str(
                    item.get("hint", "")
                ).strip()
            else:
                text = str(item).strip()
            if text:
                lines.append(text)
        return lines


class StorySceneGroundingPort:
    def ground_scene_for_cue(
        self,
        cue: str,
        *,
        policy: SceneGroundingPolicy | None = None,
    ) -> SceneGroundingResult:
        raise NotImplementedError


@dataclass(frozen=True)
class AgendaToolBundle:
    memory: MemoryRecallPort
    journal: JournalLookupPort
    chronicle: ChronicleLookupPort
    scene_grounding: StorySceneGroundingPort | None = None

    def recall_memory(self, query: str) -> list[str]:
        return self.memory.recall(query)

    def inspect_journal(self) -> str:
        done = self.journal.recent_done(limit=5)
        digest = self.journal.digest(days=7)
        intents = self.journal.all_intents()
        parts = ["【近期已完成地标意图】"]
        parts.extend(f"- {line}" for line in done or ["（无）"])
        parts.append("【手账摘要】")
        parts.append(digest.strip() or "（无）")
        parts.append("【全部地标意图（避免重复）】")
        parts.extend(f"- {line}" for line in intents[-8:] or ["（无）"])
        return "\n".join(parts)

    def inspect_chronicle(self) -> str:
        recent = self.chronicle.recent_entries(tail=12)
        hot = self.chronicle.hot_experiences(hours=48)
        parts = ["【近期虚拟 chronicle】"]
        parts.extend(f"- {line}" for line in recent or ["（无）"])
        parts.append("【近期 hot 体验】")
        parts.extend(f"- {line}" for line in hot or ["（无）"])
        return "\n".join(parts)

    def ground_scene(self, cue: str) -> SceneGroundingResult:
        if self.scene_grounding is None:
            raise RuntimeError("StorySceneGroundingPort not wired")
        return self.scene_grounding.ground_scene_for_cue(cue)

    def scene_grounding_context(self, result: SceneGroundingResult) -> str:
        if result.blocked:
            return f"【场景绑定失败】{result.blocked_reason}"
        lines = [
            f"【绑定 scene_id】{result.scene_id}",
            f"【绑定 scene_name】{result.scene_name}",
            f"【scene narrative】{result.narrative[:240]}",
        ]
        if result.cards:
            lines.append("【scene cards】")
            for card in result.cards:
                lines.append(f"- {card.title}：{card.description[:100]}")
        if result.trace:
            lines.append("【grounding trace】")
            for entry in result.trace:
                lines.append(f"- R{entry.round} {entry.action}: {entry.observation[:120]}")
        return "\n".join(lines)
