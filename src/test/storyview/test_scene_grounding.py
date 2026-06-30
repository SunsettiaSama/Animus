from __future__ import annotations

import json
from pathlib import Path

from infra.storage import JsonStorageService
from storyview.engine import StoryEngine
from storyview.gm.story import StoryDirector
from storyview.scene import SceneComposer
from storyview.scene.cards import cards_from_meta, cards_to_meta
from storyview.scene.drafting import SceneDraftingEngine
from storyview.scene.grounding import SceneGroundingService
from storyview.scene.network import SceneNetwork
from storyview.gm.resolve import ActionResolver
from storyview.store.json import StoryStoreBundle
from storyview.types import (
    SceneCard,
    SceneDraft,
    SceneGroundingPolicy,
    SceneGroundingTraceEntry,
    SceneReviewStatus,
    SceneUnit,
    StoryEventKind,
)
from storyview.world.inspector import WorldviewInspector
from storyview.world.provider import WorldviewProvider


def _engine(tmp_path: Path, *, llm=None) -> StoryEngine:
    stores = StoryStoreBundle(JsonStorageService(str(tmp_path)))
    return StoryEngine(stores, llm=llm)


def _seed_desk_scene(engine: StoryEngine, world_id: str = "w1") -> str:
    cards = [
        SceneCard(
            id="card-desk",
            title="书桌",
            description="整理记录的工作台面。",
            affordances=("整理", "核对"),
        ),
        SceneCard(
            id="card-note",
            title="记录本",
            description="补写采集记录的本子。",
            affordances=("记录",),
        ),
        SceneCard(
            id="card-lamp",
            title="台灯",
            description="提供稳定照明的固定光源。",
            affordances=("照明",),
        ),
    ]
    return engine.upsert_scene(
        world_id,
        name="窗边书桌",
        narrative="你在窗边书桌旁整理标本与记录。",
        tags=["desk", "home"],
        meta=cards_to_meta(cards),
    )


def test_grounding_matches_existing_scene_without_create(tmp_path: Path):
    engine = _engine(tmp_path)
    world_id = "w1"
    scene_id = _seed_desk_scene(engine, world_id)
    result = engine.ground_scene_for_cue(
        world_id,
        "书桌 整理 标本册",
        policy=SceneGroundingPolicy(allow_create=False, match_threshold=4),
    )
    assert result.scene_id == scene_id
    assert result.created is False
    assert result.matched_by in {"scene_name", "scene_narrative"}
    assert len(result.cards) == 3


def test_low_score_current_fallback_does_not_count_as_match(tmp_path: Path):
    engine = _engine(tmp_path)
    world_id = "w1"
    current_id = engine.upsert_scene(
        world_id,
        name="当前营地",
        narrative="你在营地休息。",
        tags=["camp"],
    )
    engine.apply_scene(world_id, current_id)
    result = engine.ground_scene_for_cue(
        world_id,
        "明天整理标本册",
        policy=SceneGroundingPolicy(allow_create=True, match_threshold=8),
    )
    assert result.created is True
    assert result.scene_id != current_id
    assert result.matched_by == "created"


def test_auto_create_persists_scene_cards(tmp_path: Path):
    engine = _engine(tmp_path)
    world_id = "w1"
    anchor_id = engine.upsert_scene(
        world_id,
        name="家",
        narrative="你在家里。",
        tags=["home"],
    )
    engine.apply_scene(world_id, anchor_id)
    result = engine.ground_scene_for_cue(
        world_id,
        "明天在记录台整理标本",
        policy=SceneGroundingPolicy(match_threshold=99),
    )
    assert result.created is True
    assert result.scene_id
    assert len(result.cards) >= 3
    scene = engine.scene_network.get(result.scene_id)
    assert scene is not None
    stored = cards_from_meta(scene.meta)
    assert len(stored) >= 3
    assert stored[0].title


def test_inspector_revision_then_approve(tmp_path: Path):
    provider = WorldviewProvider(_engine(tmp_path)._stores)
    inspector = WorldviewInspector(provider, llm=None)
    draft = SceneDraft(
        name="测试场景",
        narrative="",
        cards=(),
    )
    review = inspector.review_scene_draft("w1", "cue", draft)
    assert review.status == SceneReviewStatus.revision_required

    fixed = SceneDraft(
        name="测试场景",
        narrative="可工作的记录场景。",
        cards=(
            SceneCard(id="1", title="记录台", description="整理记录"),
            SceneCard(id="2", title="样线标记", description="标记位置"),
            SceneCard(id="3", title="安全观察点", description="暂停复核"),
        ),
    )
    approved = inspector.review_scene_draft("w1", "cue", fixed)
    assert approved.is_approved


def test_inspector_rechecks_llm_approved_draft_for_subjective_narrative(tmp_path: Path):
    class _BadApprovalLLM:
        def generate_messages(self, messages) -> str:
            return json.dumps(
                {
                    "keyword_groups": [
                        {
                            "name": "叙述客观性",
                            "keywords": ["固定场景", "客观描述"],
                            "purpose": "避免角色行动与日程进入 narrative",
                        },
                        {
                            "name": "世界观技术层级",
                            "keywords": ["低技术", "记录", "复核"],
                            "purpose": "确认工具和设施符合世界观",
                        },
                        {
                            "name": "场景网络",
                            "keywords": ["已有节点", "相邻场景"],
                            "purpose": "确认场景可挂载到网络",
                        },
                    ],
                    "review_questions": [
                        "narrative 是否只描述客观固定场景？",
                        "工具和设施是否符合世界观技术层级？",
                        "场景是否能合理挂载到已有网络？",
                    ],
                    "question_reviews": [
                        {
                            "question": "narrative 是否只描述客观固定场景？",
                            "verdict": "pass",
                            "reason": "原草案符合",
                            "suggestion": "",
                        },
                        {
                            "question": "工具和设施是否符合世界观技术层级？",
                            "verdict": "pass",
                            "reason": "低技术工具",
                            "suggestion": "",
                        },
                        {
                            "question": "场景是否能合理挂载到已有网络？",
                            "verdict": "pass",
                            "reason": "可挂载",
                            "suggestion": "",
                        },
                    ],
                    "status": "approved",
                    "reason": "看起来可用",
                    "approved_draft": {
                        "name": "北坡岩棚",
                        "narrative": "按照昨天日志的规划，今天的工作是去北坡建立观察点。",
                        "cards": [
                            {"id": "1", "title": "记录台", "description": "记录数据"},
                            {"id": "2", "title": "湿度计", "description": "读取湿度"},
                            {"id": "3", "title": "标尺", "description": "读取裂隙朝向"},
                        ],
                    },
                },
                ensure_ascii=False,
            )

    provider = WorldviewProvider(_engine(tmp_path)._stores)
    inspector = WorldviewInspector(provider, llm=_BadApprovalLLM())
    draft = SceneDraft(
        name="北坡岩棚",
        narrative="北坡岩棚设有固定观察边界。",
        cards=(
            SceneCard(id="1", title="记录台", description="记录数据"),
            SceneCard(id="2", title="湿度计", description="读取湿度"),
            SceneCard(id="3", title="标尺", description="读取裂隙朝向"),
        ),
    )

    review = inspector.review_scene_draft("w1", "cue", draft)
    assert review.status == SceneReviewStatus.revision_required
    assert "主观/日程叙述" in review.reason


def test_inspector_blocks_when_worldview_questions_do_not_pass(tmp_path: Path):
    class _QuestionReviewLLM:
        def generate_messages(self, messages) -> str:
            return json.dumps(
                {
                    "keyword_groups": [
                        {
                            "name": "技术层级",
                            "keywords": ["低技术", "手工记录"],
                            "purpose": "确认工具是否符合世界观",
                        },
                        {
                            "name": "场景网络",
                            "keywords": ["home", "相邻节点"],
                            "purpose": "确认场景是否能合理挂载",
                        },
                        {
                            "name": "叙事基调",
                            "keywords": ["观察", "复核", "克制"],
                            "purpose": "确认不变成现代科考或高冲突支线",
                        },
                    ],
                    "review_questions": [
                        "设备与材料是否符合低技术边境营地？",
                        "场景是否能从现有网络自然延伸？",
                        "场景是否保持观察、记录、复核的克制基调？",
                    ],
                    "question_reviews": [
                        {
                            "question": "设备与材料是否符合低技术边境营地？",
                            "verdict": "fail",
                            "reason": "草案引入现代传感器与相机支架。",
                            "suggestion": "改为木标杆、麻线、炭笔、粗陶罐和手工读数。",
                        },
                        {
                            "question": "场景是否能从现有网络自然延伸？",
                            "verdict": "pass",
                            "reason": "可从营地帐篷挂载。",
                            "suggestion": "",
                        },
                        {
                            "question": "场景是否保持观察、记录、复核的克制基调？",
                            "verdict": "weak",
                            "reason": "内容偏现代科考流程。",
                            "suggestion": "降低设备复杂度，保留自然志观察。",
                        },
                    ],
                    "status": "revision_required",
                    "reason": "技术层级问题未通过。",
                    "patches": [
                        {
                            "field": "narrative",
                            "value": "北坡岩棚设有木标杆、麻线样线、粗陶水罐与记录木牌。",
                        }
                    ],
                },
                ensure_ascii=False,
            )

    provider = WorldviewProvider(_engine(tmp_path)._stores)
    inspector = WorldviewInspector(provider, llm=_QuestionReviewLLM())
    draft = SceneDraft(
        name="北坡岩棚",
        narrative="北坡岩棚设有传感器安装螺口与相机支架。",
        cards=(
            SceneCard(id="1", title="传感器", description="读取湿度"),
            SceneCard(id="2", title="相机支架", description="拍照记录"),
            SceneCard(id="3", title="气象站", description="记录风速"),
        ),
    )

    review = inspector.review_scene_draft("w1", "cue", draft)
    assert review.status == SceneReviewStatus.revision_required
    assert "pass=1/3" in review.reason
    assert review.patches


def test_inspector_reject_returns_blocked(tmp_path: Path):
    stores = StoryStoreBundle(JsonStorageService(str(tmp_path)))
    stores.world.ensure(
        "w1",
        title="test",
        canon_json={"forbidden": ["史诗战争"], "must": [], "prefer": []},
    )
    provider = WorldviewProvider(stores)
    inspector = WorldviewInspector(provider, llm=None)
    bad_draft = SceneDraft(
        name="战场",
        narrative="爆发史诗战争的主战场。",
        cards=(
            SceneCard(id="1", title="战旗", description="史诗战争中心"),
            SceneCard(id="2", title="壕沟", description="前线"),
            SceneCard(id="3", title="指挥台", description="指挥"),
        ),
    )
    review = inspector.review_scene_draft("w1", "cue", bad_draft)
    assert review.status == SceneReviewStatus.rejected

    class _BadDraftDrafter:
        def draft_for_cue(self, *args, **kwargs) -> SceneDraft:
            return bad_draft

    network = SceneNetwork(stores.scene.nodes, stores.scene.edges, runtime=stores)
    service = SceneGroundingService(
        stores,
        network,
        worldview_provider=provider,
        inspector=inspector,
        drafter=_BadDraftDrafter(),
    )
    result = service.ground_scene_for_cue(
        "w1",
        "明天观察战场",
        policy=SceneGroundingPolicy(match_threshold=99),
    )
    assert result.blocked
    assert "forbidden" in result.blocked_reason.lower() or "违反" in result.blocked_reason


class _PickSceneTracker(StoryDirector):
    pick_calls = 0

    def _pick_scene(self, world_id: str, cue: str, *, current_scene_id=None):
        type(self).pick_calls += 1
        return super()._pick_scene(world_id, cue, current_scene_id=current_scene_id)


def test_ask_at_scene_does_not_call_pick_scene(tmp_path: Path):
    stores = StoryStoreBundle(JsonStorageService(str(tmp_path)))
    network = SceneNetwork(stores.scene.nodes, stores.scene.edges, runtime=stores)
    composer = SceneComposer(stores, llm=None, scene_network=network)
    resolver = ActionResolver(stores, llm=None)
    _PickSceneTracker.pick_calls = 0
    director = _PickSceneTracker(stores, network, composer, resolver, llm=None)
    world_id = "w1"
    scene_id = network.upsert_scene(
        world_id,
        name="书桌",
        narrative="整理标本的书桌。",
        meta=cards_to_meta(
            [
                SceneCard(id="a", title="记录台", description="整理"),
                SceneCard(id="b", title="样线标记", description="标记"),
                SceneCard(id="c", title="安全观察点", description="观察"),
            ]
        ),
    )
    question = director.ask_at_scene(
        world_id,
        scene_id,
        "【触发来源】journal_landmark_agenda\n整理标本",
        kind=StoryEventKind.landmark,
    )
    assert question.scene_id == scene_id
    assert _PickSceneTracker.pick_calls == 0


def test_scene_grounding_trace_serializes(tmp_path: Path):
    entry = SceneGroundingTraceEntry(round=1, action="draft_scene", observation="ok")
    payload = entry.to_dict()
    assert payload["action"] == "draft_scene"
