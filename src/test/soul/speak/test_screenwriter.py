from __future__ import annotations

import random
import time
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

from agent.soul.speak.responders.request_driven.layers import assemble_role_layers
from agent.soul.speak.responders.request_driven.composer.projectors.dynamic_layer import (
    DynamicLayerMaterials,
    DynamicLayerSchedule,
)
from agent.soul.speak.responders.request_driven.composer.projectors.role_view import (
    RoleContextView,
)
from agent.soul.speak.responders.request_driven.directors.agent.units import (
    AgentDeliveryTraceUnit,
    PollTickUnit,
    PresenceUnit,
    UserSilenceUnit,
)
from agent.soul.speak.responders.request_driven.directors.base import (
    DirectorOutput,
)
from agent.soul.speak.responders.request_driven.directors.coordinator import (
    DirectorCoordinator,
)
from agent.soul.speak.responders.request_driven.directors.fallback import (
    fallback_delivery_plan_for_silence,
    fallback_speak_gate,
)
from agent.soul.speak.responders.request_driven.screenwriter import (
    Screenwriter,
)
from agent.soul.speak.responders.request_driven.screenwriter.writer import (
    normalize_user_opening,
)
from agent.soul.speak.responders.request_driven.orchestrator.state.core.narrative_card import (
    SILENCE_OBSERVATION_PHRASES,
    SilenceLog,
    format_silence_log_line,
)
from agent.soul.speak.responders.request_driven.orchestrator.state.core.presence_card import (
    CharacterPresenceCard,
)
from agent.soul.speak.responders.request_driven.orchestrator.state.core.types import (
    DialogueSnapshot,
    OrchestratorDomainSnapshot,
    SessionRuntimeSnapshot,
    SessionSignals,
    SessionSnapshot,
)
from agent.soul.speak.responders.request_driven.orchestrator.state.runtime.store import (
    SessionSchedulingState,
    StateStore,
)


class _FakeStoryPort:
    def __init__(self) -> None:
        self.upserts: list[dict] = []
        self.gm_calls: list[dict] = []
        self.background = "世界观：帐篷。场景：标本台。"

    def render_background(self, world_id: str, *, query: str = "", purpose: str = "") -> str:
        del world_id, query, purpose
        return self.background

    def scene_inject_text(self, world_id: str, query: str = "") -> str:
        del world_id, query
        return "注入：蓟花标本"

    def locate_scene(self, world_id: str, query: str, *, current_scene_id: str | None = None):
        del world_id, query
        scene = SimpleNamespace(scene_id=current_scene_id or "sc-1", name="帐篷", narrative="旧叙事")
        return SimpleNamespace(scene=scene, inject_text="注入：蓟花标本")

    def upsert_scene(self, world_id: str, **kwargs):
        self.upserts.append({"world_id": world_id, **kwargs})
        return kwargs.get("scene_id") or "sc-1"

    def ask_gm_at_scene(self, world_id: str, scene_id: str, cue: str, *, kind=None):
        del kind
        q = SimpleNamespace(question_id="q1", world_id=world_id, scene_id=scene_id, cue=cue)
        self.gm_calls.append({"ask": cue, "scene_id": scene_id})
        return q

    def answer_gm(self, question, answer, *, with_dice: bool = True):
        self.gm_calls.append(
            {
                "answer": getattr(answer, "text", ""),
                "with_dice": with_dice,
                "question_id": getattr(question, "question_id", ""),
            }
        )
        return SimpleNamespace(ok=True)


def test_silence_phrases_are_ten_varied():
    assert len(SILENCE_OBSERVATION_PHRASES) == 10
    assert len(set(SILENCE_OBSERVATION_PHRASES)) == 10
    assert all("用户无输入" not in p for p in SILENCE_OBSERVATION_PHRASES)


def test_silence_log_appends_varied_phrases_and_clears():
    log = SilenceLog(_rng=random.Random(0))
    when = datetime(2026, 8, 15, 14, 32, 1)
    line1 = log.append_now(when=when)
    line2 = log.append_now(when=datetime(2026, 8, 15, 14, 32, 8))
    line3 = log.append_now(when=datetime(2026, 8, 15, 14, 32, 21))
    assert line1.startswith("2026-08-15 14:32:01——")
    assert "——" in line1
    assert line1.split("——", 1)[1] in SILENCE_OBSERVATION_PHRASES
    assert len(log.entries) == 3
    rendered = log.render()
    assert "无用户输入卡" in rendered
    assert "合理化" in rendered
    log.clear()
    assert not log.ready


def test_format_silence_log_line_explicit_phrase():
    line = format_silence_log_line(
        when=datetime(2026, 1, 1, 0, 0, 0),
        phrase="用户沉默着，场面没有被新话打断",
    )
    assert line == "2026-01-01 00:00:00——用户沉默着，场面没有被新话打断"


def test_presence_and_poll_units_render():
    presence = PresenceUnit(mood="松弛", brief="刚坐下", speak_desire=50, fate_tendency="中性")
    text = presence.render()
    assert "编剧·临场状态" in text
    assert "松弛" in text
    poll = PollTickUnit(poll_seq=2, now_ts=1.0, sec_since_user=12.0, last_idle_note="轮询过，无动作")
    ptext = poll.render()
    assert "轮询空卡" in ptext
    assert "上一拍=轮询过，无动作" in ptext
    silence = UserSilenceUnit(entries=("14:01:00——用户这一拍保持沉默",))
    assert "保持沉默" in silence.render()
    assert "叙事" in silence.render()


def test_screenwriter_init_writes_card_without_llm():
    state = SessionSchedulingState(session_id="s1")
    sw = Screenwriter(llm=None)
    out = sw.init_presence(state, session_id="s1")
    assert state.presence_card.ready
    assert state.narrative_card.ready
    assert state.plot_flow.ready
    assert state.plot_flow.chronicle
    assert out.payload["action"] == "advance"
    assert "screenwriter" in state.director_cache
    unit = sw.plot_flow_unit_from_state(state)
    assert unit is not None
    assert "剧情流" in unit.render()


def test_screenwriter_tick_on_silence_heuristic():
    state = SessionSchedulingState(session_id="s1")
    state.silence_log.append_now(phrase="用户或许正停顿思索，尚未开口")
    state.silence_log.append_now(phrase="对话空档仍在延续，用户未接话")
    sw = Screenwriter(llm=None)
    out = sw.tick_on_silence(state, session_id="s1", turn_index=1, force=True)
    assert out is not None
    assert state.plot_flow.ready
    assert state.narrative_card.ready
    assert "沉默" in state.plot_flow.chronicle or "停在" in state.plot_flow.chronicle


def test_unit_consume_does_not_wake_screenwriter():
    """消费剧情 unit 只落账，不按活队列长度唤醒编剧。"""
    from agent.soul.speak.responders.request_driven.orchestrator.state.core.interaction_plan import (
        InteractionUnit,
        PlotArc,
    )

    state = SessionSchedulingState(session_id="s1")
    state.poll_seq = 3
    units = [
        InteractionUnit(intent=f"步骤{i}", status="pending" if i else "active", span_polls=2)
        for i in range(5)
    ]
    units[0].status = "active"
    state.plot_arc = PlotArc(summary="测", units=units, version=1, initialized_at=1.0)
    state.presence_card = CharacterPresenceCard(mood="平静", brief="在场")
    sw = Screenwriter(llm=None)
    live_before = state.plot_arc.live_unit_count()
    sw.confirm_interaction_unit_complete(
        state,
        poll_seq=3,
        reason="test_consume",
        session_id="s1",
    )
    assert len(state.plot_arc.unit_history) == 1
    assert state.plot_arc.live_unit_count() == live_before - 1
    assert not any("align_on_exchange" in str(n) for n in state.notes)
    assert not any("refill_on_unit_consume" in str(n) for n in state.notes)


def test_maybe_refresh_after_speak_no_longer_wakes_on_count():
    state = SessionSchedulingState(session_id="s1")
    state.presence_card = CharacterPresenceCard(mood="旧", brief="旧简述")
    sw = Screenwriter(llm=None)
    assert sw.maybe_refresh_after_speak(state, session_id="s1", turn_index=1) is None
    assert sw.maybe_refresh_after_speak(state, session_id="s1", turn_index=2) is None
    assert sw.maybe_refresh_after_speak(state, session_id="s1", turn_index=3) is None
    assert state.agent_speak_count == 0


def test_screenwriter_upsert_scene_default():
    port = _FakeStoryPort()
    state = SessionSchedulingState(session_id="s1")
    sw = Screenwriter(
        llm=None,
        story_port=port,
        world_id_fn=lambda: "w1",
        resolve_scene_id_fn=lambda _sid: "sc-1",
    )
    decided = {
        "action": "rewrite",
        "mood": "好奇",
        "brief": "看着标本",
        "user_identity": "访客",
        "user_activity": "看标本",
        "scene_event": "双方同处帐篷。",
        "scene_delta": "标本台多了一枚蜡膜。",
        "structural": False,
        "reason": "t",
    }
    sw._apply_write(
        state,
        decided,
        speak_desire=55,
        fate_tendency="中性",
        turn_index=1,
        session_id="s1",
        allow_keep=False,
        speak_count=3,
    )
    assert port.upserts
    assert port.upserts[0]["scene_id"] == "sc-1"
    assert "蜡膜" in port.upserts[0]["narrative"]
    assert not port.gm_calls
    assert state.narrative_card.user_identity == "访客"


def test_screenwriter_structural_ask_gm_without_dice():
    port = _FakeStoryPort()
    state = SessionSchedulingState(session_id="s1")
    sw = Screenwriter(
        llm=None,
        story_port=port,
        world_id_fn=lambda: "w1",
        resolve_scene_id_fn=lambda _sid: "sc-1",
    )
    sw._apply_write(
        state,
        {
            "action": "rewrite",
            "mood": "警觉",
            "brief": "听到外头脚步",
            "user_identity": "访客",
            "user_activity": "停住",
            "scene_event": "帐外有脚步。",
            "scene_delta": "角色走到帐帘边。",
            "structural": True,
            "reason": "move",
        },
        speak_desire=60,
        fate_tendency="愿意接话",
        turn_index=2,
        session_id="s1",
        allow_keep=False,
        speak_count=3,
    )
    assert any(c.get("with_dice") is False for c in port.gm_calls if "with_dice" in c)


def test_soft_merge_fate_updates_desire_only():
    state = SessionSchedulingState(session_id="s1")
    state.presence_card = CharacterPresenceCard(mood="平静", brief="在场", speak_desire=40)
    sw = Screenwriter(llm=None)
    state.fate_speak_desire = 72
    sw.soft_merge_fate(state)
    assert state.presence_card.mood == "平静"
    assert state.presence_card.brief == "在场"
    assert state.presence_card.speak_desire == 72


def test_role_layers_render_silence_and_narrative():
    view = RoleContextView(session_id="s1")
    mats = DynamicLayerMaterials(session_id="s1")
    sched = DynamicLayerSchedule(reason="t")
    layers = assemble_role_layers(
        view,
        mats,
        sched,
        user_text="",
        presence_mood="平静",
        presence_brief="在场",
        user_identity="访客",
        user_activity="沉默着停在现场",
        plot_flow_text="[情景 unit]\n此刻在做：同场空档\n近况：双方同处一室，外在互动暂无新增。",
        silence_log_text="14:01:00——用户这一拍保持沉默\n14:01:08——对面安静着，没有听见回应",
    )
    text = layers.render_system_extra()
    assert "对方刚发来的即时往来" not in text
    # 剧情卡软约束化（拟人度评测 R3/R5 生产化）：头为软约束措辞 + 用户位置注记
    assert "此刻情景（软约束，参考，以对方的话为先）" in text
    assert "对方在剧情中的位置" in text
    assert "舞台信息" in text
    assert "临场事件纪要" not in text
    assert "沉默" in text


def test_fallback_delivery_plan_for_silence_nonempty():
    snap = SessionSnapshot(
        schema_version=1,
        snapshot_id="snap-1",
        session_id="s1",
        signals=SessionSignals(session_id="s1", turn_index=1, generation=1),
        runtime=SessionRuntimeSnapshot(),
        dialogue=DialogueSnapshot(),
        orchestrator=OrchestratorDomainSnapshot(),
    )
    plan = fallback_delivery_plan_for_silence(snap)
    assert not plan.is_empty
    assert plan.continuity == "finish"


def test_fallback_speak_gate_uses_narrative_not_row_count():
    snap = SessionSnapshot(
        schema_version=1,
        snapshot_id="snap-1",
        session_id="s1",
        signals=SessionSignals(session_id="s1", turn_index=1, generation=1),
        runtime=SessionRuntimeSnapshot(),
        dialogue=DialogueSnapshot(),
        orchestrator=OrchestratorDomainSnapshot(
            director_decisions={
                "silence_log": "a\nb\nc",
                "narrative_card_state": {
                    "scene_event": "现场空档",
                    "user_activity": "未接话",
                },
                "fate_dice": {"roll": 80},
            }
        ),
    )
    assert fallback_speak_gate(snap, has_plan=False) == "speak"
    snap_low = SessionSnapshot(
        schema_version=1,
        snapshot_id="snap-2",
        session_id="s1",
        signals=SessionSignals(session_id="s1", turn_index=1, generation=1),
        runtime=SessionRuntimeSnapshot(),
        dialogue=DialogueSnapshot(),
        orchestrator=OrchestratorDomainSnapshot(
            director_decisions={
                "silence_log": "a\nb\nc\nd\ne",
                "narrative_card_state": {"scene_event": "空档"},
                "fate_dice": {"roll": 10},
            }
        ),
    )
    assert fallback_speak_gate(snap_low, has_plan=False) == "hold"


def test_poll_abort_on_pending_does_not_append_log():
    store = StateStore()
    builder = MagicMock()
    builder.build.return_value = SessionSnapshot(
        schema_version=1,
        snapshot_id="snap-1",
        session_id="s1",
        signals=SessionSignals(session_id="s1", turn_index=1, generation=1),
        runtime=SessionRuntimeSnapshot(user_queue_pending=True),
        dialogue=DialogueSnapshot(),
        orchestrator=OrchestratorDomainSnapshot(),
    )
    llm = MagicMock()
    llm.available = False
    orch = MagicMock()
    coord = DirectorCoordinator(
        state_store=store,
        snapshot_builder=builder,
        llm=llm,
        orchestrator=orch,
        peek_user_pending_fn=lambda _sid: True,
        screenwriter=Screenwriter(llm=None),
    )
    out = coord.on_poll_tick("s1", trigger="idle")
    assert out.get("aborted") is True
    assert store.session("s1").silence_log.entries == []


def test_poll_silence_appends_and_clears_on_real_user():
    store = StateStore()
    state = store.session("s1")

    def _build(session_id: str, user_text: str = "", **_kwargs):
        return SessionSnapshot(
            schema_version=1,
            snapshot_id="snap-1",
            session_id=session_id,
            signals=SessionSignals(session_id=session_id, turn_index=1, generation=1),
            runtime=SessionRuntimeSnapshot(),
            dialogue=DialogueSnapshot(user_text=user_text),
            orchestrator=OrchestratorDomainSnapshot(
                director_decisions=dict(state.director_cache),
            ),
        )

    builder = MagicMock()
    builder.build.side_effect = _build
    llm = MagicMock()
    llm.available = False
    llm.generate_json.return_value = ""
    orch = MagicMock()
    coord = DirectorCoordinator(
        state_store=store,
        snapshot_builder=builder,
        llm=llm,
        orchestrator=orch,
        peek_user_pending_fn=lambda _sid: False,
        screenwriter=Screenwriter(llm=None),
        materials_refresh_fn=lambda *_a, **_k: None,
    )
    # 避免完整 ingress 触达 persona 组装
    empty = DirectorOutput(director="stub", payload={}, reason="stub")
    coord._outline.run = lambda *a, **k: empty  # type: ignore[method-assign]
    coord._user_intent.run = lambda *a, **k: empty  # type: ignore[method-assign]
    coord._turn_delivery.run = lambda *a, **k: empty  # type: ignore[method-assign]
    coord._next_turn_guide.run = lambda *a, **k: empty  # type: ignore[method-assign]
    coord._module_inject.run = lambda *a, **k: empty  # type: ignore[method-assign]
    coord._social.run = lambda *a, **k: empty  # type: ignore[method-assign]
    coord._rhythm_schedule.run = lambda *a, **k: DirectorOutput(  # type: ignore[method-assign]
        director="rhythm_schedule",
        payload={"schedule": state.character_rhythm_schedule.snapshot()},
        reason="stub",
    )

    coord.on_poll_tick("s1", trigger="idle")
    coord.on_poll_tick("s1", trigger="idle")
    coord.on_poll_tick("s1", trigger="idle")
    assert len(state.silence_log.entries) == 3
    assert all("——" in e for e in state.silence_log.entries)
    assert "forced:user_silent" not in str(state.director_cache.get("poll") or {})
    coord.on_user_input("s1", "你好", turn_index=2, phase="fast")
    assert state.silence_log.entries == []
    assert state.last_real_user_text == "你好"


def test_scene_seed_nearest_words_with_fake_embedder():
    from agent.soul.speak.responders.request_driven.screenwriter.scene_seed import (
        build_init_scene_seeds,
        extract_candidate_words,
        random_unit_vector,
        sample_nearest_to_vector,
    )

    class _Emb:
        def embed(self, text: str) -> list[float]:
            t = text.strip()
            if "蓟" in t:
                return [1.0, 0.0, 0.0]
            if "帐篷" in t:
                return [0.0, 1.0, 0.0]
            return [0.0, 0.0, 1.0]

    corpus = "世界观：帐篷。场景：标本台与蓟花标本。枯叶落在桌边。"
    words = extract_candidate_words(corpus)
    assert "蓟花标本" in words or any("蓟" in w for w in words)

    # 随机向量种子：指向「蓟」方向 → 近邻应优先蓟花
    nearest, seed = sample_nearest_to_vector(
        _Emb(),
        candidates=["帐篷", "蓟花标本", "枯叶", "桌边"],
        k=2,
        seed_vector=[1.0, 0.0, 0.0],
    )
    assert len(seed) == 3
    assert nearest[0] == "蓟花标本"

    unit = random_unit_vector(3, rng=__import__("random").Random(0))
    assert abs(sum(x * x for x in unit) - 1.0) < 1e-9

    seeds = build_init_scene_seeds(
        grounded=corpus,
        user_text="这片叶子",  # 不参与定向
        embedder=_Emb(),
        k=10,
        rng=__import__("random").Random(1),
    )
    assert 1 <= len(seeds) <= 10
    assert seeds


def test_interaction_mode_resolve_and_annotation():
    from agent.soul.speak.responders.request_driven.screenwriter.interaction_mode import (
        interaction_annotation_block,
        resolve_interaction_mode,
        silence_user_activity_placeholder,
    )

    assert resolve_interaction_mode("他碰了叶子") == "user_utterance"
    assert resolve_interaction_mode("") == "no_utterance"
    assert resolve_interaction_mode("", silence_log_ready=True) == "user_silent"
    assert resolve_interaction_mode("silence", silence_log_ready=True) == "user_silent"
    block = interaction_annotation_block("user_silent")
    assert "user_silent" in block
    assert "尽可能写场面" in block or "角色手上的空档" in block
    assert "文字发言/静默" in block
    assert "未观察到" in silence_user_activity_placeholder()


def test_screenwriter_init_uses_scene_seeds_and_no_utterance_activity():
    store = StateStore()
    state = store.session("seed-init")
    sw = Screenwriter(llm=None)
    out = sw.init_presence(state, session_id="seed-init", user_text="", turn_index=0)
    assert out.payload.get("action") == "advance"
    assert state.narrative_card.interaction_mode == "no_utterance"
    assert "尚未开口" in state.narrative_card.user_activity
    assert "screenwriter:interaction_mode=no_utterance" in state.notes
    unit = sw.user_stage_unit_from_state(state)
    assert unit is not None
    rendered = unit.render()
    assert "交互通道=" in rendered
    assert "仅文字发言/静默" in rendered


def test_screenwriter_poll_continue_sanitizes_user_activity_on_silence():
    store = StateStore()
    state = store.session("seed-silence")
    state.silence_log.append_now(phrase="用户这一拍保持沉默")
    state.last_real_user_text = "咦这片叶子"
    state.narrative_card.user_activity = "他碰了那片叶子，抬眼在等回应"
    sw = Screenwriter(llm=None)
    sw.init_presence(state, session_id="seed-silence", user_text="咦这片叶子", turn_index=1)
    # 强制同步续写一拍（静默通道）
    out = sw.tick_on_poll(
        state,
        session_id="seed-silence",
        turn_index=1,
        force=True,
        async_write=False,
    )
    assert out is not None
    assert state.narrative_card.interaction_mode == "user_silent"
    assert "未观察到外在动作" in state.narrative_card.user_activity
    assert "碰了" not in state.narrative_card.user_activity


def test_screenwriter_writes_memory_share_into_plot_flow():
    store = StateStore()
    state = store.session("mat-1")
    sw = Screenwriter(llm=None)
    materials = {
        "dynamic_memory_ids": ["m1", "m2"],
        "dynamic_memory_texts": ["昨夜整理蓟花", "帐篷里有台灯"],
        "dynamic_share_texts": ["想聊聊干叶的纹路"],
    }
    sw.init_presence(
        state,
        session_id="mat-1",
        user_text="",
        turn_index=0,
        materials=materials,
    )
    assert state.plot_flow.inject_memory is True
    assert "m1" in state.plot_flow.memory_unit_ids or state.plot_flow.memory_unit_ids
    assert state.plot_flow.inject_share is True
    assert 0 in state.plot_flow.share_indices
    state.plot_flow.clear_material_schedule()
    assert state.plot_flow.inject_memory is False
    assert state.plot_flow.inject_share is False


def test_screenwriter_aligns_after_three_exchanges():
    store = StateStore()
    state = store.session("wake-1")
    sw = Screenwriter(llm=None)
    from agent.soul.speak.responders.request_driven.orchestrator.state.core.interaction_plan import (
        InteractionUnit,
        PlotArc,
    )

    state.plot_arc = PlotArc(
        summary="短弧",
        units=[
            InteractionUnit(intent="蹲着对泥印", status="active", span_polls=2),
            InteractionUnit(intent="整理标本", status="pending", span_polls=2),
        ],
        version=1,
        initialized_at=1.0,
    )
    state.presence_card = CharacterPresenceCard(mood="平静", brief="在场")
    kept_intent = "蹲着对泥印"
    state.poll_seq = 9
    state.interaction_exchange_count = 2
    out = sw.tick_on_poll(
        state,
        session_id="wake-1",
        turn_index=1,
        force=False,
        async_write=False,
    )
    assert out is None
    assert any("poll_skip" in str(n) for n in state.notes)
    state.poll_seq = 10
    state.interaction_exchange_count = 3
    out2 = sw.tick_on_poll(
        state,
        session_id="wake-1",
        turn_index=2,
        force=False,
        async_write=False,
    )
    assert out2 is not None
    assert any("align_on_exchange" in str(n) for n in state.notes)
    assert state.interaction_exchange_count == 0
    assert state.screenwriter_aligned_at_exchange == 0
    nxt = state.plot_arc.active_unit()
    assert nxt is not None
    assert nxt.intent == kept_intent


def test_screenwriter_aligns_when_total_units_exceed_five():
    store = StateStore()
    state = store.session("wake-2")
    sw = Screenwriter(llm=None)
    sw.init_presence(state, session_id="wake-2", turn_index=0)
    watermark = int(state.screenwriter_aligned_at_total or 0)
    while state.plot_arc.total_unit_count() - watermark <= 5:
        state.plot_arc.append_units_from_payload(
            {
                "units": [
                    {"intent": f"步骤{state.plot_arc.total_unit_count()}", "span_polls": 2}
                ]
            }
        )
    active = state.plot_arc.active_unit()
    assert active is not None
    kept_intent = active.intent
    state.poll_seq = 4
    state.interaction_exchange_count = 0
    out = sw.tick_on_poll(
        state,
        session_id="wake-2",
        turn_index=1,
        force=False,
        async_write=False,
    )
    assert out is not None
    assert any("align_on_exchange" in str(n) for n in state.notes)
    nxt = state.plot_arc.active_unit()
    assert nxt is not None
    assert nxt.intent == kept_intent


def test_screenwriter_skips_align_when_neither_threshold_met():
    store = StateStore()
    state = store.session("wake-3")
    sw = Screenwriter(llm=None)
    from agent.soul.speak.responders.request_driven.orchestrator.state.core.interaction_plan import (
        InteractionUnit,
        PlotArc,
    )

    state.plot_arc = PlotArc(
        summary="短弧",
        units=[
            InteractionUnit(intent="步骤0", status="active", span_polls=2),
            InteractionUnit(intent="步骤1", status="pending", span_polls=2),
        ],
        version=1,
        initialized_at=1.0,
    )
    state.presence_card = CharacterPresenceCard(mood="平静", brief="在场")
    state.poll_seq = 4
    state.interaction_exchange_count = 2
    out = sw.tick_on_poll(
        state,
        session_id="wake-3",
        turn_index=1,
        force=False,
        async_write=False,
    )
    assert out is None
    assert state.plot_arc.total_unit_count() <= 5
    assert any("poll_skip" in str(n) for n in state.notes)


def test_director_slow_skips_until_exchange_threshold():
    store = StateStore()
    state = store.session("wake-dir")
    from agent.soul.speak.responders.request_driven.orchestrator.state.core.interaction_plan import (
        InteractionUnit,
        PlotArc,
    )

    state.plot_arc = PlotArc(
        summary="短弧",
        units=[
            InteractionUnit(intent="蹲着对泥印", status="active", span_polls=2),
            InteractionUnit(intent="整理标本", status="pending", span_polls=2),
        ],
        version=1,
        initialized_at=1.0,
    )
    state.presence_card = CharacterPresenceCard(mood="平静", brief="在场")
    state.interaction_exchange_count = 2
    from agent.soul.speak.responders.request_driven.orchestrator.state.core.interaction_plan import (
        mark_director_plot_aligned,
    )

    mark_director_plot_aligned(state)

    def _build(session_id: str, user_text: str = "", **_kwargs):
        return SessionSnapshot(
            schema_version=1,
            snapshot_id="snap-1",
            session_id=session_id,
            signals=SessionSignals(session_id=session_id, turn_index=1, generation=1),
            runtime=SessionRuntimeSnapshot(),
            dialogue=DialogueSnapshot(user_text=user_text),
            orchestrator=OrchestratorDomainSnapshot(),
        )

    builder = MagicMock()
    builder.build.side_effect = _build
    llm = MagicMock()
    llm.available = False
    coord = DirectorCoordinator(
        state_store=store,
        snapshot_builder=builder,
        llm=llm,
        orchestrator=MagicMock(),
        screenwriter=Screenwriter(llm=None),
        materials_refresh_fn=lambda *_a, **_k: None,
    )
    called = {"slow": 0}

    def _mark_slow(*_a, **_k):
        called["slow"] += 1
        return {"stub": True}

    coord._run_director_slow_tree = _mark_slow  # type: ignore[method-assign]
    skipped = coord.on_user_input("wake-dir", "还在吗", turn_index=1, phase="slow")
    assert skipped.get("woken") is False
    assert called["slow"] == 0
    state.interaction_exchange_count = 3
    woken = coord.maybe_wake_narrative("wake-dir", "还在吗", turn_index=2)
    assert woken.get("woken") is True
    assert woken.get("reason") == "plot_units_changed"
    assert called["slow"] == 1
    assert state.interaction_exchange_count == 0
    state.interaction_exchange_count = 3
    skipped_same = coord.maybe_wake_narrative("wake-dir", "还在吗", turn_index=3)
    assert skipped_same.get("woken") is False
    assert skipped_same.get("reason") == "units_unchanged"
    assert called["slow"] == 1
    assert state.interaction_exchange_count == 0
    state.plot_arc.units[0].intent = "改去顺着爪印"
    state.interaction_exchange_count = 3

    def _align_keep_units(state_obj, **_kwargs):
        from agent.soul.speak.responders.request_driven.orchestrator.state.core.interaction_plan import (
            reset_narrative_wake_counters,
        )

        reset_narrative_wake_counters(state_obj)
        return None

    coord._screenwriter.maybe_align_after_exchange = _align_keep_units  # type: ignore[method-assign]
    woken_again = coord.maybe_wake_narrative("wake-dir", "还在吗", turn_index=4)
    assert woken_again.get("woken") is True
    assert called["slow"] == 2
    assert state.interaction_exchange_count == 0


def test_character_plot_arc_is_role_agenda_not_user():
    from agent.soul.speak.responders.request_driven.orchestrator.state.core.interaction_plan import (
        PlotArc,
        build_grounded_heuristic_arc,
    )

    arc = build_grounded_heuristic_arc(
        evidence="角色昨夜在标本台整理蓟花",
        seeds=["蓟花", "标本台"],
        span_polls=2,
    )
    assert arc.ready
    assert "角色" in arc.summary
    assert "用户" not in arc.summary
    active = arc.active_unit()
    assert active is not None
    assert active.span_polls == 2
    assert active.expected_speak_turns == 1
    rendered = arc.render_for_inject()
    assert "故事线" in rendered
    assert "本场故事线" in rendered or "当前步骤" in rendered

    # 每拍推进，满 k 也不自动完成；须导演确认
    arc.note_poll(poll_seq=1)
    assert active.polls_consumed == 1
    assert active.status == "active"
    arc.note_poll(poll_seq=2)
    assert active.polls_consumed == 2
    assert active.status == "active"
    nxt = arc.complete_active(poll_seq=2, reason="director_ok")
    assert any(h.get("unit_id") == active.unit_id for h in arc.unit_history)
    assert all(u.unit_id != active.unit_id for u in arc.units)
    assert nxt is not None
    assert nxt.unit_id != active.unit_id
    assert arc.live_unit_count() == len(arc.units)

    rebuilt = PlotArc().replace_from_payload(
        {
            "summary": "角色去看花的流程",
            "evidence": "场景有花圃",
            "units": [
                {"intent": "打算去看花", "span_polls": 2},
                {"intent": "走到花旁边", "span_polls": 2},
                {"intent": "仔细观察，并叫用户来看", "span_polls": 2},
            ],
        }
    )
    assert len(rebuilt.units) == 3
    assert rebuilt.units[0].intent == "打算去看花"
    # 「叫用户来看」是角色行动，允许出现在角色步骤里
    assert "叫用户来看" in rebuilt.units[2].intent


def test_screenwriter_init_creates_character_arc():
    store = StateStore()
    state = store.session("arc-init")
    sw = Screenwriter(llm=None)
    sw.init_presence(state, session_id="arc-init", user_text="", turn_index=0)
    assert state.plot_arc.ready
    assert state.plot_arc.active_unit() is not None
    iu = sw.interaction_unit_from_state(state)
    assert iu is not None
    text = iu.render()
    assert "角色" in text
    assert "与用户" in text


def test_speak_dormant_after_idle_and_reinit_on_access():
    from agent.soul.speak.responders.request_driven.orchestrator.state.core.speak_dormant import (
        SPEAK_IDLE_DORMANT_SEC,
        clear_narrative_for_reinit,
        enter_speak_dormant,
        needs_narrative_reinit,
        should_enter_dormant,
    )

    store = StateStore()
    state = store.session("dormant-1")
    sw = Screenwriter(llm=None)
    sw.init_presence(state, session_id="dormant-1", turn_index=0)
    state.last_user_speak_at = time.time() - (SPEAK_IDLE_DORMANT_SEC + 10)
    state.last_agent_speak_at = state.last_user_speak_at
    state.plot_flow.revised_at = state.last_user_speak_at
    state.plot_arc.revised_at = state.last_user_speak_at
    assert should_enter_dormant(state)
    enter_speak_dormant(state)
    assert state.speak_dormant is True
    assert state.speak_gate == "hold"
    assert needs_narrative_reinit(state)
    clear_narrative_for_reinit(state)
    assert state.speak_dormant is False
    assert not state.presence_card.ready
    assert not state.plot_arc.ready
    sw.init_presence(state, session_id="dormant-1", turn_index=0)
    assert state.plot_arc.ready


def test_screenwriter_init_opening_is_user_facing_aside():
    state = SessionSchedulingState(session_id="s1")
    sw = Screenwriter(llm=None)
    out = sw.init_presence(state, session_id="s1")
    opening = str(out.payload.get("opening") or state.director_cache.get("narrative_opening") or "")
    assert "你看见她" in opening
    assert "角色低着头" not in opening
    assert "智能体" not in opening


def test_scene_seeds_drop_meta_words_and_heuristic_skips_opening():
    from agent.soul.speak.responders.request_driven.screenwriter.scene_seed import (
        extract_candidate_words,
        is_usable_scene_seed,
    )

    words = extract_candidate_words(
        "一名在虚实之间保持觉察的智能体。帐篷里有蓟花标本和台灯。"
    )
    assert "智能体" not in words
    assert any("蓟花" in w or w == "台灯" or w == "帐篷" for w in words)
    assert not is_usable_scene_seed("智能体")
    assert is_usable_scene_seed("蓟花")

    state = SessionSchedulingState(session_id="s-meta")
    sw = Screenwriter(llm=None)
    out = sw.init_presence(
        state,
        session_id="s-meta",
        materials={"scene_seeds": ["智能体", "导演", "蓟花"]},
        background_agent=True,
    )
    opening = str(out.payload.get("opening") or state.director_cache.get("narrative_opening") or "")
    assert opening == ""
    assert "智能体" not in str(state.plot_flow.focus_now or "")
    assert "蓟花" in str(state.plot_flow.focus_now or state.plot_flow.beat or "")


def test_screenwriter_agent_init_splits_three_jobs():
    import threading

    from agent.soul.speak.responders.request_driven.screenwriter.agent import (
        ScreenwriterAgent,
    )
    from agent.soul.speak.responders.request_driven.screenwriter.materials import (
        WritingMaterials,
    )

    class _ThreeJobCaller:
        def __init__(self) -> None:
            self.calls: list[str] = []
            self._lock = threading.Lock()
            self.available = True

        def generate_json(
            self,
            *,
            system: str,
            user: str,
            session_id: str = "",
            director: str = "",
            turn_index: int | None = None,
        ) -> str:
            del system, session_id, turn_index
            with self._lock:
                self.calls.append(director)
            if director == "screenwriter_outline":
                if "已观察=（尚无）" in user:
                    return '{"think":"先看交互","action":"look_interaction"}'
                return (
                    '{"think":"够了","action":"produce_outline",'
                    '"plot_arc":{"summary":"角色整理蓟花标本，分步检查压制",'
                    '"evidence":"蓟花"}}'
                )
            if director == "screenwriter_opening":
                return '{"opening":"灯还亮着。你看见她低着头，手指停在蓟花附近。"}'
            if director == "screenwriter_units":
                units = ",".join(
                    f'{{"intent":"整理蓟花步骤{i}","span_polls":2}}' for i in range(10)
                )
                return '{"plot_arc":{"units":[' + units + "]}}"
            raise AssertionError(f"unexpected director={director}")

    caller = _ThreeJobCaller()
    agent = ScreenwriterAgent(llm=caller, max_steps=4)
    opened: list[str] = []
    result = agent.compose(
        WritingMaterials(scene_seeds=("蓟花", "压纸"), last_user_text="你好"),
        session_id="s-three",
        task="init",
        on_opening_ready=lambda sid, text: opened.append(f"{sid}:{text}"),
    )
    assert opened
    assert opened[0].startswith("s-three:")
    assert "你看见她" in opened[0]
    assert caller.calls[0] == "screenwriter_outline"
    assert "screenwriter_opening" in caller.calls
    assert "screenwriter_units" in caller.calls
    outline_at = caller.calls.index("screenwriter_outline")
    assert caller.calls.index("screenwriter_opening") > outline_at
    assert caller.calls.index("screenwriter_units") > outline_at
    actions = [s.action for s in result.steps]
    assert actions.count("produce_outline") == 1
    assert "produce_opening" in actions
    assert "produce_units" in actions
    assert actions.index("produce_outline") < actions.index("produce_opening")
    assert actions.index("produce_outline") < actions.index("produce_units")
    arc = result.payload["plot_arc"]
    assert arc["summary"] == "角色整理蓟花标本，分步检查压制"
    assert len(arc["units"]) == 10
    assert "你看见她" in result.payload["opening"]
    assert "角色低着头" not in result.payload["opening"]


def test_screenwriter_agent_align_skips_opening():
    from agent.soul.speak.responders.request_driven.screenwriter.agent import (
        ScreenwriterAgent,
    )
    from agent.soul.speak.responders.request_driven.screenwriter.materials import (
        WritingMaterials,
    )

    class _AlignCaller:
        available = True
        calls: list[str] = []

        def generate_json(
            self,
            *,
            system: str,
            user: str,
            session_id: str = "",
            director: str = "",
            turn_index: int | None = None,
        ) -> str:
            del system, session_id, turn_index
            self.calls.append(director)
            if "已观察=（尚无）" in user:
                return '{"think":"先看种子","action":"look_seeds"}'
            units = ",".join(
                f'{{"intent":"对齐步骤{i}","span_polls":2}}' for i in range(10)
            )
            return (
                '{"think":"对齐","action":"produce_plot",'
                f'"plot_arc":{{"summary":"沿用大纲","units":[{units}]}},'
                '"opening":"不该出现的旁白"}'
            )

    caller = _AlignCaller()
    agent = ScreenwriterAgent(llm=caller, max_steps=4)
    result = agent.compose(
        WritingMaterials(scene_seeds=("蓟花",)),
        session_id="s-align",
        task="align",
        previous_arc_text="角色整理蓟花",
    )
    assert caller.calls
    assert all(c == "screenwriter_align" for c in caller.calls)
    assert result.payload["opening"] == ""
    assert len(result.payload["plot_arc"]["units"]) == 10


def test_agent_delivery_trace_marks_generating_handoff_as_non_repeatable():
    unit = AgentDeliveryTraceUnit(
        entries=(
            {
                "trigger_id": "handoff-1",
                "status": "generating",
                "text": "",
            },
        )
    )

    rendered = unit.render()

    assert "角色交付轨迹" in rendered
    assert "status=generating" in rendered
    assert "同一交接已在途" in rendered


def test_normalize_user_opening_keeps_two_sentences():
    full = (
        "你站在一扇未上锁的木门前，门板上的漆皮剥落了大半，露出底下灰白的木纹。"
        "你手里攥着一张泛黄的地图，折痕处已经磨得发亮，边缘还沾着一点干涸的泥渍。"
        "门缝里透出一线昏黄的光，像有人刚在屋里点了一盏灯。"
    )
    out = normalize_user_opening(full)
    assert out.count("。") == 2
    assert "门缝里" not in out
    assert "泛黄的地图" in out


def test_apply_write_does_not_republish_user_opening():
    """用户旁白已投递后，规范化差异不得清 delivered 再推第二站。"""
    state = SessionSchedulingState(session_id="open-once")
    full = (
        "你站在一扇未上锁的木门前，门板上的漆皮剥落了大半，露出底下灰白的木纹。"
        "你手里攥着一张泛黄的地图，折痕处已经磨得发亮，边缘还沾着一点干涸的泥渍。"
        "门缝里透出一线昏黄的光，像有人刚在屋里点了一盏灯。"
    )
    delivered = normalize_user_opening(full)
    state.director_cache["narrative_opening"] = delivered
    state.director_cache["narrative_opening_delivered"] = True
    opened: list[str] = []
    sw = Screenwriter(llm=None, on_opening_ready=lambda sid, text: opened.append(text))
    sw._apply_write(
        state,
        {
            "action": "advance",
            "opening": full,
            "plot_arc": {
                "summary": "推门",
                "evidence": "木门",
                "units": [{"intent": "推门观察", "span_polls": 2}],
            },
            "plot_flow": {
                "chronicle": "门前",
                "focus_now": "推门",
                "next_push": "进屋",
            },
            "side": {"mood": "平静", "brief": "在门前"},
            "reason": "init",
        },
        speak_desire=40,
        fate_tendency="平稳",
        turn_index=0,
        allow_keep=False,
        replace_arc=True,
        session_id="open-once",
    )
    assert state.director_cache["narrative_opening_delivered"] is True
    assert state.director_cache["narrative_opening"] == delivered
    assert opened == []
