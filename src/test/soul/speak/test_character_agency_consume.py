from __future__ import annotations

from agent.soul.speak.responders.request_driven.character.consume import (
    consume_injected_materials,
    resolve_injected_memory_ids,
    resolve_injected_share,
)
from agent.soul.speak.responders.request_driven.character.context import (
    context_cards_from_narrative,
)
from agent.soul.speak.responders.request_driven.character.contracts import (
    NarrativeSnapshot,
)
from agent.soul.speak.responders.request_driven.interpreter import interpret_role_packet
from agent.soul.speak.responders.request_driven.composer.projectors.dynamic_layer import (
    DynamicLayerMaterials,
    DynamicLayerSchedule,
)
from agent.soul.speak.responders.request_driven.protocol.blocks import parse_role_blocks
from agent.soul.speak.session.queue.share import SessionShareQueue


def test_parse_note_director_and_screenwriter_blocks():
    raw = (
        "[think]不想照导演说的演[/think]\n"
        "<speak action>silence 2</speak action>\n"
        "<note director>这步太急，角色不会主动开口</note director>\n"
        "<note screenwriter>交互单元「仔细观察」与角色当前心情不符</note screenwriter>\n"
    )
    blocks = parse_role_blocks(raw)
    kinds = [b.kind for b in blocks]
    assert "note_director" in kinds
    assert "note_screenwriter" in kinds
    assert "speak_action" in kinds
    packet = interpret_role_packet(raw)
    assert packet.notes_to_director == ("这步太急，角色不会主动开口",)
    assert "交互单元" in packet.notes_to_screenwriter[0]
    assert not packet.timeline.answer_text
    assert any(op.kind == "silence" for op in packet.timeline.ops)


def test_memory_and_share_appear_as_context_cards():
    snap = NarrativeSnapshot(plot_outline_text="走近标本")
    cards = context_cards_from_narrative(
        snap,
        memory_texts=("记得上次蓟花",),
        share_texts=("想分享帐篷里的光",),
    )
    titles = [t for t, _ in cards]
    assert "记忆卡片" in titles
    assert "分享卡片" in titles


def test_character_gets_full_interaction_record():
    from agent.soul.speak.responders.request_driven.character.context import (
        build_narrative_snapshot,
        context_cards_from_narrative,
    )
    from agent.soul.speak.responders.request_driven.character.interaction import (
        note_character_exchange,
        note_pending_user,
    )
    from agent.soul.speak.responders.request_driven.layers import assemble_role_layers
    from agent.soul.speak.responders.request_driven.orchestrator.state.runtime.store import (
        SessionSchedulingState,
    )
    from agent.soul.speak.responders.request_driven.composer.projectors.dynamic_layer import (
        DynamicLayerMaterials,
        DynamicLayerSchedule,
    )
    from agent.soul.speak.responders.request_driven.composer.projectors.role_view import (
        RoleContextView,
    )

    state = SessionSchedulingState(session_id="s-ledger")
    note_character_exchange(
        state,
        user_text="",
        agent_text="咦——这绳头，怎么缠到这儿来了。",
    )
    note_pending_user(state, user_text="在干啥呢，借我瞅瞅")
    snap = build_narrative_snapshot(
        state,
        origin="user",
        user_text="在干啥呢，借我瞅瞅",
    )
    assert "在干啥呢，借我瞅瞅" in snap.interaction_record_text
    assert "咦——这绳头" in snap.interaction_record_text
    assert "自然延续" in snap.interaction_record_text
    cards = context_cards_from_narrative(
        snap,
        user_text="在干啥呢，借我瞅瞅",
        dialogue_frame="对话轨迹（尚未压缩）如下：\n用户：嗨\n你：嗯",
    )
    titles = [t for t, _ in cards]
    assert titles[0] == "即时往来"
    assert "交互记录" in titles
    assert "对话轨迹" not in titles
    director_snap = build_narrative_snapshot(state, origin="director")
    assert "在干啥呢，借我瞅瞅" in director_snap.interaction_record_text
    layers = assemble_role_layers(
        RoleContextView(session_id="s-ledger", working_turns=(("嗨", "嗯"),)),
        DynamicLayerMaterials(session_id="s-ledger"),
        DynamicLayerSchedule(reason="t"),
        user_text="",
        interaction_record_text=director_snap.interaction_record_text,
    )
    extra = layers.render_system_extra()
    assert "在干啥呢，借我瞅瞅" in extra
    assert "咦——这绳头" in extra
    assert "对话轨迹" not in extra
    assert "顺着上一句往下说" in extra


def test_injected_materials_are_fully_consumed():
    queue = SessionShareQueue()
    from agent.soul.presence.state.dynamic.expectation.queue import ShareIntent
    from agent.soul.presence.share_desire import ShareDesire

    queue.enqueue_batch(
        "s1",
        [ShareIntent(topic="想分享帐篷里的光", share_desire=ShareDesire.mild)],
    )
    consumed_mem: list[str] = []
    cleared: list[str] = []

    notes = consume_injected_materials(
        "s1",
        memory_unit_ids=("mem-1", "mem-2"),
        share_texts=("想分享帐篷里的光",),
        share_indices=(0,),
        mark_recall_unit_consumed=lambda sid, uid: consumed_mem.append(f"{sid}:{uid}"),
        pop_session_share_at=lambda sid, index: queue.consume_at(
            sid,
            index,
            turn_index=3,
            trigger_id="director-3",
        ),
        pop_presence_share_at=None,
        peek_session_share=queue.peek_session,
        pop_deferred_share_matching=lambda sid, topic: queue.consume_by_topic(
            sid,
            topic,
            turn_index=3,
            trigger_id="director-3",
        ) is not None,
        clear_director_inject_flags=lambda sid: cleared.append(sid),
    )
    assert consumed_mem == ["s1:mem-1", "s1:mem-2"]
    assert queue.peek_session("s1") == []
    assert "s1" in cleared
    assert any("character_memory_consumed" in n for n in notes)
    assert any("character_share_consumed" in n for n in notes)
    assert queue.consumption_history("s1") == [
        {
            "topic": "想分享帐篷里的光",
            "source": "",
            "turn_index": 3,
            "trigger_id": "director-3",
            "consumed_at": queue.consumption_history("s1")[0]["consumed_at"],
        }
    ]


def test_schedule_selected_ids_and_share_indices():
    materials = DynamicLayerMaterials(
        session_id="s1",
        memory_ids=("a", "b"),
        memory_texts=("记忆A", "记忆B"),
        share_texts=("分享1", "分享2"),
    )
    schedule = DynamicLayerSchedule(
        inject_memory=True,
        memory_unit_ids=("b",),
        inject_share=True,
        share_indices=(1,),
        reason="test",
    )
    assert resolve_injected_memory_ids(schedule, materials) == ("b",)
    texts, indices = resolve_injected_share(schedule, materials)
    assert texts == ("分享2",)
    assert indices == (1,)
