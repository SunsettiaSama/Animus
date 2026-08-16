from __future__ import annotations

from unittest.mock import MagicMock

from test.soul.speak.compose_helpers import finish_turn_for_test as finish_turn_bundle
from agent.soul.speak.responders.request_driven.orchestrator.bundle import SpeakPromptBundle
from agent.soul.speak.responders.request_driven.orchestrator.blocks.guidance.control import (
    GuidanceControlService,
    GuidancePlanInput,
)
from agent.soul.speak.responders.request_driven.orchestrator.blocks.guidance.runtime.control import (
    NARRATIVE_MAX_CHARS,
)
from agent.soul.speak.responders.request_driven.orchestrator.blocks.guidance.layer import SpeakGuidanceLayer
from agent.soul.speak.responders.request_driven.orchestrator.io import OrchestratorIOHub
from agent.soul.speak.responders.request_driven.orchestrator.io.inbound.guidance import GuidancePlanRequest
from agent.soul.speak.responders.request_driven.orchestrator.blocks.persona import SpeakPersonaLayer
from agent.soul.speak.session.manage.coordinator import SessionSocialManager
from config.soul.presence.config import SHARE_INTENT_QUEUE_MAX_ITEMS


def _registry_mock(*, turn_index: int = 3):
    registry = MagicMock()
    registry.get.return_value = MagicMock(generation=1)
    registry.current_turn_index.return_value = turn_index
    return registry


def test_control_state_narrative_is_capped_and_has_version():
    control = GuidanceControlService()
    state = control.plan_and_set(
        GuidancePlanInput(
            session_id="tao",
            turn_index=1,
            distilled_context="你们在去冒险家协会的路上偶遇。",
            persona_portrait="你是博物学家，开朗乐观。",
            interactor_portrait="荧，好朋友。",
            share_preview="",
            recall_preview="",
            last_rhythm_brief="",
            share_queue_count=0,
            share_queue_full=False,
            trigger="init",
        )
    )
    assert state.version == 1
    assert len(state.narrative) <= NARRATIVE_MAX_CHARS
    assert "用户" in state.narrative
    assert "你" in state.narrative


def test_share_queue_full_triggers_control_refresh():
    control = GuidanceControlService()
    io = OrchestratorIOHub.from_control_service(control)
    request = GuidancePlanRequest(
        session_id="tao",
        turn_index=2,
        distilled_context="近期对话：互相打了招呼。",
        persona_portrait="你是博物学家。",
        interactor_portrait="荧。",
        share_preview="- [0] 地底蜥蜴（意愿：strong）",
        share_queue_count=SHARE_INTENT_QUEUE_MAX_ITEMS,
        share_queue_full=True,
        trigger="share_queue_full",
    )
    assert io.inbound.guidance.sync_for_compose(request, force=True) is True
    snapshot = io.outbound.guidance.snapshot("tao")
    assert snapshot is not None
    assert snapshot["share_linked"] is True


def test_finish_turn_bundle_injects_guidance_narrative():
    control = GuidanceControlService()
    io = OrchestratorIOHub.from_control_service(control)
    social = SessionSocialManager(registry=_registry_mock())
    persona = SpeakPersonaLayer()
    persona.self_narrative = "你是博物学家。"
    persona.dialogue_compressed = "你们在路上偶遇。"
    bundle = SpeakPromptBundle(
        session_id="tao",
        persona=persona,
        guidance=SpeakGuidanceLayer(
            interactor_portrait="荧。",
            recall_preview="- 上次在纳塔地底见过蜥蜴",
        ),
    )
    from agent.soul.speak.responders.request_driven.orchestrator.director.types import DirectorPlan, ModuleDecision

    director_plan = DirectorPlan(
        session_id="tao",
        target_turn_index=2,
        modules=(
            ModuleDecision("persona", False, True, "test"),
            ModuleDecision("scene", False, True, "test"),
            ModuleDecision("guidance", True, True, "test", guidance_trigger="init"),
            ModuleDecision("context", False, True, "test"),
            ModuleDecision("memory", False, True, "test"),
            ModuleDecision("social", False, False, "test"),
            ModuleDecision("share", False, False, "test"),
        ),
    )
    finish_turn_bundle(
        bundle,
        social=social,
        session_id="tao",
        user_text="嗨",
        turn_index=2,
        io=io,
        share_queue_count=0,
        director_plan=director_plan,
    )
    assert "用户" in bundle.guidance.control_arc and "你" in bundle.guidance.control_arc
    assert bundle.meta.get("guidance_control_version") == 1


def test_version_increments_on_replan():
    control = GuidanceControlService()
    io = OrchestratorIOHub.from_control_service(control)
    io.inbound.guidance.plan(GuidancePlanRequest(session_id="tao", turn_index=1, trigger="init"))
    io.inbound.guidance.plan(GuidancePlanRequest(session_id="tao", turn_index=2, trigger="turn"))
    assert io.outbound.guidance.version("tao") == 2


def test_clear_control_arc():
    control = GuidanceControlService()
    io = OrchestratorIOHub.from_control_service(control)
    io.inbound.guidance.plan(GuidancePlanRequest(session_id="tao", turn_index=1, trigger="init"))
    io.inbound.guidance.clear_control_arc("tao")
    assert io.outbound.guidance.snapshot("tao") is None


def test_recall_candidates_penalize_repeat_pick():
    from types import SimpleNamespace

    from agent.soul.speak.responders.request_driven.orchestrator.blocks.guidance.runtime.memory.candidates import (
        build_recall_candidates_from_pull,
    )
    from agent.soul.speak.responders.request_driven.orchestrator.blocks.guidance.runtime.memory.pick_weights import (
        PICK_PENALTY_FACTOR,
        PICK_WEIGHT_FLOOR,
    )
    from agent.soul.speak.responders.request_driven.orchestrator.queue.memory import ComposeMemoryBuffer

    buffer = ComposeMemoryBuffer()
    session_id = "tao"
    pulled = SimpleNamespace(
        social_prefetch_lines=["唯一 social"],
        social_prefetch_unit_ids=["soc-1"],
        warm_spread_lines=[],
        warm_spread_unit_ids=[],
        inject=SimpleNamespace(lines=[], unit_ids=[]),
    )
    first = build_recall_candidates_from_pull(
        pulled,
        session_id=session_id,
        pick_weights=buffer,
    )
    assert len(first) == 1
    assert first[0].unit_id == "soc-1"
    weight_after = buffer.recall_pick_weight(session_id, "soc-1")
    assert weight_after == max(PICK_WEIGHT_FLOOR, PICK_PENALTY_FACTOR)
    assert weight_after < 1.0


def test_planner_does_not_emit_share_or_recall():
    from agent.soul.speak.responders.request_driven.orchestrator.blocks.guidance.runtime.control.planner import (
        GuidancePlanInput,
        _state_from_parsed,
        _ParsedPlan,
    )

    data = GuidancePlanInput(
        session_id="tao",
        turn_index=1,
        distilled_context="",
        persona_portrait="",
        interactor_portrait="",
        share_preview="- [0] topic",
        recall_preview="",
        share_queue_count=1,
        share_queue_full=False,
        trigger="turn",
    )
    state = _state_from_parsed(
        data,
        _ParsedPlan(narrative="用户还在。你先用一条短消息接住对方，说到哪停就停。"),
        version=1,
    )
    assert state.emit_share_queue_index is None
    assert state.emit_recall_unit_id is None
    assert state.share_linked is False


def test_fallback_does_not_force_share_or_recall_tags():
    control = GuidanceControlService()
    state = control.plan_and_set(
        GuidancePlanInput(
            session_id="tao",
            turn_index=2,
            distilled_context="你们在去冒险家协会的路上偶遇。",
            persona_portrait="你是博物学家。",
            interactor_portrait="荧。",
            share_preview="- [0] 地底蜥蜴（意愿：strong）",
            recall_preview="- 曾在雨夜与同伴失散",
            last_rhythm_brief="",
            share_queue_count=SHARE_INTENT_QUEUE_MAX_ITEMS,
            share_queue_full=True,
            trigger="share_queue_full",
        )
    )
    assert "（分享：" not in state.narrative
    assert "（回忆：" not in state.narrative
    assert state.share_linked is True


def test_guidance_fallback_keeps_the_character_moving():
    control = GuidanceControlService()
    state = control.plan_and_set(
        GuidancePlanInput(
            session_id="tao",
            turn_index=2,
            distilled_context="",
            persona_portrait="",
            interactor_portrait="",
            share_preview="",
            recall_preview="",
            last_rhythm_brief="",
            share_queue_count=0,
            share_queue_full=False,
            trigger="init",
        )
    )
    assert "短消息" in state.narrative


def test_planner_prompt_grounds_user_and_scene():
    from agent.soul.speak.responders.request_driven.orchestrator.blocks.guidance.runtime.control.planner import (
        GuidancePlanInput,
        _build_planner_user_prompt,
    )

    prompt = _build_planner_user_prompt(
        GuidancePlanInput(
            session_id="tao",
            turn_index=2,
            distilled_context="",
            persona_portrait="你是博物学家，常聊生灵趣事。",
            interactor_portrait="",
            share_preview="",
            recall_preview="",
            user_text="灯罩上哪有蚊子啦，在干嘛；",
            scene_brief="灯下翻看手稿扉页，放大镜贴着纸面看水印。",
            trigger="turn",
        )
    )
    assert "【本拍用户原文】" in prompt
    assert "灯罩上哪有蚊子啦" in prompt
    assert "手稿扉页" in prompt
    assert "只可引用此块已写明的物件" in prompt
    assert "补成完整一拍" in prompt
    assert "薄剧情 unit" in prompt


def test_planner_prompt_forbids_invented_props_when_scene_empty():
    from agent.soul.speak.responders.request_driven.orchestrator.blocks.guidance.runtime.control.planner import (
        GuidancePlanInput,
        _build_planner_user_prompt,
    )

    prompt = _build_planner_user_prompt(
        GuidancePlanInput(
            session_id="tao",
            turn_index=1,
            distilled_context="",
            persona_portrait="你是博物学家。",
            interactor_portrait="",
            share_preview="",
            recall_preview="",
            trigger="init",
        )
    )
    assert "【当前临场/剧情】空" in prompt
    assert "禁止点名具体物件" in prompt
    assert "动作与节奏写具体" in prompt
    assert "分享候选" not in prompt
    assert "回忆候选" not in prompt
    assert "emit_share" not in prompt
    assert "emit_recall" not in prompt
    assert "格式示例" not in prompt
    assert "当前没有新增输入" not in prompt


def test_ungrounded_init_skips_llm():
    llm = MagicMock()
    control = GuidanceControlService(llm=llm)
    state = control.plan_and_set(
        GuidancePlanInput(
            session_id="tao",
            turn_index=1,
            distilled_context="",
            persona_portrait="你是博物学家，爱谈鹿与叶脉。",
            interactor_portrait="",
            share_preview="",
            recall_preview="",
            trigger="init",
        )
    )
    llm.generate.assert_not_called()
    assert "短消息" in state.narrative
    assert "鹿" not in state.narrative
    assert "叶脉" not in state.narrative
    assert "小牌" not in state.narrative


def test_grounded_turn_calls_llm():
    llm = MagicMock()
    llm.generate.return_value = MagicMock(
        text=(
            '{"narrative": "用户问灯罩上有没有蚊子。你先短句接住这句调侃，'
            '再把手稿上的观察往前推一步，语气轻松。"}'
        )
    )
    control = GuidanceControlService(llm=llm)
    state = control.plan_and_set(
        GuidancePlanInput(
            session_id="tao",
            turn_index=2,
            distilled_context="",
            persona_portrait="你是博物学家。",
            interactor_portrait="",
            share_preview="",
            recall_preview="",
            user_text="灯罩上哪有蚊子啦，在干嘛；",
            scene_brief="灯下翻看手稿扉页。",
            trigger="turn",
        )
    )
    llm.generate.assert_called_once()
    prompt = llm.generate.call_args.args[0]
    assert "灯罩上哪有蚊子啦" in prompt
    assert "手稿扉页" in prompt
    assert "手稿" in state.narrative


def test_planner_system_requires_action_enrichment():
    from agent.soul.speak.responders.request_driven.orchestrator.blocks.guidance.runtime.control.planner import (
        _PLANNER_SYSTEM,
    )

    assert "手头动作与节奏" in _PLANNER_SYSTEM
    assert "剧情 unit 偏薄" in _PLANNER_SYSTEM
    assert "不要让她写 body" in _PLANNER_SYSTEM
    assert "不要代替角色开口" in _PLANNER_SYSTEM
    assert "不要写她会说的原句" in _PLANNER_SYSTEM
    assert "100–280" in _PLANNER_SYSTEM


def test_fallback_with_scene_completes_the_beat():
    control = GuidanceControlService()
    state = control.plan_and_set(
        GuidancePlanInput(
            session_id="tao",
            turn_index=2,
            distilled_context="",
            persona_portrait="",
            interactor_portrait="",
            share_preview="",
            recall_preview="",
            user_text="上面写的什么",
            scene_brief="灯下翻看手稿扉页。",
            trigger="turn",
        )
    )
    assert "上面写的什么" in state.narrative
    assert "动作" in state.narrative
    assert "短消息" in state.narrative


def test_fallback_mentions_user_text():
    control = GuidanceControlService()
    state = control.plan_and_set(
        GuidancePlanInput(
            session_id="tao",
            turn_index=2,
            distilled_context="",
            persona_portrait="",
            interactor_portrait="",
            share_preview="",
            recall_preview="",
            user_text="上面写的什么，你有看出些什么名堂么",
            trigger="turn",
        )
    )
    assert "上面写的什么" in state.narrative


def test_on_turn_complete_consumes_remaining_turns():
    control = GuidanceControlService()
    control.plan_and_set(
        GuidancePlanInput(
            session_id="tao",
            turn_index=1,
            distilled_context="",
            persona_portrait="",
            interactor_portrait="",
            share_preview="",
            recall_preview="",
            last_rhythm_brief="",
            share_queue_count=0,
            share_queue_full=False,
            trigger="init",
        )
    )
    control.on_turn_complete("tao", session_state="finish")
    active = control.active("tao")
    assert active is not None
    assert active.remaining_turns == 2
