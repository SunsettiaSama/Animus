from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import MagicMock

from agent.soul.speak.compose.bundle import SpeakPromptBundle
from agent.soul.speak.compose.composer import SpeakPromptComposer
from agent.soul.speak.compose.context.chunk_types import DialogueContextChunk
from agent.soul.speak.compose.context.distiller import SpeakContextDistiller
from agent.soul.speak.compose.context.render import render_session_working_memory
from agent.soul.speak.compose.injected.context import SpeakInjectedContext
from agent.soul.speak.compose.memory.render import render_similar_memories_block
from agent.soul.speak.compose.system import SpeakSystemPrompt
from agent.soul.speak.io.inbound.compose import SpeakStatusInjected
from agent.soul.presence.state.presence_state import PresenceState
from agent.soul.presence.transition.static.lifecycle import apply_dialogue_session_boundary
from agent.soul.speak.io.inbound.compose.render import render_presence
from agent.soul.life.anchor.presence_bundle import merge_presence_bundles, PresenceExperienceBundle


@dataclass
class _Snap:
    state: object = None


def _presence_snap():
    snap = MagicMock()
    snap.state.affect.render.return_value = ""
    snap.state.somatic.render.return_value = ""
    snap.state.cognition.thinking = ""
    snap.state.perception.render.return_value = ""
    snap.state.expectation.to_dict.return_value = {"share_queue": {"items": []}}
    snap.interaction.impulse_reason = ""
    from agent.soul.presence.share_desire import ShareDesire
    snap.interaction.share_desire = ShareDesire.none
    return snap


class _Presence:
    def snapshot(self, session_id: str) -> MagicMock:
        return _presence_snap()


class _Persona:
    def get_persona_snapshot(self, *, session_id: str = "tao") -> dict:
        return {}


def test_render_session_working_memory_includes_generation_and_buffer():
    block = render_session_working_memory(
        generation=3,
        distilled=["用户问候，我回应还在。"],
        recent_turns=[("还在么", "在的")],
    )
    assert "【当前会话·工作记忆】" in block
    assert "generation=3" in block
    assert "用户问候" in block
    assert "还在么" in block
    assert "在的" in block


def test_working_memory_block_at_bottom_before_output_format():
    distiller = SpeakContextDistiller(chunk_size=4)
    state = distiller._session("s1")
    with state.lock:
        state.buffer.append(
            DialogueContextChunk(user_text="还在么", agent_text="在的")
        )

    bundle = SpeakPromptBundle(
        session_id="s1",
        injected=SpeakInjectedContext(
            status=SpeakStatusInjected(
                presence="【当下态·状态】\n情感：平静",
                similar_memories=render_similar_memories_block(["营地边的秘密"]),
            ),
        ),
        system=SpeakSystemPrompt(
            role="你是莉奈娅",
            output_format="[think]…[/think]",
        ),
        session_working_memory=distiller.working_memory_block("s1", generation=2),
    )
    assembled = bundle.build_system()
    wm_pos = assembled.index("【当前会话·工作记忆】")
    fmt_pos = assembled.index("[think]")
    ltm_pos = assembled.index("【涌现记忆·长期】")
    assert ltm_pos < wm_pos < fmt_pos


def test_finalize_puts_working_memory_on_bundle():
    distiller = SpeakContextDistiller(chunk_size=4)
    state = distiller._session("s1")
    with state.lock:
        state.distilled.append("此前聊过探险。")

    composer = SpeakPromptComposer(
        _Persona(),
        _Presence(),
        context_distiller=distiller,
    )
    frame = composer.prepare("s1", generation=5)
    bundle = composer.finalize(frame, "你好", session_id="s1")
    assert "【当前会话·工作记忆】" in bundle.session_working_memory
    assert "generation=5" in bundle.session_working_memory
    assert "此前聊过探险" in bundle.session_working_memory
    assert bundle.injected.status.dialogue_compressed == ""


def test_ltm_block_label():
    block = render_similar_memories_block(["伤雉与营地"])
    assert block.startswith("【涌现记忆·长期】")
    assert "长期记忆" in block
    assert "不是当前对话原文" in block


def test_presence_render_excludes_working_memory():
    state = PresenceState()
    state.cognition.working_memory = "用户：旧对话\n我：旧回复"
    state.cognition.thinking = "有点在意对方"
    state.perception.narrative = "用户问了天气"
    rendered = render_presence(state)
    assert "工作记忆" not in rendered
    assert "有点在意对方" in rendered


def test_apply_dialogue_session_boundary_clears_verbatim_perception():
    state = PresenceState()
    state.perception.narrative = "用户偷偷分享了和不好的事情有关的秘密"
    state.cognition.working_memory = "用户：还在么"
    notes = apply_dialogue_session_boundary(state)
    assert state.perception.narrative == ""
    assert state.cognition.working_memory == ""
    assert "boundary" in notes[0]
    assert "秘密" in state.cognition.thinking


def test_merge_presence_bundles_skips_interaction_perception():
    bundles = [
        PresenceExperienceBundle(
            session_id="tao",
            source="interaction",
            perception="用户偷偷分享了秘密",
            narration="完成了一轮对话",
            salience=0.5,
        ),
        PresenceExperienceBundle(
            session_id="tao",
            source="narrative",
            perception="窗外有雨",
            narration="注意到雨声",
            salience=0.3,
        ),
    ]
    merged = merge_presence_bundles(bundles)
    assert merged is not None
    assert "秘密" not in merged.perception
    assert "窗外有雨" in merged.perception
    assert "完成了一轮对话" in merged.narration
