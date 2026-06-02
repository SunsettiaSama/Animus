from __future__ import annotations

import threading
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from .compose_reconcile import build_compose_reconcile_plan
from .compose_slots import KNOWN_COMPOSE_BLOCKS
from .guidance.inbound.persona_brief import build_guidance_plan_request
from .io.inbound.persona import PersonaComposeRequest
from .io.inbound.scene import SceneUpdateRequest
from .persona.outbound.brief import collect_persona_outbound_brief

if TYPE_CHECKING:
    from .orchestrator import SpeakOrchestrator


def _default_submit(task: Callable[[], None]) -> None:
    thread = threading.Thread(target=task, daemon=True)
    thread.start()


class SessionComposeSyncAgent:
    """会话重连后异步对照 live 版本，向各子模块下发 refresh 指令。"""

    def __init__(
        self,
        orchestrator: SpeakOrchestrator,
        *,
        submit: Callable[[Callable[[], None]], None] | None = None,
    ) -> None:
        self._orchestrator = orchestrator
        self._submit = submit or _default_submit
        self._inflight: set[str] = set()
        self._lock = threading.Lock()

    def schedule(self, session_id: str) -> bool:
        sid = session_id.strip()
        if not sid:
            return False
        with self._lock:
            if sid in self._inflight:
                return False
            self._inflight.add(sid)
        self._submit(lambda: self._run(sid))
        return True

    def _run(self, session_id: str) -> None:
        notes: list[str] = []
        notes.append(f"session_compose_sync: start {session_id}")
        port = self._orchestrator._session_port
        if port is None:
            notes.append("session_compose_sync: no session port")
            self._finish(session_id, notes)
            return

        cache = self._orchestrator.compose_cache(session_id)
        session = port.signals(session_id)
        plan = build_compose_reconcile_plan(
            bundle_meta=cache.meta_snapshot(),
            io=self._orchestrator.io,
            session=session,
        )
        notes.extend(plan.notes)
        turn_index = session.turn_index
        wm = self._orchestrator._session_working_memory(session_id, generation=session.generation)
        distilled = wm[:400].strip() if wm else ""

        for block in KNOWN_COMPOSE_BLOCKS:
            directive = plan.directive_for(block)
            if directive.action != "refresh":
                continue
            notes.append(
                f"session_compose_sync: refresh {block} ({directive.reason})"
            )
            if block == "persona":
                self._orchestrator.io.inbound.persona.sync_for_compose(
                    PersonaComposeRequest(
                        session_id=session_id,
                        turn_index=turn_index,
                        force=directive.force,
                        injected_context=distilled,
                        dialogue_compressed=distilled,
                    ),
                    force=directive.force,
                )
            elif block == "scene":
                query = distilled or wm[:120].strip()
                if query and self._orchestrator.io.inbound.scene.service.has_story_binding():
                    self._orchestrator.io.inbound.scene.sync_for_turn(
                        SceneUpdateRequest(
                            session_id=session_id,
                            turn_index=turn_index,
                            query=query,
                            force=directive.force,
                        ),
                        force=directive.force,
                    )
            elif block == "guidance":
                layer = self._orchestrator.io.outbound.persona.build_layer(session_id)
                persona_brief = collect_persona_outbound_brief(
                    self._orchestrator.io,
                    session_id=session_id,
                    layer=layer,
                )
                request = build_guidance_plan_request(
                    session_id=session_id,
                    turn_index=turn_index,
                    distilled_context=distilled,
                    persona_brief=persona_brief,
                    interactor_portrait="",
                    share_preview="",
                    recall_preview="",
                    share_candidates=(),
                    recall_candidates=(),
                    share_queue_count=0,
                    share_queue_full=False,
                    use_session_share_queue=False,
                )
                self._orchestrator.io.inbound.guidance.sync_for_compose(
                    request,
                    force=directive.force,
                )

        meta = self._live_meta(session_id, generation=session.generation)
        cache.update_from_meta(meta)
        notes.append("session_compose_sync: done")
        self._finish(session_id, notes)

    def _live_meta(self, session_id: str, *, generation: int) -> dict[str, Any]:
        io = self._orchestrator.io
        slots: list[dict[str, object]] = []
        persona_layer = io.outbound.persona.build_layer(session_id)
        persona_version = io.outbound.persona.version(session_id) or 0
        slots.append(
            {
                "block": "persona",
                "narrative": persona_layer.self_narrative.strip(),
                "version": persona_version,
            }
        )
        scene_version = io.outbound.scene.version(session_id) or 0
        scene_narrative = ""
        scene_snap = io.outbound.scene.snapshot(session_id)
        if isinstance(scene_snap, dict):
            scene_narrative = str(scene_snap.get("world_scene") or "").strip()
        slots.append(
            {
                "block": "scene",
                "narrative": scene_narrative,
                "version": scene_version,
            }
        )
        guidance_version = io.outbound.guidance.version(session_id) or 0
        guidance_narrative = ""
        control = io.inbound.guidance.control.active(session_id)
        if control is not None:
            guidance_narrative = control.narrative.strip()
        slots.append(
            {
                "block": "guidance",
                "narrative": guidance_narrative,
                "version": guidance_version,
            }
        )
        return {
            "compose_session_generation": generation,
            "turn_compose_assembly": {
                "session_id": session_id,
                "slots": slots,
            },
        }

    def _finish(self, session_id: str, notes: list[str]) -> None:
        cache = self._orchestrator.compose_cache(session_id)
        cache.sync_notes.extend(notes)
        with self._lock:
            self._inflight.discard(session_id)
