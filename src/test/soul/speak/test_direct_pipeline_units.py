from __future__ import annotations

from types import SimpleNamespace

import pytest

from agent.soul.speak.responders.request_driven.character.frame import (
    DebtSnapshot,
    DirectTuning,
    current_debt,
    find_duplicate,
    frame_meta,
    note_debt_agent_reply,
    note_debt_user_message,
    recent_answers,
    remember_answer,
)
from agent.soul.speak.responders.request_driven.character.runtime import (
    CharacterRuntime,
    DirectRetryPolicy,
)
from agent.soul.speak.responders.request_driven.composer.projectors.dynamic_layer import (
    DynamicLayerMaterials,
    DynamicLayerSchedule,
)
from agent.soul.speak.responders.request_driven.composer.projectors.role_view import (
    RoleContextView,
)
from agent.soul.speak.responders.request_driven.layers import assemble_role_layers
from agent.soul.speak.responders.request_driven.orchestrator.bundle import SpeakPromptBundle
from agent.soul.speak.responders.request_driven.policy_lint import lint_policy_text
from agent.soul.speak.responders.request_driven.responder import SpeakRole


def _state():
    return SimpleNamespace(director_cache={})


# ── 注意力债 ─────────────────────────────────────────────────────────────────


def test_debt_counts_unanswered_and_flags_soft_hard():
    st = _state()
    d1 = note_debt_user_message(st)
    assert d1.unanswered == 1 and not d1.soft_exceeded
    d2 = note_debt_user_message(st)
    assert d2.unanswered == 2 and d2.soft_exceeded and not d2.hard_exceeded
    d3 = note_debt_user_message(st)
    assert d3.unanswered == 3 and d3.hard_exceeded
    lines = "\n".join(d3.material_lines())
    assert "3 条" in lines and "失礼" in lines


def test_debt_cleared_by_agent_reply():
    st = _state()
    note_debt_user_message(st)
    note_debt_user_message(st)
    assert current_debt(st).unanswered == 2
    note_debt_agent_reply(st)
    snap = current_debt(st)
    assert snap.unanswered == 0 and not snap.hard_exceeded and not snap.soft_exceeded
    assert snap.material_lines() == []


def test_debt_material_is_factual_not_instructional():
    st = _state()
    for _ in range(3):
        note_debt_user_message(st)
    snap = current_debt(st)
    lines = snap.material_lines()
    assert lines
    joined = "\n".join(lines)
    # 材料化：不得出现指令动词或 <speak> 协议词
    assert "<speak>" not in joined
    assert "必须" not in joined and "请勿" not in joined
    assert "回复格式" not in joined


# ── 跨轮去重 ─────────────────────────────────────────────────────────────────


def test_dedup_detects_near_repeat_and_ignores_distinct():
    st = _state()
    original = (
        "我顺着地图上那个铅笔画的小圆圈，找到这间没人住的旧屋子。"
        "门没锁，像是专门给我留的。屋子里的东西摆得太整齐了。"
    )
    remember_answer(st, original)
    got = recent_answers(st)
    assert got and got[-1] == original[:800]
    near = original.replace("旧屋子", "空屋子")
    assert find_duplicate(near, got)
    other = "今天天气不错，适合去河边走走看看渔船回来没有。"
    assert find_duplicate(other, got) == ""


def test_recent_answers_ring_buffer_keeps_last_six():
    st = _state()
    for i in range(8):
        remember_answer(st, f"answer-{i}")
    got = recent_answers(st)
    assert len(got) == 6 and got[-1] == "answer-7"


# ── 剧情帧 ───────────────────────────────────────────────────────────────────


def test_frame_renews_on_expiry_only():
    st = _state()
    t = DirectTuning()
    # 首次建帧：跨越边界
    first = frame_meta(st, t, now=1000.0)
    assert first["frame_expired_this_turn"] is True
    assert first["frame_started_at"] == pytest.approx(1000.0)
    # 帧内（age < 120s）：不重开
    second = frame_meta(st, t, now=1050.0)
    assert second["frame_expired_this_turn"] is False
    assert second["frame_age"] == pytest.approx(50.0, abs=0.01)
    # 超过 120s 上限：本轮跨越边界，惰性重开
    third = frame_meta(st, t, now=1125.0)
    assert third["frame_expired_this_turn"] is True
    assert third["frame_started_at"] == pytest.approx(1125.0)
    # 新帧内继续沿用
    fourth = frame_meta(st, t, now=1180.0)
    assert fourth["frame_expired_this_turn"] is False
    assert fourth["frame_started_at"] == pytest.approx(1125.0)


# ── 动态层材料化检查 ─────────────────────────────────────────────────────────


def test_dynamic_layer_renders_no_directives_even_when_busy():
    view = RoleContextView(session_id="s")
    layers = assemble_role_layers(
        view,
        DynamicLayerMaterials(session_id="s"),
        DynamicLayerSchedule(reason="poll_open"),
        user_text="在吗",
        plot_flow_text="他正在收拾摊位，账本摊到一半。",
        director_detail="把手头这单账记完",
        director_inner="有点烦躁",
        interaction_channel="当前通道：远程文字往来，对方不在身边。",
    )
    extra = layers.render_system_extra()
    assert "手头动作：把手头这单账记完" in extra
    assert "「你」指角色自己" in extra          # 人称消歧标注保留
    assert "<speak>" not in extra
    assert "回复格式" not in extra
    assert "只写" not in extra
    assert "以本层列出的材料为准" not in extra
    assert lint_policy_text(extra) == []


def test_policy_lint_flags_known_patterns():
    assert "speak-tag" in lint_policy_text("输出：<speak>hi</speak>")
    assert "compose-tag" in lint_policy_text("[state]finish[/state]")
    assert "format-word" in lint_policy_text("回复格式如下")
    assert lint_policy_text("他正在记账，灯还亮着。") == []


# ── runtime 重试策略 ──────────────────────────────────────────────────────────


def _mk_runtime(outputs: list[str]) -> tuple[CharacterRuntime, list[str]]:
    seen_systems: list[str] = []

    def gen(system: str, user: str) -> str:
        seen_systems.append(system)
        return outputs.pop(0)

    role = SpeakRole(generate_fn=gen)
    rt = CharacterRuntime(speak_role=role)
    return rt, seen_systems


def _mk_request():
    from agent.soul.speak.responders.request_driven.character.contracts import (
        CharacterReplyRequest,
        NarrativeSnapshot,
        new_trigger_id,
    )

    return CharacterReplyRequest(
        origin="user",
        session_id="s1",
        turn_index=1,
        trigger_id=new_trigger_id(),
        narrative=NarrativeSnapshot(),
        user_text="在吗",
    )


@pytest.mark.parametrize("first_output", [""])
def test_force_ack_retry_regenerates_once(first_output):
    rt, systems = _mk_runtime([first_output, "<speak>嗯，忙着呢，回头说。</speak>"])
    bundle = SpeakPromptBundle(session_id="s1")
    view = RoleContextView(session_id="s1")
    result = rt.run(
        _mk_request(),
        bundle=bundle,
        view=view,
        materials=DynamicLayerMaterials(session_id="s1"),
        schedule=DynamicLayerSchedule(reason="direct"),
        notes=[],
        retry_policy=DirectRetryPolicy(force_ack_note="对方已连发 3 条消息。"),
    )
    assert result.answer_text == "嗯，忙着呢，回头说。"
    assert any(n.startswith("direct_forced_ack_retry") for n in result.notes)
    assert len(systems) == 2
    assert "处境注记" in systems[1]


def test_silence_without_policy_stays_silent():
    rt, systems = _mk_runtime([""])
    bundle = SpeakPromptBundle(session_id="s1")
    view = RoleContextView(session_id="s1")
    result = rt.run(
        _mk_request(),
        bundle=bundle,
        view=view,
        materials=DynamicLayerMaterials(session_id="s1"),
        schedule=DynamicLayerSchedule(reason="direct"),
        notes=[],
    )
    assert result.answer_text == ""
    assert len(systems) == 1


def test_dedup_retry_swaps_repeat_for_fresh_angle():
    repeated = "这句话和上一次说过的几乎一样，内容足够长以触发判定阈值线。"
    again = repeated[:-5] + "边界线上。"  # 高相似变体（ratio ≈ 0.90）
    rt, systems = _mk_runtime([repeated, "<speak>换了个说法的新回应。</speak>"])
    bundle = SpeakPromptBundle(session_id="s1")
    view = RoleContextView(session_id="s1")
    result = rt.run(
        _mk_request(),
        bundle=bundle,
        view=view,
        materials=DynamicLayerMaterials(session_id="s1"),
        schedule=DynamicLayerSchedule(reason="direct"),
        notes=[],
        retry_policy=DirectRetryPolicy(recent_answers=(again,), dedup_threshold=0.80),
    )
    assert result.answer_text == "换了个说法的新回应。"
    assert any(n.startswith("direct_dedup_retry") for n in result.notes)
