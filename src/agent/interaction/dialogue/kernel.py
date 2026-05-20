from __future__ import annotations

from collections.abc import Callable

from agent.interaction.core.continuity import (
    ContinuityInput,
    ContinuityJudge,
    ContinuityVerdict,
    StackedContinuityJudge,
)
from agent.interaction.core.context import InteractionContext, SceneRef
from agent.interaction.core.events import InteractionClosedEvent
from agent.interaction.core.expectation import Expectation
from agent.interaction.core.semantic import InteractionCloseReason, SemanticInteraction
from agent.interaction.core.segments import InteractionDirection
from agent.interaction.kinds import InteractionModalityKind
from agent.posture import InteractionEvent, InteractionPosture
from agent.soul.drive import DriveContext, DriveEvent, DriveLayer


class DialogueKernel:
    """对话模态内核：SemanticInteraction + posture 结构态 + Soul 驱动期待。"""

    def __init__(
        self,
        continuity: ContinuityJudge | None = None,
        posture: InteractionPosture | None = None,
        drive: DriveLayer | None = None,
        on_closed: Callable[[InteractionClosedEvent], None] | None = None,
    ) -> None:
        self._continuity = continuity or StackedContinuityJudge()
        self._posture = posture or InteractionPosture()
        self._drive = drive or DriveLayer()
        self._on_closed = on_closed
        self._active: dict[str, SemanticInteraction] = {}

    @property
    def posture(self) -> InteractionPosture:
        return self._posture

    @property
    def drive(self) -> DriveLayer:
        return self._drive

    def active(self, session_id: str) -> SemanticInteraction | None:
        item = self._active.get(session_id)
        if item is not None and item.is_open:
            return item
        return None

    def open(
        self,
        session_id: str,
        *,
        direction: InteractionDirection = InteractionDirection.inbound,
        channel: str = "",
        stakes: str = "",
        expectation: Expectation = Expectation.required,
    ) -> SemanticInteraction:
        ctx = InteractionContext(
            session_id=session_id,
            channel=channel,
            expectation=expectation,
        )
        interaction = SemanticInteraction(
            context=ctx,
            direction=direction,
            stakes=stakes,
        )
        self._active[session_id] = interaction
        self._posture.bind_interaction(
            session_id,
            interaction.id,
            stakes=stakes,
            channel=channel,
            modality=InteractionModalityKind.dialogue.value,
        )
        self._drive.bind(session_id, expectation=expectation)
        self._sync_interaction_from_layers(interaction, session_id)
        return interaction

    def admit_scene(
        self,
        session_id: str,
        scene: SceneRef,
        *,
        admitted: bool = True,
    ) -> SemanticInteraction:
        interaction = self._require_open(session_id)
        self._posture.dispatch(
            InteractionEvent.scene_enter(
                session_id,
                scene_id=scene.scene_id,
                scene_kind=scene.kind,
                title=scene.title,
                stakes=interaction.stakes,
                admitted=admitted,
            )
        )
        self._dispatch_drive(DriveEvent.scene_enter(session_id))
        self._sync_interaction_from_layers(interaction, session_id)
        return interaction

    def leave_scene(self, session_id: str) -> SemanticInteraction:
        interaction = self._require_open(session_id)
        self._posture.dispatch(InteractionEvent.scene_leave(session_id))
        self._sync_interaction_from_layers(interaction, session_id)
        return interaction

    def allows_behavior(self, session_id: str, action_name: str) -> bool:
        interaction = self.active(session_id)
        if interaction is None:
            return False
        snap = self._posture.snapshot(session_id)
        if snap.in_scene and snap.scene_admitted:
            return True
        return action_name in ("finish",)

    def on_user_text(
        self,
        session_id: str,
        text: str,
        *,
        channel: str = "",
        ambiguous: bool = False,
    ) -> SemanticInteraction:
        active = self.active(session_id)
        decision = self._continuity.judge(
            ContinuityInput(active=active, incoming_user_text=text)
        )
        if decision.verdict == ContinuityVerdict.close_and_new:
            if active is not None and active.is_open:
                reason = InteractionCloseReason.user_shift
                if decision.reason.startswith("idle"):
                    reason = InteractionCloseReason.idle_timeout
                elif decision.reason == "break_phrase":
                    reason = InteractionCloseReason.user_shift
                else:
                    reason = InteractionCloseReason.continuity_break
                self.close(session_id, reason)
            interaction = self.open(
                session_id,
                channel=channel,
                direction=InteractionDirection.inbound,
            )
        else:
            interaction = active or self.open(session_id, channel=channel)
        interaction.append_user(text)
        posture_snap = self._posture.snapshot(session_id)
        drive_ctx = DriveContext(
            line_open=posture_snap.line_open,
            proactive_intent_id=posture_snap.proactive_intent_id,
        )
        self._posture.dispatch(
            InteractionEvent.user_text(
                session_id, text, ambiguous=ambiguous
            )
        )
        self._drive.dispatch(
            DriveEvent.user_text(
                session_id,
                ambiguous=ambiguous,
                proactive_intent_id=posture_snap.proactive_intent_id,
            ),
            context=drive_ctx,
        )
        self._sync_interaction_from_layers(interaction, session_id)
        return interaction

    def close(
        self,
        session_id: str,
        reason: InteractionCloseReason,
    ) -> SemanticInteraction | None:
        interaction = self._active.get(session_id)
        if interaction is None or not interaction.is_open:
            return None
        interaction.close(reason)
        self._posture.dispatch(
            InteractionEvent.close(session_id, reason=reason.value)
        )
        self._dispatch_drive(
            DriveEvent.close(session_id, reason=reason.value)
        )
        if self._on_closed is not None:
            self._on_closed(InteractionClosedEvent(interaction=interaction))
        return interaction

    def dispatch_posture(self, event: InteractionEvent) -> None:
        self._posture.dispatch(event)
        drive_event = self._map_posture_event_to_drive(event)
        if drive_event is not None:
            self._dispatch_drive(drive_event)
        session_id = event.session_id
        interaction = self._active.get(session_id)
        if interaction is not None and interaction.is_open:
            self._sync_interaction_from_layers(interaction, session_id)

    def _map_posture_event_to_drive(
        self,
        event: InteractionEvent,
    ) -> DriveEvent | None:
        sid = event.session_id
        p = event.payload
        kind = event.kind.value
        if kind == "agent_utterance":
            return DriveEvent.agent_utterance(
                sid,
                has_question=bool(p.get("has_question")),
                final=bool(p.get("final")),
                notify_only=bool(p.get("notify_only")),
            )
        if kind == "agent_deferred":
            return DriveEvent.agent_deferred(sid)
        if kind == "proactive_open":
            return DriveEvent.proactive_open(
                sid,
                wait_reply=bool(p.get("wait_reply", True)),
            )
        if kind == "proactive_delivered":
            return DriveEvent.proactive_delivered(sid)
        if kind == "ambiguity_detected":
            return DriveEvent.ambiguity_detected(
                sid,
                reason=str(p.get("reason", "")),
            )
        if kind == "clarify_resolved":
            return DriveEvent.clarify_resolved(sid)
        return None

    def _dispatch_drive(self, event: DriveEvent) -> None:
        snap = self._posture.snapshot(event.session_id)
        self._drive.dispatch(
            event,
            context=DriveContext(
                line_open=snap.line_open,
                proactive_intent_id=snap.proactive_intent_id,
            ),
        )

    def _sync_interaction_from_layers(
        self,
        interaction: SemanticInteraction,
        session_id: str,
    ) -> None:
        snap = self._posture.snapshot(session_id)
        drive_snap = self._drive.snapshot(session_id)
        interaction.expectation = drive_snap.expectation
        interaction.context.expectation = drive_snap.expectation
        interaction.context.in_scene = snap.in_scene
        interaction.context.proactive_intent_id = snap.proactive_intent_id
        if snap.channel:
            interaction.context.channel = snap.channel
        if snap.in_scene and snap.scene_id:
            interaction.context.active_scene = SceneRef(
                scene_id=snap.scene_id,
                kind=snap.scene_kind,
                title=snap.scene_title,
            )
        else:
            interaction.context.active_scene = None

    def _require_open(self, session_id: str) -> SemanticInteraction:
        interaction = self.active(session_id)
        if interaction is None:
            raise RuntimeError(f"no open SemanticInteraction for session {session_id!r}")
        return interaction
