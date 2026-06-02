from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import MagicMock

from agent.soul.speak.orchestrator.guidance.context.chunk_types import DialogueContextChunk
from agent.soul.speak.orchestrator.guidance.context.distiller import SpeakContextDistiller
from agent.soul.speak.orchestrator.guidance.context.render import render_session_working_memory
from agent.soul.speak.orchestrator.guidance import SpeakGuidanceLayer
from agent.soul.speak.orchestrator.persona import SpeakPersonaLayer
from agent.soul.speak.orchestrator.guidance.memory.render import render_similar_memories_block
from agent.soul.speak.orchestrator import SpeakOrchestrator, SpeakPromptBundle
from agent.soul.speak.orchestrator.scene import SpeakSceneLayer
from agent.soul.speak.orchestrator.system import SpeakSystemLayer
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
        from test.soul.persona.distill_fixtures import persona_snapshot_with_distill

        return persona_snapshot_with_distill()


def test_render_session_working_memory_includes_generation_and_buffer():
    block = render_session_working_memory(
        generation=3,
        distilled=["???????????"],
        recent_turns=[("???", "??")],
    )
    assert "???????????" in block
    assert "generation=3" in block
    assert "????" in block
    assert "???" in block
    assert "??" in block


def test_working_memory_block_at_bottom_before_output_format():
    distiller = SpeakContextDistiller(chunk_size=4)
    state = distiller._session("s1")
    with state.lock:
        state.buffer.append(
            DialogueContextChunk(user_text="???", agent_text="??")
        )

    bundle = SpeakPromptBundle(
        session_id="s1",
        system=SpeakSystemLayer(
            role="role block",
            output_format="[think]x[/think]",
        ),
        persona=SpeakPersonaLayer(
            self_narrative="persona narrative",
        ),
        scene=SpeakSceneLayer(),
        guidance=SpeakGuidanceLayer(
            control_arc="??????\n?????????????",
            recall_preview="- memory line",
            working_memory=distiller.working_memory_block("s1", generation=2),
        ),
    )
    assembled = bundle.build_system()
    wm_pos = assembled.index("recent dialogue")
    fmt_pos = assembled.index("[think]")
    guidance_pos = assembled.index("???")
    assert guidance_pos < wm_pos < fmt_pos
    assert "????" not in assembled


def test_finalize_puts_working_memory_on_bundle():
    distiller = SpeakContextDistiller(chunk_size=4)
    state = distiller._session("s1")
    with state.lock:
        state.distilled.append("???????")

    orchestrator = SpeakOrchestrator(
        _Persona(),
        _Presence(),
        context_distiller=distiller,
    )
    frame = orchestrator.prepare("s1", generation=5)
    bundle = orchestrator.finalize(frame, "??", session_id="s1")
    assert "???????????" in bundle.guidance.working_memory
    assert "generation=5" in bundle.guidance.working_memory
    assert "??????" in bundle.guidance.working_memory
    assert bundle.persona.dialogue_compressed == ""


def test_ltm_block_label():
    block = render_similar_memories_block(["?????"])
    assert block.startswith("?????????")
    assert "????" in block
    assert "????????" in block


def test_presence_render_excludes_working_memory():
    state = PresenceState()
    state.cognition.working_memory = "??????\n?????"
    state.cognition.thinking = "??????"
    state.perception.narrative = "??????"
    rendered = render_presence(state)
    assert "????" not in rendered
    assert "??????" in rendered


def test_apply_dialogue_session_boundary_clears_verbatim_perception():
    state = PresenceState()
    state.perception.narrative = "??????????????????"
    state.cognition.working_memory = "??????"
    notes = apply_dialogue_session_boundary(state)
    assert state.perception.narrative == ""
    assert state.cognition.working_memory == ""
    assert "boundary" in notes[0]
    assert "??" in state.cognition.thinking


def test_merge_presence_bundles_skips_interaction_perception():
    bundles = [
        PresenceExperienceBundle(
            session_id="tao",
            source="interaction",
            perception="?????????",
            narration="???????",
            salience=0.5,
        ),
        PresenceExperienceBundle(
            session_id="tao",
            source="narrative",
            perception="????",
            narration="?????",
            salience=0.3,
        ),
    ]
    merged = merge_presence_bundles(bundles)
    assert merged is not None
    assert "??" not in merged.perception
    assert "????" in merged.perception
    assert "???????" in merged.narration
