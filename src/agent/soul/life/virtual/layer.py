from __future__ import annotations

from datetime import datetime
from typing import Callable

from infra.llm import BaseLLM

from agent.soul.heartbeat.bridge import MemoryHeartbeatResult

from ..experience import ExperienceBuilder, ExperienceActionKind, ExperienceUnit
from ..narrative_context import (
    NarrativeContextSupplier,
    NarrativePurpose,
    StoryWorldContextSupplier,
)
from .chronicle import VirtualChronicleStore
from storyview.port import StoryPort
from storyview.types import (
    ArcStartPolicy,
    GMAnswer,
    GMExchange,
    GMQuestion,
    SceneGroundingPolicy,
    StoryBeatOutcome,
    StoryEventKind,
)
from .journal.filler import LandmarkFiller, NullLandmarkFiller
from .journal.item import Landmark, LandmarkStatus
from .journal.journal import LifeJournal
from .journal.store import JournalStore
from .journal.agenda import LandmarkAgenda, LandmarkAgendaStore, build_landmark_agenda_public_cue
from .journal.contracts import LandmarkAgendaDraftResult, LandmarkAgendaPreviewResult
from .journal.planner import JournalPlanner
from .narrative import NarrativeEngine
from .narrative.engine import NarrativeDraft
from agent.soul.life.experience.domain.virtual_codec import VirtualUnitContext, VirtualUnitTrigger
from agent.soul.life.virtual.episode.builder import (
    attach_episode_memory_drafts,
    build_landmark_episode,
)
from .surprise.generator import NullSurpriseGenerator, SurpriseGenerator


class VirtualLayer:
    """虚拟层：故事驱动、手账地标、命运骰与意外事件。

    所有经本层写入的体验单元 ``source`` 为 ``narrative`` 或 ``surprise``，
    仍走同一 ``ExperienceBuilder`` → ``ExperienceOrchestrator`` 链路。
    """

    def __init__(
        self,
        builder: ExperienceBuilder | None,
        life_dir: str,
        llm: BaseLLM | None = None,
        chronicle: VirtualChronicleStore | None = None,
    ) -> None:
        self._builder = builder
        self._llm = llm
        self._chronicle = chronicle or VirtualChronicleStore(life_dir)
        self._journal_store = JournalStore(life_dir)
        self._journal: LifeJournal = self._journal_store.load()
        self._agenda_store = LandmarkAgendaStore(life_dir)
        self._hot_experience_supplier: Callable[..., list] | None = None
        self._journal_planner = JournalPlanner(
            self,
            self._agenda_store,
            hot_experience_supplier=lambda **kwargs: self._hot_experiences(**kwargs),
        )
        self._narrative: NarrativeEngine | None = (
            NarrativeEngine(llm) if llm is not None else None
        )
        self._filler: LandmarkFiller = (
            self._narrative if self._narrative is not None else NullLandmarkFiller()
        )
        self._surprise_generator: SurpriseGenerator = (
            self._narrative if self._narrative is not None else NullSurpriseGenerator()
        )
        self._profile_narrative = ""
        self._continuity_memories: list[str] = []
        self._world_background = ""
        self._context_supplier: NarrativeContextSupplier | None = None
        self._world_context_supplier: StoryWorldContextSupplier | None = None
        self._story_port: StoryPort | None = None
        self._gm_answerer: Callable[[GMQuestion], str] | None = None
        self._story_arc_max_steps = 3
        self._story_start_policy = ArcStartPolicy.history
        self._scene_grounding_policy: SceneGroundingPolicy | None = None
        self._world_id: str = "default"
        self._bound_scene_id: str = ""
        self._bound_scene_name: str = ""
        self._bound_scene_cards: list[dict] = []

    @property
    def builder(self) -> ExperienceBuilder:
        if self._builder is None:
            raise RuntimeError("VirtualLayer builder not attached — wire presence/experience first")
        return self._builder

    def set_builder(self, builder: ExperienceBuilder) -> None:
        self._builder = builder

    @property
    def chronicle(self) -> VirtualChronicleStore:
        return self._chronicle

    @property
    def journal(self) -> LifeJournal:
        return self._journal

    @property
    def narrative(self) -> NarrativeEngine | None:
        return self._narrative

    @property
    def profile_narrative(self) -> str:
        return self._profile_narrative

    @property
    def continuity_memories(self) -> list[str]:
        return self._continuity_memories

    @property
    def world_background(self) -> str:
        return self._world_background

    @property
    def surprise_probability(self) -> float:
        if self._story_port is None:
            return 0.0
        return self._story_port.surprise_probability(self._world_id)

    @property
    def journal_planner(self) -> JournalPlanner:
        return self._journal_planner

    @property
    def agenda_store(self) -> LandmarkAgendaStore:
        return self._agenda_store

    def require_llm(self) -> BaseLLM:
        if self._llm is None:
            raise RuntimeError("LLM not wired — agenda drafting requires an LLM")
        return self._llm

    def set_hot_experience_supplier(
        self,
        supplier: Callable[..., list] | None,
    ) -> None:
        self._hot_experience_supplier = supplier
        self._journal_planner = JournalPlanner(
            self,
            self._agenda_store,
            hot_experience_supplier=supplier,
        )

    def _hot_experiences(self, *, hours: int = 48) -> list:
        if self._hot_experience_supplier is None:
            return []
        return self._hot_experience_supplier(hours=hours)

    def compose_landmark_agenda_for_tomorrow(
        self,
        *,
        target_date: str | None = None,
        save: bool = True,
    ) -> LandmarkAgendaDraftResult:
        result = self._journal_planner.compose_draft(target_date=target_date)
        if save:
            self._journal_planner.save_agenda(result.agenda)
        return result

    def save_landmark_agenda(self, agenda: LandmarkAgenda) -> None:
        self._journal_planner.save_agenda(agenda)

    def latest_landmark_agendas(self, *, limit: int = 10) -> list[LandmarkAgenda]:
        return self._journal_planner.latest_agendas(limit=limit)

    def preview_landmark_agenda_story(
        self,
        agenda: LandmarkAgenda,
    ) -> LandmarkAgendaPreviewResult:
        if not agenda.scene_id.strip():
            raise RuntimeError("LandmarkAgenda missing scene_id — preview requires grounded scene")
        public_cue = build_landmark_agenda_public_cue(agenda)
        port = self._require_story_port()
        question = port.ask_gm_at_scene(
            self._world_id,
            agenda.scene_id,
            public_cue,
            kind=StoryEventKind.landmark,
        )
        fallback = agenda.steps[0] if agenda.steps else agenda.summary
        answer = self._answer_gm_question(question, fallback=fallback)
        return LandmarkAgendaPreviewResult(
            agenda=agenda,
            public_cue=public_cue,
            question=question.question.strip(),
            answer=answer.text.strip(),
        )

    def fill_landmark_agenda(self, agenda: LandmarkAgenda) -> dict:
        if not agenda.scene_id.strip():
            raise RuntimeError("LandmarkAgenda missing scene_id — fill requires grounded scene")
        public_cue = build_landmark_agenda_public_cue(agenda)
        query = " ".join(
            part.strip()
            for part in (agenda.title, agenda.summary, agenda.full_context, agenda.scene_name)
            if part.strip()
        )
        self.ensure_narrative_context(NarrativePurpose.fill, query=query)
        fallback = agenda.steps[0] if agenda.steps else agenda.summary
        story_outcome = self._run_story_arc(
            public_cue,
            kind=StoryEventKind.landmark,
            fallback_answer=fallback,
            start_policy=self._story_start_policy,
            scene_id=agenda.scene_id,
        )
        self.apply_world_background(story_outcome.scene_packet.scene_text)
        draft, unit = self._subjective_from_outcome(
            story_outcome,
            salience=0.65,
            trigger=VirtualUnitTrigger.landmark_agenda,
            landmark_id=agenda.id,
            journal_intention=agenda.summary,
            journal_context=agenda.full_context,
            default_intensity=0.65,
            promotion_context=self._agenda_promotion_context(agenda, story_outcome),
        )
        agenda.mark_completed()
        self.save_landmark_agenda(agenda)
        payload = self._outcome_payload(
            story_outcome,
            draft=draft,
            unit=unit,
            trigger="landmark_agenda",
            salience=0.65,
            share_desire="moderate",
            landmark_id=agenda.id,
            intention=agenda.title,
        )
        payload["hint"] = unit.situation.narration
        payload["landmark_agenda_id"] = agenda.id
        payload["agenda"] = agenda.to_dict()
        return payload

    def set_narrative_engine(self, engine: NarrativeEngine | None) -> None:
        self._narrative = engine
        if engine is not None:
            self._filler = engine
            self._surprise_generator = engine
        else:
            self._filler = NullLandmarkFiller()
            self._surprise_generator = NullSurpriseGenerator()

    def set_filler(self, filler: LandmarkFiller) -> None:
        self._filler = filler

    def set_surprise_generator(self, generator: SurpriseGenerator) -> None:
        self._surprise_generator = generator

    def set_narrative_context_supplier(
        self, supplier: NarrativeContextSupplier | None
    ) -> None:
        self._context_supplier = supplier

    def set_story_world_context_supplier(
        self,
        supplier: StoryWorldContextSupplier | None,
    ) -> None:
        self._world_context_supplier = supplier

    def set_story_port(self, port: StoryPort | None) -> None:
        self._story_port = port

    def set_gm_answerer(self, answerer: Callable[[GMQuestion], str] | None) -> None:
        self._gm_answerer = answerer

    def set_story_arc_max_steps(self, max_steps: int) -> None:
        self._story_arc_max_steps = max(1, min(6, int(max_steps)))

    def set_story_start_policy(self, policy: ArcStartPolicy | str) -> None:
        token = str(getattr(policy, "value", policy)).strip().lower()
        if token not in {ArcStartPolicy.history.value, ArcStartPolicy.home.value}:
            raise ValueError(f"unsupported story start policy: {policy}")
        self._story_start_policy = ArcStartPolicy(token)

    def set_scene_grounding_policy(self, policy: SceneGroundingPolicy | None) -> None:
        self._scene_grounding_policy = policy

    @property
    def scene_grounding_policy(self) -> SceneGroundingPolicy | None:
        return self._scene_grounding_policy

    def set_world_id(self, world_id: str) -> None:
        self._world_id = world_id.strip() or "default"

    def set_bound_scene(
        self,
        scene_id: str,
        *,
        scene_name: str = "",
        scene_cards: list[dict] | None = None,
    ) -> None:
        self._bound_scene_id = scene_id.strip()
        self._bound_scene_name = scene_name.strip()
        self._bound_scene_cards = list(scene_cards or [])

    @property
    def world_id(self) -> str:
        return self._world_id

    def _require_story_port(self) -> StoryPort:
        if self._story_port is None:
            raise RuntimeError("StoryPort not wired — start SoulService with story engine")
        return self._story_port

    def _open_story_scene(
        self,
        cue: str,
        kind: StoryEventKind | str,
    ):
        port = self._require_story_port()
        packet = port.begin_event(self._world_id, cue, kind=kind)
        self.apply_world_background(packet.scene_text)
        return packet

    def _answer_gm_question(
        self,
        question: GMQuestion,
        *,
        fallback: str = "",
    ) -> GMAnswer:
        text = ""
        if self._gm_answerer is not None:
            text = self._gm_answerer(question).strip()
        if not text:
            text = fallback.strip()
        if not text and question.choices:
            text = question.choices[0]
        if not text:
            text = "你先稳住自己，观察眼前的变化。"
        return GMAnswer(
            question_id=question.question_id,
            text=text,
            intent=text,
        )

    def _next_arc_cue(
        self,
        base_cue: str,
        outcome: StoryBeatOutcome,
        *,
        step: int,
    ) -> str:
        result = outcome.resolved.resolution_text.strip()
        answer = outcome.answer.text.strip()
        return (
            f"{base_cue.strip()}\n"
            f"上一拍你选择：{answer}\n"
            f"上一拍客观反馈：{result}\n"
            f"现在进入第 {step + 1} 拍，主持继续推进这个场景弧。"
        )

    def _with_arc(
        self,
        outcome: StoryBeatOutcome,
        *,
        outcomes: list[StoryBeatOutcome],
        objective_summary: str,
    ) -> StoryBeatOutcome:
        return StoryBeatOutcome(
            question=outcome.question,
            answer=outcome.answer,
            scene_packet=outcome.scene_packet,
            resolved=outcome.resolved,
            dice_value=outcome.dice_value,
            dice_tendency=outcome.dice_tendency,
            influence=outcome.influence,
            scene_candidates=outcome.scene_candidates,
            arc_steps=tuple(
                GMExchange(
                    question=item.question,
                    answer=item.answer,
                    scene_packet=item.scene_packet,
                    resolved=item.resolved,
                    dice_value=item.dice_value,
                    dice_tendency=item.dice_tendency,
                    story_direction=item.resolved.story_direction,
                    decision_importance=item.influence.decision_importance,
                )
                for item in outcomes
            ),
            objective_summary=objective_summary,
        )

    def _build_public_landmark_cue(self, lm: Landmark) -> str:
        parts = [
            "【触发来源】journal_landmark",
            f"【journal_landmark_id】{lm.id}",
            f"【公开预约意图】{lm.intention.strip()}",
        ]
        if lm.context.strip():
            parts.append(f"【公开预约背景】{lm.context.strip()}")
        if self._bound_scene_id:
            parts.append(f"【绑定场景】{self._bound_scene_name or self._bound_scene_id}")
            parts.append(
                "【场景约束】本次地标已绑定上述场景与场景卡；"
                "主持不得离开绑定 scene，不得引入 journal 未声明的新地点。"
            )
            if self._bound_scene_cards:
                card_lines = [
                    f"- {card.get('title', card.get('id', 'card'))}：{str(card.get('description', ''))[:80]}"
                    for card in self._bound_scene_cards[:6]
                ]
                parts.append("【场景卡】")
                parts.extend(card_lines)
        parts.append(
            "【主持规则】以上意图为 Soul 与 storyview 共享的公开行动声明；"
            "你只能据此主持问题和选项，不得替 Soul 决定最终行动或动机。"
        )
        return "\n".join(parts)

    def _run_story_arc(
        self,
        cue: str,
        *,
        kind: StoryEventKind | str,
        fallback_answer: str = "",
        first_question: GMQuestion | None = None,
        start_policy: ArcStartPolicy | str = ArcStartPolicy.history,
        scene_id: str = "",
    ) -> StoryBeatOutcome:
        port = self._require_story_port()
        outcomes: list[StoryBeatOutcome] = []
        question = first_question
        current_cue = cue
        move_offered = False
        forced_scene_id = scene_id.strip()
        for step in range(self._story_arc_max_steps):
            if question is None:
                if step == 0 and forced_scene_id:
                    question = port.ask_gm_at_scene(
                        self._world_id,
                        forced_scene_id,
                        current_cue,
                        kind=kind,
                    )
                else:
                    policy = start_policy if step == 0 else ArcStartPolicy.history
                    question = port.ask_gm(
                        self._world_id,
                        current_cue,
                        kind=kind,
                        start_policy=policy,
                    )
            answer = self._answer_gm_question(
                question,
                fallback=fallback_answer if step == 0 else "",
            )
            outcome = port.answer_gm(
                question,
                answer,
                with_dice=True,
            )
            outcomes.append(outcome)
            move_context = ""
            if not move_offered and not forced_scene_id:
                move_question = port.ask_move(
                    self._world_id,
                    current_cue,
                    kind=kind,
                )
                move_offered = True
                if move_question is not None:
                    move_answer = self._answer_gm_question(move_question)
                    move_outcome = port.answer_move(
                        move_question,
                        move_answer,
                        with_dice=False,
                    )
                    move_context = move_outcome.scene_packet.scene_text.strip()
            current_cue = self._next_arc_cue(cue, outcome, step=step)
            if move_context:
                current_cue = f"{current_cue}\n\n【新的场景信息】\n{move_context}"
            question = None
        objective_summary = port.distill_arc(self._world_id, outcomes)
        return self._with_arc(
            outcomes[-1],
            outcomes=outcomes,
            objective_summary=objective_summary,
        )

    def apply_narrative_context(
        self,
        portrait: str,
        continuity: list[str],
    ) -> None:
        self._profile_narrative = portrait
        self._continuity_memories = continuity

    def apply_world_background(self, background: str) -> None:
        self._world_background = background.strip()

    def ensure_narrative_context(
        self,
        purpose: NarrativePurpose,
        *,
        query: str = "",
    ) -> None:
        if self._context_supplier is not None:
            self._context_supplier.refresh(self, purpose, query=query)
        if self._world_context_supplier is not None:
            world = self._world_context_supplier.background(purpose, query=query)
            self.apply_world_background(world)

    def update_context(
        self,
        profile_narrative: str = "",
        continuity_memories: list[str] | None = None,
        world_background: str | None = None,
    ) -> None:
        if profile_narrative:
            self._profile_narrative = profile_narrative
        if continuity_memories is not None:
            self._continuity_memories = continuity_memories
        if world_background is not None:
            self._world_background = world_background

    def save_journal(self) -> None:
        self._journal_store.save(self._journal)

    def add_landmark(
        self,
        intention: str,
        scheduled_at: str,
        context: str = "",
    ) -> bool:
        return self.plan_landmark(intention, scheduled_at, context) is not None

    def plan_landmark(
        self,
        intention: str,
        scheduled_at: str,
        context: str = "",
    ) -> dict | None:
        lm = self._journal.add_landmark(intention, scheduled_at, context)
        if lm is None:
            return None
        self.save_journal()
        query = intention.strip()
        if context.strip():
            query = f"{query} {context.strip()}"
        self.ensure_narrative_context(NarrativePurpose.fabricate, query=query)
        objective_scene = ""
        if self._story_port is not None:
            packet = self._open_story_scene(query, StoryEventKind.fabricate)
            objective_scene = packet.scene_text

        plan_seed = f"我刚为自己预约了一个体验时刻：{intention.strip() or '一个新的地标'}"
        if context.strip():
            plan_seed = f"{plan_seed}。背景：{context.strip()}"
        plan_seed = f"{plan_seed}。触发时间：{scheduled_at}"

        narrative_hint = plan_seed
        emotion_text = ""
        emotion_intensity = 0.35
        emotion_strength = "轻微波动"
        if self._narrative is not None:
            draft = self._narrative.fabricate_with_emotion(
                hint=plan_seed,
                profile_narrative=self._profile_narrative,
                continuity_memories=self._continuity_memories,
                world_background=self._world_background,
                objective_scene=objective_scene,
                default_intensity=0.35,
            )
            narrative_hint = draft.narrative
            emotion_text = draft.emotion_text
            emotion_intensity = draft.emotion_intensity
            emotion_strength = draft.emotion_strength

        unit = self.record_story_beat(
            narrative_hint=narrative_hint,
            salience=emotion_intensity,
            emotion_label=emotion_strength,
            action_kind=ExperienceActionKind.deciding,
            virtual_ctx=VirtualUnitContext(
                trigger=VirtualUnitTrigger.landmark_plan,
                landmark_id=lm.id,
            ),
        )
        return {
            "hint": narrative_hint,
            "salience": emotion_intensity,
            "trigger": "landmark_plan",
            "source": "life",
            "share_desire": "mild",
            "emotion_text": emotion_text,
            "emotion_intensity": emotion_intensity,
            "emotion_strength": emotion_strength,
            "landmark_id": lm.id,
            "experience_id": unit.id,
        }

    def compose_landmark(self) -> dict | None:
        self.ensure_narrative_context(NarrativePurpose.compose)
        if self._narrative is None:
            return None
        return self._narrative.compose_landmark_intent(
            profile_narrative=self._profile_narrative,
            recent_landmark_intents=self._journal.recent_done_intent_lines(3),
            world_background=self._world_background,
        )

    def count_landmarks_written_since(self, since_iso: str) -> int:
        since = datetime.fromisoformat(since_iso.replace("Z", "+00:00"))
        return self._journal.count_written_since(since)

    def _arc_dialogue_text(self, outcome: StoryBeatOutcome) -> str:
        return "\n".join(
            f"{idx}. 主持：{step.question.question.strip()} / 你：{step.answer.text.strip()}"
            for idx, step in enumerate(outcome.arc_steps, start=1)
        )

    def _arc_soul_answers_text(self, outcome: StoryBeatOutcome) -> str:
        return "\n".join(
            f"{idx}. {step.answer.text.strip()}"
            for idx, step in enumerate(outcome.arc_steps, start=1)
            if step.answer.text.strip()
        )

    def _subjective_from_outcome(
        self,
        outcome: StoryBeatOutcome,
        *,
        salience: float,
        trigger: VirtualUnitTrigger,
        landmark_id: str = "",
        journal_intention: str = "",
        journal_context: str = "",
        default_intensity: float | None = None,
        promotion_context: str = "",
    ) -> tuple[NarrativeDraft | None, ExperienceUnit]:
        intensity = default_intensity
        if intensity is None:
            intensity = outcome.influence.salience or salience
        effective_salience = max(salience, outcome.influence.salience or 0.0)
        draft: NarrativeDraft | None = None
        objective_arc = outcome.objective_summary.strip()
        if not objective_arc:
            objective_arc = outcome.resolved.resolution_text
        arc_dialogue = self._arc_dialogue_text(outcome)
        arc_step_facts = "\n".join(
            f"{idx}. {step.resolved.resolution_text.strip()}"
            for idx, step in enumerate(outcome.arc_steps, start=1)
            if step.resolved.resolution_text.strip()
        )
        soul_answers = self._arc_soul_answers_text(outcome)
        resolution_text = objective_arc
        if arc_step_facts:
            resolution_text = f"{objective_arc}\n\n【各拍客观结果】\n{arc_step_facts}".strip()
        story_query = " ".join(
            part.strip()
            for part in (
                journal_intention,
                journal_context,
                outcome.scene_packet.scene_text,
                resolution_text,
                arc_dialogue,
                soul_answers or outcome.answer.text,
            )
            if part.strip()
        )
        purpose = (
            NarrativePurpose.surprise
            if trigger == VirtualUnitTrigger.surprise
            else NarrativePurpose.fill
        )
        self.ensure_narrative_context(purpose, query=story_query)
        if self._narrative is not None:
            episode_for_prompt = None
            if trigger in {VirtualUnitTrigger.landmark, VirtualUnitTrigger.landmark_agenda}:
                episode_for_prompt = build_landmark_episode(
                    outcome,
                    landmark_id=landmark_id,
                    intention=journal_intention,
                    context=journal_context,
                    scene_name=self._bound_scene_name,
                    scene_cards=self._bound_scene_cards,
                )
            draft = self._narrative.subjective_from_outcome(
                objective_scene=outcome.scene_packet.scene_text,
                resolution_text=resolution_text,
                gm_question=arc_dialogue or outcome.question.question,
                soul_answer=soul_answers or outcome.answer.text,
                journal_intention=journal_intention,
                journal_context=journal_context,
                decision_importance=outcome.influence.decision_importance,
                profile_narrative=self._profile_narrative,
                continuity_memories=self._continuity_memories,
                world_background=self._world_background,
                default_intensity=intensity,
                episode_summary=episode_for_prompt.summary_text() if episode_for_prompt else "",
                episode_steps=episode_for_prompt.arc_steps if episode_for_prompt else None,
            )
        narrative = draft.narrative if draft is not None else outcome.resolved.resolution_text
        emotion_text = draft.emotion_text if draft is not None else ""
        emotion_strength = draft.emotion_strength if draft is not None else "明显触动"
        emotion_intensity = draft.emotion_intensity if draft is not None else intensity
        perception = draft.perception if draft is not None else ""
        action_summary = draft.action_summary if draft is not None else outcome.answer.text[:60]
        source = "surprise" if trigger == VirtualUnitTrigger.surprise else "narrative"
        evidence_builder = None
        if trigger in {VirtualUnitTrigger.landmark, VirtualUnitTrigger.landmark_agenda}:
            def evidence_builder(unit: ExperienceUnit) -> dict:
                episode = build_landmark_episode(
                    outcome,
                    landmark_id=landmark_id,
                    intention=journal_intention,
                    context=journal_context,
                    experience_id=unit.id,
                    scene_name=self._bound_scene_name,
                    scene_cards=self._bound_scene_cards,
                    draft=draft,
                )
                attach_episode_memory_drafts(episode, llm=self._llm)
                unit.feeling.salience_note = episode.summary_text()[:240] or unit.feeling.salience_note
                return {"landmark_episode": episode.to_dict()}
        unit = self._builder.record_virtual_beat(
            narrative,
            perception=perception,
            action_summary=action_summary,
            emotion_text=emotion_text,
            emotion_label=emotion_strength,
            salience=effective_salience,
            source=source,
            virtual_ctx=VirtualUnitContext(
                trigger=trigger,
                landmark_id=landmark_id,
                story_event_id=outcome.scene_packet.event_id,
                scene_id=outcome.question.scene_id,
                question_id=outcome.question.question_id,
            ),
            evidence_builder=evidence_builder,
        )
        if promotion_context.strip():
            unit.feeling.salience_note = (
                f"{unit.feeling.salience_note}\n\n{promotion_context.strip()}"
            ).strip()
        return draft, unit

    def _agenda_promotion_context(
        self,
        agenda: LandmarkAgenda,
        outcome: StoryBeatOutcome,
    ) -> str:
        card_lines = [
            f"- {card.title}：{card.description[:80]}"
            for card in agenda.scene_cards
        ]
        arc_summary = outcome.objective_summary.strip() or outcome.resolved.resolution_text.strip()
        parts = [
            "【LandmarkAgenda 擢升上下文】",
            f"title={agenda.title}",
            f"summary={agenda.summary}",
            f"full_context={agenda.full_context[:240]}",
            f"scene_id={agenda.scene_id}",
            f"scene_name={agenda.scene_name}",
            "steps=" + "；".join(agenda.steps[:6]),
            "success_criteria=" + "；".join(agenda.success_criteria[:4]),
        ]
        if card_lines:
            parts.append("scene_cards:")
            parts.extend(card_lines)
        if agenda.grounding_trace:
            parts.append(
                "grounding_trace="
                + " | ".join(
                    f"{item.action}:{item.observation[:60]}"
                    for item in agenda.grounding_trace[:4]
                )
            )
        if arc_summary:
            parts.append(f"gm_arc={arc_summary[:280]}")
        return "\n".join(parts)

    def _arc_step_payload(self, step: GMExchange) -> dict:
        dice_value = int(getattr(step, "dice_value", 0) or step.resolved.dice_value or 0)
        dice_tendency = str(getattr(step, "dice_tendency", "") or step.resolved.dice_tendency or "")
        story_direction = str(getattr(step, "story_direction", "") or step.resolved.story_direction or "")
        decision_importance = str(getattr(step, "decision_importance", "") or "")
        return {
            "gm_question": step.question.question,
            "soul_answer": step.answer.text,
            "scene_text": step.scene_packet.scene_text,
            "resolution_text": step.resolved.resolution_text,
            "scene_id": step.question.scene_id,
            "dice_value": dice_value,
            "dice_tendency": dice_tendency,
            "story_direction": story_direction,
            "decision_importance": decision_importance,
        }

    def _outcome_payload(
        self,
        outcome: StoryBeatOutcome,
        *,
        draft: NarrativeDraft | None,
        unit: ExperienceUnit,
        trigger: str,
        salience: float,
        share_desire: str,
        landmark_id: str = "",
        intention: str = "",
    ) -> dict:
        gm_question = outcome.question.question
        soul_answer = outcome.answer.text
        if outcome.arc_steps:
            arc_dialogue = self._arc_dialogue_text(outcome)
            arc_answers = self._arc_soul_answers_text(outcome)
            if arc_dialogue.strip():
                gm_question = arc_dialogue
            if arc_answers.strip():
                soul_answer = arc_answers
        episode_payload = dict(unit.evidence.get("landmark_episode") or {})
        return {
            "triggered": True,
            "trigger": trigger,
            "salience": salience,
            "share_desire": share_desire,
            "experience_id": unit.id,
            "narrative": unit.situation.narration,
            "scene_text": outcome.scene_packet.scene_text,
            "resolution_text": outcome.objective_summary or outcome.resolved.resolution_text,
            "gm_question": gm_question,
            "soul_answer": soul_answer,
            "decision_importance": outcome.influence.decision_importance,
            "arc_steps": [self._arc_step_payload(step) for step in outcome.arc_steps],
            "dice_trace": episode_payload.get("arc_steps") or [],
            "episode": episode_payload,
            "typed_memory_items": episode_payload.get("typed_memory_items") or [],
            "rejected_memory_items": episode_payload.get("rejected_items") or [],
            "scene_id": outcome.question.scene_id,
            "story_event_id": outcome.scene_packet.event_id,
            "scene_candidates": [
                {
                    "scene_id": cand.scene.id,
                    "name": cand.scene.name,
                    "matched_by": cand.matched_by,
                    "score": cand.score,
                }
                for cand in outcome.scene_candidates
            ],
            "deviation": outcome.resolved.deviation,
            "landmark_id": landmark_id,
            "intention": intention,
            "emotion_text": draft.emotion_text if draft is not None else "",
            "emotion_intensity": draft.emotion_intensity if draft is not None else salience,
            "emotion_strength": draft.emotion_strength if draft is not None else "",
        }

    def record_story_beat(
        self,
        narrative_hint: str,
        emotion_label: str = "",
        valence_delta: float = 0.0,
        arousal_delta: float = 0.0,
        salience: float = 0.0,
        action_kind: ExperienceActionKind = ExperienceActionKind.reasoning,
        virtual_ctx: VirtualUnitContext | None = None,
    ) -> ExperienceUnit:
        return self._builder.record_story_beat(
            narrative_hint=narrative_hint,
            emotion_label=emotion_label,
            valence_delta=valence_delta,
            arousal_delta=arousal_delta,
            salience=salience,
            action_kind=action_kind,
            virtual_ctx=virtual_ctx,
        )

    def record_surprise(
        self,
        narrative_hint: str,
        dice_value: int = 0,
        dice_tendency: str = "",
        salience: float = 0.5,
    ) -> ExperienceUnit:
        return self._builder.record_surprise(
            narrative_hint=narrative_hint,
            dice_value=dice_value,
            dice_tendency=dice_tendency,
            salience=salience,
        )

    def scan_overdue_landmarks(self) -> list[Landmark]:
        overdue = self._journal.scan_overdue()
        if overdue:
            self.save_journal()
        return overdue

    def due_landmarks(self) -> list[Landmark]:
        return self._journal.due_landmarks()

    def fill_landmark(self, landmark_id: str) -> dict | None:
        lm = self._journal.get_landmark(landmark_id)
        if lm is None or lm.status == LandmarkStatus.done:
            return None

        public_cue = self._build_public_landmark_cue(lm)
        query = lm.intention.strip()
        if lm.context.strip():
            query = f"{query} {lm.context.strip()}"
        self.ensure_narrative_context(NarrativePurpose.fill, query=query)
        lm.mark_processing()
        story_outcome = self._run_story_arc(
            public_cue,
            kind=StoryEventKind.landmark,
            fallback_answer=lm.intention,
            start_policy=self._story_start_policy,
            scene_id=self._bound_scene_id,
        )
        self.apply_world_background(story_outcome.scene_packet.scene_text)
        draft, unit = self._subjective_from_outcome(
            story_outcome,
            salience=0.6,
            trigger=VirtualUnitTrigger.landmark,
            landmark_id=lm.id,
            journal_intention=lm.intention,
            journal_context=lm.context,
            default_intensity=0.6,
        )
        lm.mark_done(
            narrative=unit.situation.narration,
            experience_id=unit.id,
            dice_value=0,
            dice_tendency="",
        )
        self.save_journal()
        payload = self._outcome_payload(
            story_outcome,
            draft=draft,
            unit=unit,
            trigger="landmark",
            salience=0.6,
            share_desire="moderate",
            landmark_id=lm.id,
            intention=lm.intention,
        )
        payload["hint"] = unit.situation.narration
        return payload

    def tick_surprise(self, elapsed_sec: float) -> dict:
        port = self._require_story_port()
        question = port.ask_surprise(self._world_id, elapsed_sec)
        if question is None:
            return {
                "triggered": False,
                "probability": round(port.surprise_probability(self._world_id), 3),
            }
        story_outcome = self._run_story_arc(
            "意外事件",
            kind=StoryEventKind.surprise,
            first_question=question,
        )
        self.ensure_narrative_context(NarrativePurpose.surprise)
        self.apply_world_background(story_outcome.scene_packet.scene_text)
        draft, unit = self._subjective_from_outcome(
            story_outcome,
            salience=0.5,
            trigger=VirtualUnitTrigger.surprise,
            default_intensity=0.5,
        )
        payload = self._outcome_payload(
            story_outcome,
            draft=draft,
            unit=unit,
            trigger="surprise",
            salience=0.5,
            share_desire="eager",
        )
        payload["triggered"] = True
        payload["probability"] = round(port.surprise_probability(self._world_id), 3)
        return payload

    def process_wander_experience(
        self,
        result: MemoryHeartbeatResult,
    ) -> list[dict]:
        """Wander 反刍信号 → 虚拟叙事 beat（在 LifeService 线程内执行）。"""
        beats: list[dict] = []
        portrait = self._profile_narrative
        hint = (result.signal.narrative_hint or "").strip()
        if hint:
            self.ensure_narrative_context(NarrativePurpose.fabricate, query=hint)
            portrait = self._profile_narrative
            objective_scene = ""
            if self._story_port is not None:
                packet = self._open_story_scene(hint, StoryEventKind.wander)
                objective_scene = packet.scene_text
            narrative_hint = (
                f"心跳反刍线索：{hint}"
            )
            emotion_text = ""
            emotion_intensity = min(result.signal.intensity * 0.6, 0.8)
            emotion_strength = ""
            if self._narrative is not None:
                draft = self._narrative.fabricate_with_emotion(
                    hint=f"心跳反刍线索：{hint}",
                    profile_narrative=portrait,
                    continuity_memories=self._continuity_memories,
                    world_background=self._world_background,
                    objective_scene=objective_scene,
                    default_intensity=min(result.signal.intensity * 0.6, 0.8),
                )
                narrative_hint = draft.narrative
                emotion_text = draft.emotion_text
                emotion_intensity = draft.emotion_intensity
                emotion_strength = draft.emotion_strength
            self.record_story_beat(
                narrative_hint=narrative_hint,
                salience=min(result.signal.intensity * 0.6, 0.8),
                emotion_label=emotion_strength,
                arousal_delta=result.signal.intensity * 0.15,
                virtual_ctx=VirtualUnitContext(trigger=VirtualUnitTrigger.wander),
            )
            beats.append(
                {
                    "hint": narrative_hint,
                    "salience": min(result.signal.intensity * 0.6, 0.8),
                    "trigger": "wander",
                    "share_desire": (
                        "moderate"
                        if result.signal.intensity >= 0.55
                        else "mild"
                    ),
                    "emotion_text": emotion_text,
                    "emotion_intensity": emotion_intensity,
                    "emotion_strength": emotion_strength,
                }
            )

        if result.signal.intensity >= 0.55:
            dom = result.signal.dominant_emotion or "—"
            seed = (
                f"心跳漂移节点：烈度 {result.signal.intensity:.2f}，主导情绪 {dom}"
            )
            self.ensure_narrative_context(NarrativePurpose.fabricate, query=seed)
            portrait = self._profile_narrative
            objective_scene = ""
            if self._story_port is not None:
                packet = self._open_story_scene(seed, StoryEventKind.wander)
                objective_scene = packet.scene_text
            narrative_hint = (
                seed
            )
            emotion_text = ""
            emotion_intensity = result.signal.intensity
            emotion_strength = ""
            if self._narrative is not None:
                draft = self._narrative.fabricate_with_emotion(
                    hint=seed,
                    profile_narrative=portrait,
                    continuity_memories=self._continuity_memories,
                    world_background=self._world_background,
                    objective_scene=objective_scene,
                    default_intensity=result.signal.intensity,
                )
                narrative_hint = draft.narrative
                emotion_text = draft.emotion_text
                emotion_intensity = draft.emotion_intensity
                emotion_strength = draft.emotion_strength
            self.record_story_beat(
                narrative_hint=narrative_hint,
                emotion_label=emotion_strength or dom,
                valence_delta=result.signal.intensity * -0.1,
                arousal_delta=result.signal.intensity * 0.2,
                salience=result.signal.intensity,
                action_kind=ExperienceActionKind.deciding,
                virtual_ctx=VirtualUnitContext(trigger=VirtualUnitTrigger.wander),
            )
            beats.append(
                {
                    "hint": narrative_hint,
                    "salience": result.signal.intensity,
                    "trigger": "wander_drift",
                    "share_desire": (
                        "eager"
                        if result.signal.intensity >= 0.75
                        else "moderate"
                    ),
                    "emotion_text": emotion_text,
                    "emotion_intensity": emotion_intensity,
                    "emotion_strength": emotion_strength,
                }
            )

        return beats

    def status_fragment(self) -> dict:
        surprise_p = 0.0
        if self._story_port is not None:
            surprise_p = self._story_port.surprise_probability(self._world_id)
        return {
            "due_landmarks": len(self._journal.due_landmarks()),
            "surprise_p": round(surprise_p, 3),
            "landmark_slots": self._journal.today_remaining_slots(),
        }
