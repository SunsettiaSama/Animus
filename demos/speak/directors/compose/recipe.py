from __future__ import annotations

from dataclasses import dataclass

from ...contracts import RhythmPlan, ShareHandOff
from ...stage.on_scene import OnSceneState


@dataclass(frozen=True)
class AssemblyRecipe:
    """Per-reply assembly recipe chosen by compose."""

    include_persona: bool = True
    include_presence: bool = True
    include_portrait: bool = True
    include_mood: bool = True
    include_on_scene: bool = True
    include_rhythm_guide: bool = True
    include_context: bool = False
    include_scene: bool = False
    include_share: bool = False
    ask_memory: bool = False
    ask_journal: bool = False
    notes: tuple[str, ...] = ()


def decide_recipe(
    on_scene: OnSceneState,
    rhythm: RhythmPlan,
    handoff: ShareHandOff,
) -> AssemblyRecipe:
    """Choose optional compose blocks from rhythm command and on-scene focus."""
    focus = on_scene.focus if on_scene.ready else "present"
    notes = [
        "grain=per_reply",
        f"gate={rhythm.gate}",
        f"on_scene_focus={focus}",
        f"on_scene_ready={on_scene.ready}",
    ]

    include_context = False
    include_scene = False
    ask_memory = False
    ask_journal = False
    include_share = handoff.active

    if rhythm.gate == "speak":
        include_context = True
        notes.append("cmd_speak_need_context")
    elif rhythm.gate == "brew":
        include_context = False
        notes.append("cmd_brew_lean")

    if handoff.active:
        include_share = True
        include_context = True
        notes.append(f"cmd_share={handoff.tag}")

    if handoff.tag == "expand" or rhythm.share_tag == "expand":
        ask_memory = True
        notes.append("cmd_expand_ask_memory")

    if rhythm.cue.strip() or rhythm.reply_guide.strip():
        notes.append("cmd_has_reply_guide")

    if focus == "drift":
        include_scene = False
        ask_journal = False
        if not handoff.active and rhythm.gate == "brew":
            include_context = False
        notes.append("tune_drift_lighten")
    elif focus == "notice":
        include_scene = True
        ask_journal = True
        notes.append("tune_notice_scene_journal")
    else:
        notes.append("tune_present")

    return AssemblyRecipe(
        include_persona=True,
        include_presence=True,
        include_portrait=True,
        include_mood=True,
        include_on_scene=on_scene.ready,
        include_rhythm_guide=True,
        include_context=include_context,
        include_scene=include_scene,
        include_share=include_share,
        ask_memory=ask_memory,
        ask_journal=ask_journal,
        notes=tuple(notes),
    )
