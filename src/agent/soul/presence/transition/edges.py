from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from ..expectation import Expectation
from ..fsm.events import DriveEvent, DriveEventKind
from ..fsm.state import DriveContext, DriveState

Guard = Callable[[DriveState, DriveContext, dict], bool]
Mutate = Callable[[DriveState, DriveState, DriveContext, dict], None]


@dataclass(frozen=True)
class DriveEdge:
    id: str
    on: DriveEventKind
    note: str
    line_open: bool | None = None
    expectation: Expectation | None = None
    guard: Guard | None = None
    mutate: Mutate | None = None


def _payload_flag(payload: dict, key: str) -> bool:
    return bool(payload.get(key))


def _mutate_expectation(value: Expectation) -> Mutate:
    def _run(
        after: DriveState,
        _before: DriveState,
        _ctx: DriveContext,
        _payload: dict,
    ) -> None:
        after.expectation = value

    return _run


def _mutate_user_text_closed_required(
    after: DriveState,
    _before: DriveState,
    _ctx: DriveContext,
    _payload: dict,
) -> None:
    after.expectation = Expectation.required


def _mutate_user_text_closed_clarify(
    after: DriveState,
    _before: DriveState,
    _ctx: DriveContext,
    _payload: dict,
) -> None:
    after.expectation = Expectation.clarify


def _mutate_agent_utterance(
    after: DriveState,
    _before: DriveState,
    _ctx: DriveContext,
    payload: dict,
) -> None:
    if _payload_flag(payload, "notify_only"):
        after.expectation = Expectation.optional
    elif _payload_flag(payload, "has_question"):
        after.expectation = Expectation.required
    elif _payload_flag(payload, "final"):
        after.expectation = Expectation.none
    else:
        after.expectation = Expectation.deferred


def _mutate_agent_deferred(
    after: DriveState,
    _before: DriveState,
    _ctx: DriveContext,
    _payload: dict,
) -> None:
    after.expectation = Expectation.deferred


def _mutate_proactive_open(
    after: DriveState,
    _before: DriveState,
    _ctx: DriveContext,
    payload: dict,
) -> None:
    wait = bool(payload.get("wait_reply", True))
    after.expectation = Expectation.required if wait else Expectation.optional


def _mutate_proactive_delivered(
    after: DriveState,
    _before: DriveState,
    _ctx: DriveContext,
    payload: dict,
) -> None:
    wait = bool(payload.get("wait_reply", True))
    after.expectation = Expectation.required if wait else Expectation.optional


def _mutate_ambiguity_detected(
    after: DriveState,
    _before: DriveState,
    _ctx: DriveContext,
    _payload: dict,
) -> None:
    after.expectation = Expectation.clarify


def _mutate_scene_enter(
    after: DriveState,
    before: DriveState,
    _ctx: DriveContext,
    _payload: dict,
) -> None:
    if before.expectation == Expectation.none:
        after.expectation = Expectation.deferred


DRIVE_EDGES: tuple[DriveEdge, ...] = (
    DriveEdge(
        id="user_text.closed.open.required",
        on=DriveEventKind.user_text,
        line_open=False,
        guard=lambda _s, _c, p: not _payload_flag(p, "ambiguous"),
        mutate=_mutate_user_text_closed_required,
        note="line opened → expectation required",
    ),
    DriveEdge(
        id="user_text.closed.open.clarify",
        on=DriveEventKind.user_text,
        line_open=False,
        guard=lambda _s, _c, p: _payload_flag(p, "ambiguous"),
        mutate=_mutate_user_text_closed_clarify,
        note="line opened → expectation clarify",
    ),
    DriveEdge(
        id="user_text.clarify.resolved",
        on=DriveEventKind.user_text,
        expectation=Expectation.clarify,
        guard=lambda _s, _c, p: _payload_flag(p, "resolves_clarify"),
        mutate=_mutate_expectation(Expectation.required),
        note="clarify→required",
    ),
    DriveEdge(
        id="user_text.open.ambiguous",
        on=DriveEventKind.user_text,
        line_open=True,
        guard=lambda _s, _c, p: _payload_flag(p, "ambiguous"),
        mutate=_mutate_expectation(Expectation.clarify),
        note="→clarify",
    ),
    DriveEdge(
        id="user_text.optional.to_required",
        on=DriveEventKind.user_text,
        expectation=Expectation.optional,
        mutate=_mutate_expectation(Expectation.required),
        note="optional→required",
    ),
    DriveEdge(
        id="user_text.open.none.to_required",
        on=DriveEventKind.user_text,
        line_open=True,
        expectation=Expectation.none,
        mutate=_mutate_expectation(Expectation.required),
        note="open line + none→required",
    ),
    DriveEdge(
        id="user_text.proactive.reply",
        on=DriveEventKind.user_text,
        guard=lambda _s, c, p: bool(c.proactive_intent_id or p.get("proactive_intent_id")),
        mutate=_mutate_expectation(Expectation.required),
        note="proactive intent answered → required",
    ),
    DriveEdge(
        id="user_text.noop",
        on=DriveEventKind.user_text,
        mutate=lambda _a, _b, _c, _p: None,
        note="user_text absorbed",
    ),
    DriveEdge(
        id="agent_utterance",
        on=DriveEventKind.agent_utterance,
        mutate=_mutate_agent_utterance,
        note="agent_utterance",
    ),
    DriveEdge(
        id="agent_deferred",
        on=DriveEventKind.agent_deferred,
        mutate=_mutate_agent_deferred,
        note="→deferred",
    ),
    DriveEdge(
        id="proactive_open",
        on=DriveEventKind.proactive_open,
        mutate=_mutate_proactive_open,
        note="proactive_open",
    ),
    DriveEdge(
        id="proactive_delivered",
        on=DriveEventKind.proactive_delivered,
        mutate=_mutate_proactive_delivered,
        note="proactive_delivered",
    ),
    DriveEdge(
        id="ambiguity_detected",
        on=DriveEventKind.ambiguity_detected,
        mutate=_mutate_ambiguity_detected,
        note="ambiguity_detected → clarify",
    ),
    DriveEdge(
        id="clarify_resolved",
        on=DriveEventKind.clarify_resolved,
        mutate=_mutate_expectation(Expectation.required),
        note="clarify_resolved → required",
    ),
    DriveEdge(
        id="scene_enter",
        on=DriveEventKind.scene_enter,
        mutate=_mutate_scene_enter,
        note="scene_enter",
    ),
)


def _edge_matches(
    edge: DriveEdge,
    before: DriveState,
    context: DriveContext,
    event: DriveEvent,
) -> bool:
    if edge.on != event.kind:
        return False
    if edge.line_open is not None and context.line_open != edge.line_open:
        return False
    if edge.expectation is not None and before.expectation != edge.expectation:
        return False
    if edge.guard is not None and not edge.guard(before, context, event.payload):
        return False
    return True


def match_drive_edge(
    before: DriveState,
    context: DriveContext,
    event: DriveEvent,
) -> DriveEdge | None:
    for edge in DRIVE_EDGES:
        if _edge_matches(edge, before, context, event):
            return edge
    return None
