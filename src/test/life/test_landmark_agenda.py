from __future__ import annotations

import json
from pathlib import Path

from agent.soul.life.virtual.journal import (
    JournalStore,
    Landmark,
    LandmarkStatus,
    LifeJournal,
)
from agent.soul.life.virtual.journal.agenda import (
    LandmarkAgenda,
    LandmarkAgendaRevision,
    LandmarkAgendaStatus,
    LandmarkAgendaStore,
    build_landmark_agenda_public_cue,
)
from agent.soul.life.virtual.journal.agenda.planner import LandmarkAgendaPlanner
from agent.soul.life.virtual.journal.agenda.tools import (
    AgendaToolBundle,
    LifeJournalLookupAdapter,
    StorySceneGroundingPort,
)
from agent.soul.life.virtual.journal.legacy import LifeJournal as LegacyLifeJournal
from agent.soul.life.virtual.journal.planner import _ContinuityMemoryRecallAdapter


def test_legacy_import_compatibility():
    assert LandmarkStatus.pending.value == "pending"
    assert LegacyLifeJournal is LifeJournal
    journal = LifeJournal()
    lm = journal.add_landmark("整理标本册", "2026-06-29T08:00:00+00:00", "书桌前")
    assert lm is not None
    assert isinstance(lm, Landmark)


def test_landmark_agenda_store_roundtrip(tmp_path: Path):
    store = LandmarkAgendaStore(str(tmp_path))
    agenda = LandmarkAgenda.new_draft(
        target_date="2026-06-29",
        title="整理标本册",
        summary="明天上午核对并补全近期采集记录",
        full_context="我打算明天上午在书桌前整理标本册，把近期采集记录补全。",
    )
    agenda.scene_hint = "书桌"
    agenda.steps = ["打开标本册", "核对标签", "补写记录"]
    agenda.success_criteria = ["三本标本册标签完整"]
    agenda.constraints = ["不展开新的野外支线"]
    agenda.revision_trace.append(
        LandmarkAgendaRevision(
            round=1,
            thought="先检索手账",
            action="inspect_journal",
            observation="（无）",
            patch_summary="补充步骤",
        )
    )
    agenda.mark_finalized()

    store.append(agenda)
    loaded = store.get(agenda.id)
    assert loaded is not None
    assert loaded.title == agenda.title
    assert loaded.status == LandmarkAgendaStatus.finalized
    assert len(loaded.steps) == 3
    assert loaded.revision_trace[0].action == "inspect_journal"

    raw = json.loads((tmp_path / "landmark_agendas.json").read_text(encoding="utf-8"))
    assert isinstance(raw, list)
    assert raw[0]["id"] == agenda.id


class _FakeMemory:
    def recall(self, query: str) -> list[str]:
        return [f"与「{query}」相关的记忆：上次整理时漏了两页标签。"]


class _FakeJournal:
    def recent_done(self, *, limit: int = 5) -> list[str]:
        return ["核对放大镜"]

    def digest(self, *, days: int = 7) -> str:
        return "近期多在书桌前记录。"

    def all_intents(self) -> list[str]:
        return ["核对放大镜", "整理标本册"]


class _FakeChronicle:
    def recent_entries(self, *, tail: int = 20) -> list[str]:
        return ["昨天在书桌前补写了两条记录。"]

    def hot_experiences(self, *, hours: int = 48) -> list[str]:
        return ["刚才把放大镜放回抽屉。"]


class _FakeSceneGrounding(StorySceneGroundingPort):
    def ground_scene_for_cue(self, cue: str, *, policy=None):
        from storyview.types import SceneCard, SceneGroundingResult, SceneGroundingTraceEntry

        cards = (
            SceneCard(
                id="card-desk",
                title="记录台",
                description="整理与核对标本记录的台面。",
                affordances=("整理", "核对"),
            ),
            SceneCard(
                id="card-mark",
                title="样线标记",
                description="标定观察范围的位置。",
                affordances=("标记",),
            ),
            SceneCard(
                id="card-safe",
                title="安全观察点",
                description="暂停并复核判断的位置。",
                affordances=("观察",),
            ),
        )
        scene_name = "书桌"
        if "断崖" in cue:
            scene_name = "断崖观察点"
        return SceneGroundingResult(
            scene_id="scene-grounded-1",
            scene_name=scene_name,
            matched_by="existing",
            score=8,
            cards=cards,
            trace=(
                SceneGroundingTraceEntry(
                    round=1,
                    action="match_existing",
                    observation=f"绑定 {scene_name}",
                ),
            ),
            narrative=f"{scene_name} 的固定工作场景。",
        )


def _agenda_tools() -> AgendaToolBundle:
    return AgendaToolBundle(
        memory=_FakeMemory(),
        journal=_FakeJournal(),
        chronicle=_FakeChronicle(),
        scene_grounding=_FakeSceneGrounding(),
    )


class _ScriptedLLM:
    def __init__(self, responses: list[str]) -> None:
        self._responses = list(responses)
        self.calls = 0

    def generate_messages(self, messages) -> str:
        if self.calls >= len(self._responses):
            raise RuntimeError("scripted LLM exhausted")
        text = self._responses[self.calls]
        self.calls += 1
        return text


def test_landmark_agenda_planner_converges_with_fake_llm():
    init_payload = {
        "title": "整理标本册",
        "summary": "明天整理近期采集记录",
        "full_context": "我打算明天整理标本册。",
        "scene_hint": "",
        "steps": ["打开标本册"],
        "success_criteria": [],
        "constraints": ["不展开新支线"],
    }
    decide_recall = {
        "thought": "先查记忆",
        "action": "recall_memory",
        "query": "标本册",
    }
    revise_after_recall = {
        "thought": "补充上下文",
        "patches": [
            {
                "op": "add_sentence",
                "text": "我要在书桌前把近期采集记录补全，并核对标签是否与野外记录一致。",
            },
            {
                "op": "add_sentence",
                "text": "这次整理的重点是补齐遗漏页，并为下一次外出核对保留清晰索引。",
            },
            {"op": "append_ref", "field": "memory_refs", "text": "上次漏了两页标签"},
        ],
        "patch_summary": "补充 full_context 与 memory_refs",
    }
    decide_journal = {
        "thought": "查看手账",
        "action": "inspect_journal",
    }
    revise_after_journal = {
        "thought": "补齐结构",
        "patches": [
            {"op": "set_field", "field": "scene_hint", "text": "书桌"},
            {
                "op": "set_list",
                "field": "steps",
                "items": [
                    "在记录台打开标本册",
                    "在记录台核对标签",
                    "在样线标记补写记录",
                ],
            },
            {
                "op": "set_list",
                "field": "success_criteria",
                "items": ["三本标本册标签完整"],
            },
            {
                "op": "add_sentence",
                "text": "完成后我会把需要复查的标本单独标记，避免下次外出前再次遗漏。",
            },
            {"op": "append_ref", "field": "journal_refs", "text": "近期多在书桌前记录"},
        ],
        "patch_summary": "补齐 scene/steps/success",
    }
    decide_finish = {"thought": "可以收敛", "action": "finish"}

    llm = _ScriptedLLM(
        [
            json.dumps(init_payload, ensure_ascii=False),
            json.dumps(decide_recall, ensure_ascii=False),
            json.dumps(revise_after_recall, ensure_ascii=False),
            json.dumps(decide_journal, ensure_ascii=False),
            json.dumps(revise_after_journal, ensure_ascii=False),
            json.dumps(decide_finish, ensure_ascii=False),
            json.dumps(decide_finish, ensure_ascii=False),
        ]
    )
    tools = _agenda_tools()
    planner = LandmarkAgendaPlanner(llm, tools, max_rounds=6)
    result = planner.compose_tomorrow_agenda(
        profile_narrative="你是博物学家。",
        world_background="边境营地",
        target_date="2026-06-29",
        recent_landmark_intents=["核对放大镜"],
    )

    agenda = result.agenda
    assert agenda.title == "整理标本册"
    assert agenda.scene_id == "scene-grounded-1"
    assert agenda.scene_name == "书桌"
    assert len(agenda.scene_cards) == 3
    assert agenda.scene_hint == "书桌"
    assert len(agenda.steps) == 3
    assert agenda.success_criteria
    assert "书桌前" in agenda.full_context
    assert agenda.memory_refs
    assert agenda.journal_refs
    assert any(item.action == "finish" for item in result.revision_trace)


def test_landmark_agenda_planner_dedupes_near_duplicate_context_sentences():
    init_payload = {
        "title": "哨塔断崖的鸣禽观察",
        "summary": "明天记录断崖边清晨鸣禽。",
        "full_context": (
            "那个区域尚未正式踏勘，崖壁缝隙和矮林可能支撑小型集群栖息。"
            "我计划在日出后30分钟内抵达现场，安静记录鸣声特征、个体数目和飞行路径。"
            "那个区域尚未正式踏勘，但崖壁上的缝隙和矮林可能支撑小型集群栖息。"
            "我需要在天光稳定后抵达现场，安静记录鸣声特征、个体数目和可能的飞行路径。"
            "完成记录后我会在原地核对时间、风向和可见个体数量，确保返回营地前留下完整基线。"
        ),
        "scene_hint": "晨光初透的断崖边缘",
        "steps": ["在记录台检查记录本", "在安全观察点记录鸣声与数量", "在样线标记核对时间"],
        "success_criteria": ["完成三段连续鸣声记录"],
        "constraints": ["不靠近崖缘"],
    }
    decide_finish = {"thought": "可以收敛", "action": "finish"}
    llm = _ScriptedLLM(
        [
            json.dumps(init_payload, ensure_ascii=False),
            json.dumps(decide_finish, ensure_ascii=False),
        ]
    )
    tools = _agenda_tools()
    planner = LandmarkAgendaPlanner(llm, tools, max_rounds=2)

    result = planner.compose_tomorrow_agenda(
        profile_narrative="你是博物学家。",
        world_background="边境营地",
        target_date="2026-06-29",
    )

    context = result.agenda.full_context
    assert context.count("那个区域尚未正式踏勘") == 1
    assert context.count("安静记录鸣声特征") == 1


def test_continuity_memory_recall_adapter_imports_life_narrative_context():
    class _FakeVirtual:
        continuity_memories = ["记忆线索"]
        calls = []

        def ensure_narrative_context(self, purpose, *, query: str = "") -> None:
            self.calls.append((purpose.value, query))

    virtual = _FakeVirtual()
    lines = _ContinuityMemoryRecallAdapter(virtual).recall("标本册")

    assert lines == ["记忆线索"]
    assert virtual.calls == [("compose", "标本册")]


def test_life_journal_lookup_adapter_uses_legacy_digest_signature():
    journal = LifeJournal()
    journal.set_narrative("近期一直在整理低地植物记录。")
    journal.add_landmark("检查标本夹", "2026-06-29T08:00:00+00:00", "书桌")

    tools = AgendaToolBundle(
        memory=_FakeMemory(),
        journal=LifeJournalLookupAdapter(journal),
        chronicle=_FakeChronicle(),
        scene_grounding=_FakeSceneGrounding(),
    )
    text = tools.inspect_journal()

    assert "手账摘要" in text
    assert "检查标本夹" in text
    assert "近期一直在整理低地植物记录。" in text


def test_landmark_agenda_public_cue_contains_key_fields():
    agenda = LandmarkAgenda.new_draft(
        target_date="2026-06-29",
        title="整理标本册",
        summary="明天整理近期采集记录",
        full_context="我打算明天在书桌前整理标本册，把近期采集记录补全。",
    )
    agenda.scene_hint = "书桌"
    agenda.scene_id = "scene-desk"
    agenda.scene_name = "书桌"
    agenda.scene_cards = list(_FakeSceneGrounding().ground_scene_for_cue("").cards)
    agenda.steps = ["打开标本册", "核对标签", "补写记录"]
    agenda.success_criteria = ["三本标本册标签完整"]
    agenda.constraints = ["不展开新的野外支线"]

    cue = build_landmark_agenda_public_cue(agenda)
    assert "journal_landmark_agenda" in cue
    assert agenda.title in cue
    assert agenda.summary in cue
    assert agenda.full_context in cue
    assert agenda.scene_hint in cue
    assert agenda.scene_id in cue
    assert "记录台" in cue
    assert agenda.steps[0] in cue
    assert agenda.success_criteria[0] in cue
    assert agenda.constraints[0] in cue
    assert "主持规则" in cue


def test_fill_landmark_agenda_requires_scene_id():
    import pytest

    from agent.soul.life.virtual.layer import VirtualLayer

    layer = VirtualLayer(builder=None, life_dir=str(Path("unused")))
    agenda = LandmarkAgenda.new_draft(
        target_date="2026-06-29",
        title="整理标本册",
        summary="明天整理",
        full_context="我打算明天整理标本册。",
    )
    agenda.mark_finalized()
    with pytest.raises(RuntimeError, match="scene_id"):
        layer.fill_landmark_agenda(agenda)


def test_journal_store_still_uses_legacy_path(tmp_path: Path):
    store = JournalStore(str(tmp_path))
    journal = LifeJournal()
    journal.add_landmark("测试", "2026-06-29T08:00:00+00:00")
    store.save(journal)
    assert (tmp_path / "journal.json").exists()
