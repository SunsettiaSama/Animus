from __future__ import annotations



from typing import Any, Protocol



from config.soul.presence.config import PROACTIVE_OPEN_THRESHOLD



from agent.soul.speak.io.inbound.compose import SpeakStatusStore

from agent.soul.speak.llm.engine import SpeakLLMEngine



from .bundle import SpeakPromptBundle

from .frame import PreparedComposeFrame

from .guidance.layer import SpeakGuidanceLayer

from .guidance.context import SpeakContextDistiller

from .guidance.control import GuidanceControlService

from .guidance.share import ShareDesireComposer
from .guidance.share.state import ShareComposeState

from .guidance.share.preview import format_share_preview

from .io import OrchestratorIOHub

from .io.inbound.persona import PersonaComposeRequest

from .persona import PersonaComposeService, SpeakPersonaLayer
from .persona.interactor_portrait import (
    MemoryComposePortraitPullPort,
    PersonaInteractorPortraitService,
)

from .scene import SceneComposeService, SpeakSceneLayer

from .turn_assembler import TurnComposeAssembler

from .compose_cache import ComposeCacheRegistry, SessionComposeCache
from .memory import MemoryWarmBuffer
from .session_sync import SessionComposeSyncAgent

from .system.build import build_system_layer

from .system.reply_style import SpeakReplyStyle

from .system.role import SpeakTurnMode





class PersonaQueryPort(Protocol):

    """返回 persona 快照（含 persona_distill 子画像）。"""



    def get_persona_snapshot(self, *, session_id: str = "tao") -> dict[str, Any]: ...





class PresenceReadPort(Protocol):

    def snapshot(self, session_id: str): ...





class SpeakOrchestrator:

    """提示词编排器：总领 system / persona / scene / guidance 四层组装。"""



    def __init__(

        self,

        persona: PersonaQueryPort,

        presence: PresenceReadPort,

        *,

        share_threshold: float = PROACTIVE_OPEN_THRESHOLD,

        context_distiller: SpeakContextDistiller | None = None,

        share_composer: ShareDesireComposer | None = None,

        status_store: SpeakStatusStore | None = None,

        guidance_llm: SpeakLLMEngine | None = None,

        guidance_control: GuidanceControlService | None = None,

        persona_compose: PersonaComposeService | None = None,

        scene_compose: SceneComposeService | None = None,

    ) -> None:

        self._persona = persona

        self._presence = presence

        self._share = share_composer or ShareDesireComposer(

            proactive_threshold=share_threshold,

        )

        self._context = context_distiller

        self._status_store = status_store

        self._guidance_control = guidance_control or GuidanceControlService(llm=guidance_llm)

        if guidance_llm is not None:

            self._guidance_control.set_llm(guidance_llm)

        self._persona_compose = persona_compose or PersonaComposeService(

            persona,

            presence,

            llm=guidance_llm,

            status_store=status_store,

        )

        if guidance_llm is not None:

            self._persona_compose.set_llm(guidance_llm)

        if status_store is not None:

            self._persona_compose.set_status_store(status_store)

        self._scene_compose = scene_compose or SceneComposeService(llm=guidance_llm)

        if guidance_llm is not None:

            self._scene_compose.set_llm(guidance_llm)

        self.io = OrchestratorIOHub.from_services(

            guidance_control=self._guidance_control,

            persona_compose=self._persona_compose,

            scene_compose=self._scene_compose,

        )

        self._compose_assembler = TurnComposeAssembler()

        self._interactor_portrait = PersonaInteractorPortraitService()

        self._session_port = None

        self._compose_caches = ComposeCacheRegistry()
        self._memory_buffers: dict[str, MemoryWarmBuffer] = {}
        self._memory_turn_gap = 3
        self._session_sync = SessionComposeSyncAgent(self)



    @property

    def share(self) -> ShareDesireComposer:

        return self._share



    @property

    def guidance_control(self) -> GuidanceControlService:

        return self._guidance_control



    @property

    def persona_compose(self) -> PersonaComposeService:

        return self._persona_compose



    @property

    def scene_compose(self) -> SceneComposeService:

        return self._scene_compose



    @property

    def compose_assembler(self) -> TurnComposeAssembler:

        return self._compose_assembler



    def bind_story_port(self, story_port, world_id_fn=None) -> None:

        self._scene_compose.bind_story(story_port, world_id_fn)

    def bind_session_port(self, port) -> None:
        self._session_port = port

    def bind_memory_turn_gap(self, turn_gap: int) -> None:
        self._memory_turn_gap = max(1, turn_gap)

    def compose_cache(self, session_id: str) -> SessionComposeCache:
        return self._compose_caches.get(session_id)

    def memory_warm_buffer(self, session_id: str) -> MemoryWarmBuffer:
        sid = session_id.strip()
        buf = self._memory_buffers.get(sid)
        if buf is None:
            buf = MemoryWarmBuffer(max_turn_gap=self._memory_turn_gap)
            self._memory_buffers[sid] = buf
        return buf

    def recall_pick_weight(self, session_id: str, unit_id: str) -> float:
        return self.memory_warm_buffer(session_id).recall_pick_weight(session_id, unit_id)

    def record_recall_pick(self, session_id: str, unit_id: str) -> None:
        self.memory_warm_buffer(session_id).record_recall_pick(session_id, unit_id)

    def start_session_compose_sync(self, session_id: str) -> bool:
        return self._session_sync.schedule(session_id)

    def touch_compose_cache_from_meta(self, session_id: str, meta: dict[str, object]) -> None:
        self.compose_cache(session_id).update_from_meta(meta)

    def attach_session_context(
        self,
        bundle: SpeakPromptBundle,
        session_id: str,
        *,
        generation: int,
    ) -> None:
        """主接口 system：拆分写入上下文蒸馏块与工作记忆块。"""
        if self._context is None or not session_id.strip():
            return
        distill_block, wm_block = self._context.session_context_blocks(
            session_id,
            generation=generation,
        )
        bundle.guidance.context_distill = distill_block
        bundle.guidance.working_memory = wm_block
        raw = self._context.prompt_block(session_id)
        if raw:
            bundle.persona.dialogue_compressed = raw

    def clear_session_compose_state(self, session_id: str) -> None:
        sid = session_id.strip()
        self._compose_caches.clear(sid)
        buf = self._memory_buffers.pop(sid, None)
        if buf is not None:
            buf.clear_session(sid)

    @property
    def interactor_portrait(self) -> PersonaInteractorPortraitService:
        return self._interactor_portrait

    def bind_interactor_portrait_bridge(
        self,
        memory_compose_bridge,
        *,
        portrait_wait_ms: int = 100,
    ) -> None:
        self._interactor_portrait.bind_pull_port(
            MemoryComposePortraitPullPort(memory_compose_bridge),
        )
        self._interactor_portrait.bind_request(
            lambda session_id, turn_index, user_text, agent_text: memory_compose_bridge.request_interactor_portrait(
                session_id,
                turn_index=turn_index,
                user_text=user_text,
                agent_text=agent_text,
            ),
        )
        self._interactor_portrait._wait_ms = max(0, portrait_wait_ms)

    def reconcile_compose(self, bundle: SpeakPromptBundle, *, session_id: str):
        from .compose_reconcile import build_compose_reconcile_plan

        if self._session_port is None:
            return None
        session = self._session_port.signals(session_id)
        return build_compose_reconcile_plan(
            bundle_meta=bundle.meta,
            io=self.io,
            session=session,
        )

    def clear_guidance_control_arc(self, session_id: str) -> None:

        self.io.inbound.guidance.clear_control_arc(session_id)



    def clear_persona_compose(self, session_id: str) -> None:

        self.io.inbound.persona.clear(session_id)



    def clear_scene_compose(self, session_id: str) -> None:

        self.io.inbound.scene.clear(session_id)



    def guidance_snapshot(self, session_id: str) -> dict[str, object] | None:

        return self.io.outbound.guidance.snapshot(session_id)



    def persona_snapshot(self, session_id: str) -> dict[str, object] | None:

        return self.io.outbound.persona.snapshot(session_id)



    def guidance_version(self, session_id: str) -> int | None:

        return self.io.outbound.guidance.version(session_id)



    def persona_version(self, session_id: str) -> int | None:

        return self.io.outbound.persona.version(session_id)



    def collect_share_count(self, session_id: str) -> int:

        presence_snap = self._presence.snapshot(session_id)

        share_state = self._share.collect(presence_snap, session_id=session_id)

        return share_state.count

    def share_compose_state(self, session_id: str) -> ShareComposeState:
        presence_snap = self._presence.snapshot(session_id)
        return self._share.collect(presence_snap, session_id=session_id)

    def uses_session_share_queue(self, session_id: str) -> bool:
        reader = self._share._session_share_reader
        if reader is None or not session_id.strip():
            return False
        injected = reader(session_id.strip())
        return injected is not None and not injected.is_empty()



    def sync_persona_for_compose(
        self,
        request: PersonaComposeRequest,
        *,
        force: bool = False,
    ) -> bool:
        return self.io.inbound.persona.sync_for_compose(request, force=force)

    def _compose_persona_layer(
        self,
        session_id: str,
        *,
        turn_index: int = 0,
        force: bool = False,
        injected_context: str = "",
        dialogue_compressed: str = "",
    ) -> SpeakPersonaLayer:
        self.sync_persona_for_compose(
            PersonaComposeRequest(
                session_id=session_id,
                turn_index=turn_index,
                force=force,
                injected_context=injected_context,
                dialogue_compressed=dialogue_compressed,
            ),
            force=force,
        )
        return self.io.outbound.persona.build_layer(session_id)



    def prepare(

        self,

        session_id: str,

        *,

        mode: SpeakTurnMode = "inbound",

        reply_style: SpeakReplyStyle | None = None,

        generation: int = 0,

    ) -> PreparedComposeFrame:

        presence_snap = self._presence.snapshot(session_id)

        share_state = self._share.collect(presence_snap, session_id=session_id)

        drive_eval = self._share.evaluate_drive(presence_snap, session_id=session_id)

        style = reply_style or SpeakReplyStyle()



        return PreparedComposeFrame(

            session_id=session_id,

            mode=mode,

            generation=generation,

            system=build_system_layer(

                mode=mode,

                output_format=style.render_prompt(),

            ),

            persona=self._compose_persona_layer(session_id),

            scene=SpeakSceneLayer(),

            guidance=SpeakGuidanceLayer(

                share_preview=format_share_preview(share_state),

            ),

            wants_share=share_state.wants_share,

            share_summary=share_state.summary,

            notes=list(drive_eval.notes),

            reply_style=style,

        )



    def refresh_persona_for_turn(
        self,
        session_id: str,
        persona: SpeakPersonaLayer,
        *,
        turn_index: int = 0,
    ) -> SpeakPersonaLayer:
        """预组装 persona 可能过时：注入对话上下文并刷新自叙。"""
        dialogue = persona.dialogue_compressed.strip()
        if not dialogue:
            wm = self._session_working_memory(session_id, generation=0)
            dialogue = wm[:400].strip() if wm else ""
        self.sync_persona_for_compose(
            PersonaComposeRequest(
                session_id=session_id,
                turn_index=turn_index,
                force=True,
                injected_context=dialogue,
                dialogue_compressed=dialogue,
            ),
            force=True,
        )
        merged = self.io.outbound.persona.apply_to_layer(persona, session_id)
        if dialogue:
            merged.dialogue_compressed = dialogue
        return merged



    def _session_working_memory(

        self,

        session_id: str,

        *,

        generation: int,

    ) -> str:

        if self._context is None or not session_id.strip():

            return ""

        return self._context.working_memory_block(session_id, generation=generation)



    def finalize(

        self,

        frame: PreparedComposeFrame,

        user_text: str,

        *,

        session_id: str | None = None,

    ) -> SpeakPromptBundle:

        persona = frame.persona

        sid = (session_id or frame.session_id).strip()

        if sid:

            persona = self.refresh_persona_for_turn(sid, persona)

        guidance = SpeakGuidanceLayer(

            share_preview=frame.guidance.share_preview,

            control_arc=frame.guidance.control_arc,

            social_blocks=list(frame.guidance.social_blocks),

        )

        bundle = SpeakPromptBundle(

            session_id=frame.session_id,

            mode=frame.mode,

            system=frame.system,

            persona=persona,

            scene=frame.scene,

            guidance=guidance,

            user_text=user_text.strip(),

            wants_share=frame.wants_share,

            share_summary=frame.share_summary,

            reply_style=frame.reply_style,

            notes=list(frame.notes),

            meta={"compose_source": "prefetch"},

        )
        if sid:
            self.attach_session_context(bundle, sid, generation=frame.generation)
        return bundle



    def compose(

        self,

        session_id: str,

        user_text: str,

        *,

        mode: SpeakTurnMode = "inbound",

        reply_style: SpeakReplyStyle | None = None,

        generation: int = 0,

    ) -> SpeakPromptBundle:

        frame = self.prepare(session_id, mode=mode, reply_style=reply_style, generation=generation)

        bundle = self.finalize(frame, user_text, session_id=session_id)

        bundle.meta["compose_source"] = "sync"

        return bundle



    def reveal_share(

        self,

        session_id: str,

        pointer: str,

        *,

        trigger_source: str = "",

    ):

        presence_snap = self._presence.snapshot(session_id)

        return self._share.reveal(

            presence_snap,

            pointer,

            session_id=session_id,

            trigger_source=trigger_source,

        )



    def finish_turn_bundle(

        self,

        bundle: SpeakPromptBundle,

        *,

        social,

        session_id: str,

        user_text: str,

        turn_index: int,

        mode: SpeakTurnMode = "inbound",

        story_port=None,

        world_id_fn=None,

        share_queue_count: int | None = None,

    ) -> SpeakPromptBundle:

        from .assemble import finish_turn_bundle



        resolved_share_count = (

            share_queue_count

            if share_queue_count is not None

            else self.collect_share_count(session_id)

        )

        presence_snap = self._presence.snapshot(session_id)

        share_state = self._share.collect(presence_snap, session_id=session_id)

        use_session_share = self.uses_session_share_queue(session_id)

        reconcile_plan = self.reconcile_compose(bundle, session_id=session_id)

        return finish_turn_bundle(

            bundle,

            social=social,

            session_id=session_id,

            user_text=user_text,

            turn_index=turn_index,

            mode=mode,

            story_port=story_port,

            world_id_fn=world_id_fn,

            io=self.io,

            share_queue_count=resolved_share_count,

            share_state=share_state,

            use_session_share_queue=use_session_share,

            session_port=self._session_port,

            reconcile_plan=reconcile_plan,

        )


