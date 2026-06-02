from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .compose_slots import KNOWN_COMPOSE_BLOCKS
from .guidance.inbound.persona_brief import build_guidance_plan_request
from .io.inbound.persona import PersonaComposeRequest
from .io.inbound.scene import SceneUpdateRequest
from .persona.outbound.brief import collect_persona_outbound_brief
from .turn_coordinator import ModuleRefreshFlags

if TYPE_CHECKING:
    from .orchestrator import SpeakOrchestrator


def apply_module_refresh(
    orchestrator: SpeakOrchestrator,
    session_id: str,
    flags: ModuleRefreshFlags,
    *,
    generation: int,
    turn_index: int,
) -> dict[str, Any]:
    """当轮同步刷新：仅对 refresh=True 的 compose 块下发 inbound sync。"""
    sid = session_id.strip()
    notes: list[str] = []
    snapshot = flags.snapshot()
    notes.append(f"module_refresh: {snapshot}")

    port = orchestrator._session_port
    if port is None:
        notes.append("module_refresh: no session port")
        return {"flags": snapshot, "notes": notes}

    if not any(snapshot.values()):
        notes.append("module_refresh: skip (no flags)")
        return {"flags": snapshot, "notes": notes}

    wm = orchestrator._session_working_memory(sid, generation=generation)
    distilled = wm[:400].strip() if wm else ""

    io = orchestrator.io
    for block in KNOWN_COMPOSE_BLOCKS:
        refresh = {
            "persona": flags.persona,
            "scene": flags.scene,
            "guidance": flags.guidance,
        }.get(block, False)
        if not refresh:
            continue
        notes.append(f"module_refresh: sync {block}")
        if block == "persona":
            io.inbound.persona.sync_for_compose(
                PersonaComposeRequest(
                    session_id=sid,
                    turn_index=turn_index,
                    force=True,
                    injected_context=distilled,
                    dialogue_compressed=distilled,
                ),
                force=True,
            )
        elif block == "scene":
            query = distilled or wm[:120].strip()
            if query and io.inbound.scene.service.has_story_binding():
                io.inbound.scene.sync_for_turn(
                    SceneUpdateRequest(
                        session_id=sid,
                        turn_index=turn_index,
                        query=query,
                        force=True,
                    ),
                    force=True,
                )
        elif block == "guidance":
            layer = io.outbound.persona.build_layer(sid)
            persona_brief = collect_persona_outbound_brief(
                io,
                session_id=sid,
                layer=layer,
            )
            request = build_guidance_plan_request(
                session_id=sid,
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
            io.inbound.guidance.sync_for_compose(request, force=True)

    cache = orchestrator.compose_cache(sid)
    meta = _live_meta(orchestrator, sid, generation=generation)
    cache.update_from_meta(meta)
    notes.append("module_refresh: cache touched")
    return {"flags": snapshot, "notes": notes}


def _live_meta(orchestrator: SpeakOrchestrator, session_id: str, *, generation: int) -> dict[str, Any]:
    io = orchestrator.io
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
