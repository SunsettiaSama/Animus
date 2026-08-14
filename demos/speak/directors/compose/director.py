from __future__ import annotations

from ...contracts import ComposeBundle, RhythmPlan, ShareHandOff
from ...stage import StageSnapshot, StageState
from .ports import JournalPort, MemoryRecallPort, NullJournal, NullMemoryRecall
from .recipe import decide_recipe


class ComposeDirector:
    """
    拼接导演：粒度 = 每一轮回复。

    仅在 rhythm 开口指令到达时决策：把哪些块拼进本轮回复。
    不轮询临场；临场由外部异步注入后，本轮读到什么就用什么。
    """

    name = "compose"

    def __init__(
        self,
        *,
        memory: MemoryRecallPort | None = None,
        journal: JournalPort | None = None,
    ) -> None:
        self._memory = memory or NullMemoryRecall()
        self._journal = journal or NullJournal()

    def run(
        self,
        stage: StageState,
        snapshot: StageSnapshot,
        *,
        rhythm: RhythmPlan,
        share_handoff: ShareHandOff | None = None,
    ) -> ComposeBundle:
        if not rhythm.should_speak:
            raise RuntimeError("compose: 仅在本轮开口时拼装，listen/hold 不触发")

        handoff = share_handoff or ShareHandOff(tag="none")
        on_scene = stage.on_scene
        recipe = decide_recipe(on_scene, rhythm, handoff)

        memory_hint = ""
        if recipe.ask_memory:
            memory_hint = self._memory.recall(
                stage, on_scene=on_scene, rhythm=rhythm
            ).strip()

        journal_text = ""
        if recipe.ask_journal:
            journal_text = self._journal.peek(
                stage, on_scene=on_scene, rhythm=rhythm
            ).strip()

        notes = list(recipe.notes)
        if handoff.active and handoff.event is not None:
            notes.append(f"share_id={handoff.event.event_id}")
        if recipe.ask_journal and not journal_text:
            notes.append("journal_port_empty")
        if recipe.ask_memory and not memory_hint:
            notes.append("memory_port_empty")

        portrait = ""
        if recipe.include_portrait:
            portrait = stage.interactor_portrait.strip() or stage.cast.user

        presence = ""
        if recipe.include_presence:
            presence = stage.agent_presence or stage.agent_status

        context_block = ""
        if recipe.include_context:
            context_block = stage.working_memory() or snapshot.context_distill

        scene_block = ""
        if recipe.include_scene:
            scene_block = stage.agent_scene.strip()

        share_title = handoff.material_line() if recipe.include_share else ""

        return ComposeBundle(
            session_id=snapshot.session_id,
            turn_index=snapshot.turn_index,
            persona_block=stage.agent_persona if recipe.include_persona else "",
            presence_block=presence,
            portrait_block=portrait,
            on_scene_block=on_scene.text if recipe.include_on_scene else "",
            memory_hint=memory_hint,
            journal_block=journal_text,
            context_block=context_block,
            scene_block=scene_block,
            mood_block=stage.affect.label if recipe.include_mood else "",
            include_portrait=recipe.include_portrait,
            include_memory=bool(memory_hint),
            include_architecture_note=False,
            proactive=snapshot.trigger == "poll",
            share_title=share_title,
            notes=tuple(notes),
        )
