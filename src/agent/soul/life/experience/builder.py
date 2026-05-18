from __future__ import annotations

from typing import TYPE_CHECKING

from .unit import (
    ExperienceAction,
    ExperienceActionKind,
    ExperienceFeeling,
    ExperienceSituation,
    ExperienceUnit,
)
from ..orchestrator import ExperienceOrchestrator

if TYPE_CHECKING:
    from ..chronicle.store import ChronicleStore


class ExperienceBuilder:
    """体验单元构造器——即时层（先验）。

    职责
    ----
    接收来自 TaoLoop / 故事引擎的原始输入，构造 ``ExperienceUnit``，
    写入热存储（via Orchestrator）并追加 Chronicle（客观事实账本）。

    ``ExperienceBuilder`` 不理解叙事，不推断意义。
    ``prior_thought`` 由调用方传入（通常从 ``LifeJournal.active_focus()`` 取得）。

    调用方式
    --------
    由 ``LifeService.enqueue_*`` 在后台线程中调用，不阻塞 TaoLoop 主路。
    """

    def __init__(
        self,
        orchestrator: ExperienceOrchestrator,
        chronicle_store: ChronicleStore | None = None,
    ) -> None:
        self._orchestrator = orchestrator
        self._chronicle_store = chronicle_store

    @property
    def orchestrator(self) -> ExperienceOrchestrator:
        return self._orchestrator

    # ── 用户交互路径 ──────────────────────────────────────────────────────────

    def record_user_turn(
        self,
        session_id: str,
        turn_index: int,
        user_text: str,
        agent_reply: str,
        prior_thought: str = "",
        salience: float = 0.3,
        emotion_label: str = "",
        valence_delta: float = 0.0,
        arousal_delta: float = 0.0,
        activated_memory_ids: list[str] | None = None,
    ) -> ExperienceUnit:
        unit = ExperienceUnit.make(
            situation=ExperienceSituation(
                session_id=session_id,
                turn_index=turn_index,
                perception=user_text,
                narration=agent_reply,
                prior_thought=prior_thought,
                activated_memory_ids=activated_memory_ids or [],
            ),
            action=ExperienceAction(
                kind=ExperienceActionKind.speaking,
                content=agent_reply,
            ),
            feeling=ExperienceFeeling(
                valence_delta=valence_delta,
                arousal_delta=arousal_delta,
                salience=salience,
                emotion_label=emotion_label,
            ),
            source="user",
        )
        self._orchestrator.ingest(unit)
        self._append_chronicle_user_turn(unit, user_text, agent_reply, salience, emotion_label)
        return unit

    # ── 故事引擎路径 ──────────────────────────────────────────────────────────

    def record_story_beat(
        self,
        narrative_hint: str,
        emotion_label: str = "",
        valence_delta: float = 0.0,
        arousal_delta: float = 0.0,
        salience: float = 0.0,
        action_kind: ExperienceActionKind = ExperienceActionKind.reasoning,
    ) -> ExperienceUnit:
        unit = ExperienceUnit.make(
            situation=ExperienceSituation(
                narration=narrative_hint,
            ),
            action=ExperienceAction(
                kind=action_kind,
                content=narrative_hint,
            ),
            feeling=ExperienceFeeling(
                valence_delta=valence_delta,
                arousal_delta=arousal_delta,
                salience=salience,
                emotion_label=emotion_label,
            ),
            source="narrative",
        )
        self._orchestrator.ingest(unit)
        self._append_chronicle_story_beat(unit, narrative_hint, salience, emotion_label)
        return unit

    # ── 意外事件路径 ──────────────────────────────────────────────────────────

    def record_surprise(
        self,
        narrative_hint: str,
        dice_value: int = 0,
        dice_tendency: str = "",
        salience: float = 0.5,
    ) -> ExperienceUnit:
        """意外事件触发：构造 source="surprise" 的体验单元并写入热存储 + Chronicle。"""
        unit = ExperienceUnit.make(
            situation=ExperienceSituation(
                narration=narrative_hint,
            ),
            action=ExperienceAction(
                kind=ExperienceActionKind.attending,
                content=narrative_hint,
            ),
            feeling=ExperienceFeeling(salience=salience),
            source="surprise",
        )
        self._orchestrator.ingest(unit)
        self._append_chronicle_surprise(unit, narrative_hint, salience, dice_tendency)
        return unit

    # ── 心跳代理 ──────────────────────────────────────────────────────────────

    def tick(self) -> list[ExperienceUnit]:
        """代理 Orchestrator 的心跳批处理（扫描 + 擢升 + 清仓）。"""
        return self._orchestrator.tick()

    # ── Chronicle 写入 ────────────────────────────────────────────────────────

    def _append_chronicle_user_turn(
        self,
        unit: ExperienceUnit,
        user_text: str,
        agent_reply: str,
        salience: float,
        emotion_label: str,
    ) -> None:
        if self._chronicle_store is None:
            return
        from ..chronicle.entry import ChronicleEntry, ChronicleKind
        summary = f"用户：{user_text[:40]}  →  Agent：{agent_reply[:40]}"
        self._chronicle_store.append(ChronicleEntry(
            kind=ChronicleKind.user_turn,
            summary=summary,
            session_id=unit.situation.session_id,
            turn_index=unit.situation.turn_index,
            emotion_label=emotion_label,
            salience=salience,
            experience_id=unit.id,
        ))

    def _append_chronicle_story_beat(
        self,
        unit: ExperienceUnit,
        narrative_hint: str,
        salience: float,
        emotion_label: str,
    ) -> None:
        if self._chronicle_store is None:
            return
        from ..chronicle.entry import ChronicleEntry, ChronicleKind
        self._chronicle_store.append(ChronicleEntry(
            kind=ChronicleKind.story_beat,
            summary=narrative_hint[:80],
            emotion_label=emotion_label,
            salience=salience,
            experience_id=unit.id,
        ))

    def _append_chronicle_surprise(
        self,
        unit: ExperienceUnit,
        narrative_hint: str,
        salience: float,
        dice_tendency: str,
    ) -> None:
        if self._chronicle_store is None:
            return
        from ..chronicle.entry import ChronicleEntry, ChronicleKind
        summary = narrative_hint[:60]
        if dice_tendency:
            summary = f"{summary}（{dice_tendency}）"
        self._chronicle_store.append(ChronicleEntry(
            kind=ChronicleKind.surprise,
            summary=summary,
            salience=salience,
            experience_id=unit.id,
        ))
