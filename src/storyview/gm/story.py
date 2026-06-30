from __future__ import annotations

import random
import re
import uuid
from dataclasses import replace

from langchain_core.messages import HumanMessage, SystemMessage

from storyview.fate.dice import (
    DecisionImportance,
    DiceResult,
    roll_d100,
    roll_decision_importance,
    roll_story_direction,
)
from storyview.gm.resolve import ActionResolver
from storyview.scene import SceneComposer
from storyview.scene.cards import scene_cards
from storyview.scene.network import SceneNetwork
from storyview.store.mysql import StoryStoreBundle
from storyview.types import (
    AgentLocationSnapshot,
    ArcStartPolicy,
    GMAnswer,
    GMExchange,
    GMQuestion,
    LocationSnapshotReason,
    ResolvedOutcome,
    SceneCandidate,
    ScenePacket,
    SceneUnit,
    StoryBeatOutcome,
    StoryEventKind,
    StoryInfluence,
    StatePatch,
)

_STORY_WORLD_ONLY_RULE = (
    "避免真实世界日期、系统编排术语和格式标签；不要使用类似 6/25、2026、"
    "第1拍、步骤、轮次、NARRATIVE、STATE_PATCH 的表达。"
)

_ASK_SYSTEM = """\
你是故事主持（GM），向角色提出一个具体问题，引导本拍行动。
规则：
- 基于当前场景与本拍线索
- 若线索来自 journal landmark 公开预约意图，只能围绕该意图主持，不得替角色决定最终行动或动机
- journal landmark 时不得引入 journal 未声明的新线索、角色、物件或悬疑支线；问题与选项只能推进该意图本身
- 只问一个问题，15~40 字，第二人称「你」
- 可给 0~3 个可选行动；若必须限制行动范围，OPEN_CHOICE 输出 false
- 选项必须可执行，并受当前位置快照与场景约束
- 禁止元叙事：不得提到测试、脚本、代码、模型、API、LLM
- 避免真实世界日期、系统编排术语和格式标签；不要使用类似 6/25、2026、第1拍、步骤、轮次、NARRATIVE、STATE_PATCH 的表达
- 严格输出：

[QUESTION]
（问题）
[/QUESTION]
[STAKES]
（一句话说明这拍利害，可选）
[/STAKES]
[OPEN_CHOICE]
true
[/OPEN_CHOICE]
[CHOICES]
- （可选行动 1）
- （可选行动 2）
[/CHOICES]
[CONSTRAINTS]
（限制说明，可选）
[/CONSTRAINTS]"""

_ARC_DISTILL_SYSTEM = """\
你是故事主持（GM）的客观记录员，只蒸馏客观发生。
规则：
- 只写外部可观察事实、场景变化、行动结果
- 不写角色内心、情绪、感悟
- 不提命运骰、概率、模型、测试、脚本、代码
- 120~220 字，第二人称「你」，自然叙述
- 只输出正文，不要标题或标签"""


def _extract_tag(raw: str, tag: str) -> str:
    m = re.search(rf"\[{tag}\](.*?)\[/{tag}\]", raw, re.DOTALL)
    if m is None:
        return ""
    return m.group(1).strip()


def _kind_value(kind: StoryEventKind | str) -> str:
    return str(getattr(kind, "value", kind))


def _clean_story_text(text: str) -> str:
    cleaned = re.sub(r"\b20\d{2}[/-]\d{1,2}[/-]\d{1,2}\b", "某日", text)
    cleaned = re.sub(r"\b\d{1,2}/\d{1,2}\b", "某日", cleaned)
    cleaned = re.sub(r"第\s*\d+\s*拍[:：]?", "", cleaned)
    cleaned = re.sub(r"\[/?(?:NARRATIVE|STATE_PATCH)\]", "", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip()


def _clip_sentence(text: str, *, limit: int) -> str:
    cleaned = _clean_story_text(text)
    if len(cleaned) <= limit:
        return cleaned
    clipped = cleaned[:limit].rstrip("，。；、 ")
    boundary = max(clipped.rfind(mark) for mark in ("。", "！", "？", "；"))
    if boundary >= max(40, int(limit * 0.55)):
        return clipped[: boundary + 1]
    comma = max(clipped.rfind(mark) for mark in ("，", "、"))
    if comma >= max(40, int(limit * 0.7)):
        return clipped[:comma].rstrip("，、") + "。"
    return clipped + "。"


class StoryDirector:
    """故事编排：主持问答、场景候选、命运骰与客观 outcome。"""

    def __init__(
        self,
        stores: StoryStoreBundle,
        scene_network: SceneNetwork,
        scene_composer: SceneComposer,
        action_resolver: ActionResolver,
        llm=None,
    ) -> None:
        self._stores = stores
        self._scene_network = scene_network
        self._scene = scene_composer
        self._resolve = action_resolver
        self._llm = llm
        self._pending: dict[str, GMQuestion] = {}

    def pending_question(self, question_id: str) -> GMQuestion | None:
        return self._pending.get(question_id)

    def _snapshot_store(self):
        return getattr(self._stores, "location_snapshots", None)

    def _record_location_snapshot(
        self,
        world_id: str,
        *,
        scene: SceneUnit,
        scene_text: str,
        reason: LocationSnapshotReason | str,
        source_event_id: str = "",
    ) -> AgentLocationSnapshot | None:
        store = self._snapshot_store()
        if store is None:
            return None
        snapshot = AgentLocationSnapshot(
            snapshot_id=str(uuid.uuid4()),
            world_id=world_id,
            scene_id=scene.id,
            scene_text=scene_text.strip() or scene.narrative.strip(),
            location_id=scene.location_id,
            reason=reason,
            source_event_id=source_event_id,
        )
        store.append(snapshot)
        return snapshot

    def _apply_scene_to_runtime(
        self,
        world_id: str,
        scene: SceneUnit,
        *,
        reason: LocationSnapshotReason | str,
        scene_text: str = "",
        source_event_id: str = "",
    ) -> None:
        if scene.location_id:
            self._stores.runtime.apply_patch(
                world_id,
                StatePatch(move_to_location_id=scene.location_id),
            )
        text = scene_text.strip() or scene.narrative.strip()
        if text:
            self._stores.runtime.update_snapshot(world_id, text)
        self._record_location_snapshot(
            world_id,
            scene=scene,
            scene_text=text,
            reason=reason,
            source_event_id=source_event_id,
        )

    def _resolve_arc_start(
        self,
        world_id: str,
        *,
        start_policy: ArcStartPolicy | str = ArcStartPolicy.history,
    ) -> tuple[SceneUnit | None, str]:
        policy = str(getattr(start_policy, "value", start_policy))
        home = self._find_home_scene(world_id)

        if policy == ArcStartPolicy.home.value:
            if home is not None:
                self._apply_scene_to_runtime(
                    world_id,
                    home,
                    reason=LocationSnapshotReason.home_reset,
                )
                return home, "home"
            return None, "home_missing"

        current_id = self._scene_network.resolve_current_scene_id(world_id)
        if current_id is None:
            store = self._snapshot_store()
            if store is not None:
                last = store.last(world_id)
                if last is not None and last.scene_id:
                    current_id = last.scene_id
                    if last.location_id:
                        self._stores.runtime.apply_patch(
                            world_id,
                            StatePatch(move_to_location_id=last.location_id),
                        )

        if current_id:
            scene = self._scene_network.get(current_id)
            if scene is not None:
                return scene, "history"

        if home is not None:
            self._apply_scene_to_runtime(
                world_id,
                home,
                reason=LocationSnapshotReason.home_reset,
            )
            return home, "home_fallback"

        return None, "locator"

    def current_location_snapshot(self, world_id: str) -> AgentLocationSnapshot | None:
        store = self._snapshot_store()
        if store is None:
            return None
        return store.last(world_id)

    def list_location_snapshots(
        self,
        world_id: str,
        *,
        limit: int = 10,
    ) -> list[AgentLocationSnapshot]:
        store = self._snapshot_store()
        if store is None:
            return []
        return store.list_recent(world_id, limit=limit)

    def ask(
        self,
        world_id: str,
        cue: str,
        *,
        kind: StoryEventKind | str = StoryEventKind.fabricate,
        start_policy: ArcStartPolicy | str = ArcStartPolicy.history,
    ) -> GMQuestion:
        self._stores.world.ensure(world_id)
        start_scene, _ = self._resolve_arc_start(world_id, start_policy=start_policy)
        current_id = start_scene.id if start_scene is not None else None
        scene, candidates = self._pick_scene(
            world_id,
            cue,
            current_scene_id=current_id,
        )
        if start_scene is None or start_scene.id != scene.id:
            self._apply_scene_to_runtime(
                world_id,
                scene,
                reason=LocationSnapshotReason.arc_start,
                scene_text=scene.narrative,
            )
        else:
            self._record_location_snapshot(
                world_id,
                scene=scene,
                scene_text=self._stores.runtime.snapshot_text(world_id) or scene.narrative,
                reason=LocationSnapshotReason.arc_start,
            )
        question_id = str(uuid.uuid4())
        question_text, stakes, choices, open_choice, constraints = self._compose_question(
            world_id=world_id,
            cue=cue,
            kind=kind,
            scene=scene,
        )
        gm_question = GMQuestion(
            question_id=question_id,
            world_id=world_id,
            kind=kind,
            cue=cue.strip(),
            scene_id=scene.id,
            question=question_text,
            stakes=stakes,
            choices=tuple(choices),
            open_choice=open_choice,
            constraints=constraints,
        )
        self._pending[question_id] = gm_question
        return gm_question

    def ask_at_scene(
        self,
        world_id: str,
        scene_id: str,
        cue: str,
        *,
        kind: StoryEventKind | str = StoryEventKind.fabricate,
    ) -> GMQuestion:
        self._stores.world.ensure(world_id)
        scene = self._scene_network.get(scene_id)
        if scene is None:
            raise ValueError(f"unknown scene: {scene_id}")
        current_id = self._scene_network.resolve_current_scene_id(world_id)
        if current_id != scene.id:
            self._apply_scene_to_runtime(
                world_id,
                scene,
                reason=LocationSnapshotReason.arc_start,
                scene_text=scene.narrative,
            )
        else:
            self._record_location_snapshot(
                world_id,
                scene=scene,
                scene_text=self._stores.runtime.snapshot_text(world_id) or scene.narrative,
                reason=LocationSnapshotReason.arc_start,
            )
        question_id = str(uuid.uuid4())
        question_text, stakes, choices, open_choice, constraints = self._compose_question(
            world_id=world_id,
            cue=cue,
            kind=kind,
            scene=scene,
        )
        gm_question = GMQuestion(
            question_id=question_id,
            world_id=world_id,
            kind=kind,
            cue=cue.strip(),
            scene_id=scene.id,
            question=question_text,
            stakes=stakes,
            choices=tuple(choices),
            open_choice=open_choice,
            constraints=constraints,
        )
        self._pending[question_id] = gm_question
        return gm_question

    def answer(
        self,
        question: GMQuestion,
        answer: GMAnswer,
        *,
        dice: DiceResult | None = None,
        with_dice: bool = True,
    ) -> StoryBeatOutcome:
        if question.question_id != answer.question_id:
            raise ValueError("GM answer question_id mismatch")
        self._pending.pop(question.question_id, None)
        scene = self._scene_network.get(question.scene_id)
        transition = ""
        if scene is not None:
            current_id = self._scene_network.resolve_current_scene_id(question.world_id)
            if current_id and current_id != scene.id:
                for edge in self._scene_network.out_edges(current_id):
                    if edge.to_scene_id == scene.id:
                        transition = edge.transition_text
                        break
            if scene.location_id:
                from storyview.types import StatePatch

                self._stores.runtime.apply_patch(
                    question.world_id,
                    StatePatch(move_to_location_id=scene.location_id),
                )
        packet, _ = self._scene.open_scene(
            question.world_id,
            question.cue,
            kind=question.kind,
            scene_id=question.scene_id,
            transition_text=transition,
        )
        resolved_scene = self._scene_network.get(question.scene_id)
        if resolved_scene is not None:
            self._record_location_snapshot(
                question.world_id,
                scene=resolved_scene,
                scene_text=packet.scene_text,
                reason=LocationSnapshotReason.gm_answer,
                source_event_id=packet.event_id,
            )
        if dice is None and with_dice:
            dice = roll_d100()
        story_direction = roll_story_direction()
        decision_importance = roll_decision_importance()
        resolved = self._resolve.resolve(
            packet.event_id,
            intent=answer.intent.strip() or answer.text.strip(),
            agent_narrative="",
            with_dice=with_dice,
            dice=dice,
            story_direction=story_direction.tendency,
        )
        influence = self._influence_from(
            dice if dice is not None else DiceResult(0, ""),
            question.kind,
            decision_importance=decision_importance,
        )
        _, candidates = self._pick_scene(question.world_id, question.cue)
        return StoryBeatOutcome(
            question=question,
            answer=answer,
            scene_packet=packet,
            resolved=resolved,
            dice_value=resolved.dice_value,
            dice_tendency=resolved.dice_tendency,
            influence=influence,
            scene_candidates=tuple(candidates),
        )

    def ask_move(
        self,
        world_id: str,
        cue: str,
        *,
        kind: StoryEventKind | str = StoryEventKind.fabricate,
    ) -> GMQuestion | None:
        self._stores.world.ensure(world_id)
        current_id = self._scene_network.resolve_current_scene_id(world_id)
        if current_id is None:
            home = self._find_home_scene(world_id)
            current_id = home.id if home is not None else None
        current = self._scene_network.get(current_id) if current_id else None
        if current is None:
            return None
        options: list[tuple[str, str]] = [("留在当前场景", current.id)]
        seen = {current.id}
        for edge in self._scene_network.out_edges(current.id):
            target = self._scene_network.get(edge.to_scene_id)
            if target is not None and target.id not in seen:
                options.append((target.name, target.id))
                seen.add(target.id)
        for edge in self._scene_network.in_edges(current.id):
            target = self._scene_network.get(edge.from_scene_id)
            if target is not None and target.id not in seen:
                options.append((target.name, target.id))
                seen.add(target.id)
        if len(options) <= 1:
            return None
        question = GMQuestion(
            question_id=str(uuid.uuid4()),
            world_id=world_id,
            kind=kind,
            cue=cue.strip(),
            scene_id=current.id,
            question="是否移动到相邻场景？",
            stakes="这是本段故事弧中唯一一次移动机会。",
            choices=tuple(label for label, _ in options),
            open_choice=False,
            constraints="只能从相邻场景候选中选择；不得新增或改写地点。",
            is_move=True,
            move_target_scene_ids=tuple(scene_id for _, scene_id in options),
        )
        self._pending[question.question_id] = question
        return question

    def answer_move(
        self,
        question: GMQuestion,
        answer: GMAnswer,
        *,
        with_dice: bool = False,
    ) -> StoryBeatOutcome:
        if not question.is_move:
            return self.answer(question, answer, with_dice=with_dice)
        text = answer.text.strip()
        target_idx = 0
        for idx, choice in enumerate(question.choices):
            if choice and choice in text:
                target_idx = idx
                break
        targets = list(question.move_target_scene_ids)
        if target_idx >= len(targets):
            target_idx = 0
        target_scene_id = targets[target_idx] if targets else question.scene_id
        target_name = (
            question.choices[target_idx]
            if target_idx < len(question.choices)
            else "当前场景"
        )
        target_scene = self._scene_network.get(target_scene_id)
        if target_scene is None:
            target_scene = self._scene_network.get(question.scene_id)
        if target_scene is None:
            return self.answer(question, answer, with_dice=with_dice)
        if target_scene.location_id:
            self._stores.runtime.apply_patch(
                question.world_id,
                StatePatch(move_to_location_id=target_scene.location_id),
            )
        from storyview.scene.network.render import build_inject_text

        transition = f"移动到相邻场景：{target_scene.name}"
        scene_text = build_inject_text(target_scene, transition_text=transition)
        if scene_text.strip():
            self._stores.runtime.update_snapshot(question.world_id, scene_text)
        self._record_location_snapshot(
            question.world_id,
            scene=target_scene,
            scene_text=scene_text,
            reason=LocationSnapshotReason.move,
        )
        packet = ScenePacket(
            event_id="",
            world_id=question.world_id,
            scene_text=scene_text,
            location_id=target_scene.location_id,
        )
        resolved = ResolvedOutcome(
            event_id="",
            world_id=question.world_id,
            resolution_text=transition,
        )
        move_question = replace(
            question,
            scene_id=target_scene.id,
            cue=transition,
            question=f"移动到：{target_scene.name}",
        )
        return StoryBeatOutcome(
            question=move_question,
            answer=answer,
            scene_packet=packet,
            resolved=resolved,
            influence=StoryInfluence(salience=0.35, decision_importance="移动过渡。"),
        )

    def distill_arc(self, outcomes: list[StoryBeatOutcome]) -> str:
        steps = [item for item in outcomes if item is not None and not item.question.is_move]
        if not steps:
            return ""
        summary = "；".join(
            _clip_sentence(item.resolved.resolution_text, limit=110)
            for item in steps
            if item.resolved.resolution_text.strip()
        )
        return _clip_sentence(summary, limit=420)

    def with_arc(
        self,
        outcome: StoryBeatOutcome,
        *,
        outcomes: list[StoryBeatOutcome],
        objective_summary: str,
    ) -> StoryBeatOutcome:
        steps = tuple(
            GMExchange(
                question=item.question,
                answer=item.answer,
                scene_packet=item.scene_packet,
                resolved=item.resolved,
                kind="move" if item.question.is_move else "beat",
            )
            for item in outcomes
            if not item.question.is_move
        )
        return StoryBeatOutcome(
            question=outcome.question,
            answer=outcome.answer,
            scene_packet=outcome.scene_packet,
            resolved=outcome.resolved,
            dice_value=outcome.dice_value,
            dice_tendency=outcome.dice_tendency,
            influence=outcome.influence,
            scene_candidates=outcome.scene_candidates,
            arc_steps=steps,
            objective_summary=objective_summary,
        )

    def orchestrate(
        self,
        world_id: str,
        cue: str,
        *,
        kind: StoryEventKind | str = StoryEventKind.fabricate,
        answer_text: str | None = None,
        dice: DiceResult | None = None,
        with_dice: bool = True,
        start_policy: ArcStartPolicy | str = ArcStartPolicy.history,
    ) -> StoryBeatOutcome:
        question = self.ask(world_id, cue, kind=kind, start_policy=start_policy)
        text = (answer_text or "").strip() or self._default_answer(cue, kind)
        answer = GMAnswer(
            question_id=question.question_id,
            text=text,
            intent=text,
        )
        return self.answer(
            question,
            answer,
            dice=dice,
            with_dice=with_dice,
        )

    def _default_answer(self, cue: str, kind: StoryEventKind | str) -> str:
        kind_v = _kind_value(kind)
        if kind_v == StoryEventKind.surprise.value:
            return "你来不及细想，只能先应对眼前这突发状况。"
        if kind_v == StoryEventKind.landmark.value:
            return cue.strip() or "你按自己的意愿继续这一时刻。"
        return "你稍作停顿，决定先看清眼前再行动。"

    def _find_home_scene(self, world_id: str) -> SceneUnit | None:
        for scene in self._scene_network.list_scenes(world_id):
            if "home" in scene.tags or scene.name.strip() in ("家", "home"):
                return scene
        return None

    def _pick_scene(
        self,
        world_id: str,
        cue: str,
        *,
        current_scene_id: str | None = None,
    ) -> tuple[SceneUnit, list[SceneCandidate]]:
        current_id = current_scene_id
        if current_id is None:
            current_id = self._scene_network.resolve_current_scene_id(world_id)
        home = self._find_home_scene(world_id)
        if current_id is None and home is not None:
            current_id = home.id
        current = self._scene_network.get(current_id) if current_id else None
        query_candidates = self._scene_network.locate_candidates(
            world_id,
            cue,
            current_scene_id=current_id,
            limit=3,
        )
        weighted: list[tuple[SceneUnit, int, str]] = []
        if current is not None:
            weighted.append((current, 40, "current"))
        for edge in self._scene_network.out_edges(current_id) if current_id else []:
            target = self._scene_network.get(edge.to_scene_id)
            if target is not None:
                weighted.append((target, max(5, edge.weight), "edge"))
        for cand in query_candidates:
            weighted.append((cand.scene, max(5, cand.score), cand.matched_by or "query"))
        if not weighted and home is not None:
            weighted.append((home, 30, "home"))
        if not weighted:
            scenes = self._scene_network.list_scenes(world_id)
            if not scenes:
                raise ValueError(f"no scenes in world: {world_id}")
            weighted.append((scenes[0], 10, "fallback"))
        pool: dict[str, tuple[SceneUnit, int, str]] = {}
        for scene, weight, tag in weighted:
            prev = pool.get(scene.id)
            if prev is None or weight > prev[1]:
                pool[scene.id] = (scene, weight, tag)
        items = list(pool.values())
        total = sum(w for _, w, _ in items)
        pick = random.uniform(0, total)
        acc = 0.0
        chosen = items[0][0]
        for scene, weight, _ in items:
            acc += weight
            if pick <= acc:
                chosen = scene
                break
        return chosen, query_candidates

    def _compose_question(
        self,
        *,
        world_id: str,
        cue: str,
        kind: StoryEventKind | str,
        scene: SceneUnit,
    ) -> tuple[str, str, list[str], bool, str]:
        if self._llm is None:
            kind_v = _kind_value(kind)
            if kind_v == StoryEventKind.surprise.value:
                return (
                    f"在{scene.name}，意外打断了你——你第一反应是什么？",
                    "突发状况可能改变接下来几刻的节奏。",
                    ["先稳住自己", "立刻查看异动", "退回熟悉的位置"],
                    True,
                    "",
                )
            return (
                f"此刻你在{scene.name}，{cue.strip() or '周围安静'}——你打算怎么做？",
                "这一拍的选择会影响你接下来的状态。",
                ["靠近并观察", "停下来倾听", "先整理自己的判断"],
                True,
                "",
            )
        prompt = (
            f"【场景】\n{scene.name}：{scene.narrative[:200]}\n\n"
            f"【本拍类型】\n{_kind_value(kind)}\n\n"
            f"【线索】\n{cue.strip() or '（无）'}\n\n"
        )
        cards = scene_cards(scene)
        if cards:
            prompt += "【绑定场景互动卡片】\n"
            for card in cards:
                affordances = "、".join(card.affordances) if card.affordances else "（无）"
                conditions = "、".join(card.conditions) if card.conditions else "（无）"
                prompt += (
                    f"- {card.title}：{card.description[:80]}；"
                    f"可互动：{affordances}；使用条件：{conditions}\n"
                )
            prompt += "\n"
        if "journal_landmark" in cue:
            prompt += (
                "【公开 journal 意图】\n"
                "以上线索包含 Soul 预约的公开行动意图；"
                "你只能据此提出问题和可选行动，不得替角色决定最终选择或内心动机。"
                "不要新增 journal 未声明的线索、角色、物件或悬疑支线；"
                "选项只能围绕该意图的可观察行动展开。"
            )
            if "journal_landmark_agenda" in cue:
                prompt += (
                    "议程已绑定固定 scene 与 cards；"
                    "不得离开绑定 scene，不得引入 cards 未覆盖的新地点或物件。"
                )
            prompt += "\n\n"
        prompt += "提出主持问题："
        raw = self._llm.generate_messages(
            [SystemMessage(content=_ASK_SYSTEM), HumanMessage(content=prompt)]
        ).strip()
        question = _extract_tag(raw, "QUESTION") or raw[:60]
        stakes = _extract_tag(raw, "STAKES")
        open_raw = _extract_tag(raw, "OPEN_CHOICE").strip().lower()
        open_choice = open_raw not in {"false", "0", "no", "否", "不开放"}
        choices_raw = _extract_tag(raw, "CHOICES")
        choices = [
            re.sub(r"^\s*[-*]\s*", "", line).strip()
            for line in choices_raw.splitlines()
            if re.sub(r"^\s*[-*]\s*", "", line).strip()
        ][:3]
        constraints = _extract_tag(raw, "CONSTRAINTS")
        return question.strip(), stakes.strip(), choices, open_choice, constraints.strip()

    def _influence_from(
        self,
        dice: DiceResult,
        kind: StoryEventKind | str,
        *,
        decision_importance: DecisionImportance | None = None,
    ) -> StoryInfluence:
        kind_v = _kind_value(kind)
        base = 0.5
        if kind_v == StoryEventKind.surprise.value:
            base = 0.55
            emotion_hint = "意外"
            mood_span = "短促"
            linger = 1
        elif kind_v == StoryEventKind.landmark.value:
            base = 0.6
            emotion_hint = "专注"
            mood_span = "中等"
            linger = 2
        else:
            emotion_hint = "平静"
            mood_span = "短暂"
            linger = 1
        if dice.value >= 75:
            salience = min(0.85, base + 0.15)
            emotion_hint = f"{emotion_hint}·顺畅"
        elif dice.value <= 30:
            salience = min(0.75, base + 0.1)
            emotion_hint = f"{emotion_hint}·阻滞"
        else:
            salience = base
        if decision_importance is not None:
            salience = max(salience, decision_importance.salience)
            mood_span = decision_importance.mood_span
            linger = max(linger, decision_importance.linger_days)
        return StoryInfluence(
            salience=salience,
            emotion_hint=emotion_hint,
            mood_span=mood_span,
            linger_days=linger,
            decision_importance=(
                decision_importance.hint if decision_importance is not None else ""
            ),
        )
