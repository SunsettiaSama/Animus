from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from ..expectation import Expectation
from ..interaction import PresenceInteraction
from ...state import PresenceContext, PresenceEvent, PresenceEventKind

Guard = Callable[[PresenceInteraction, PresenceContext, dict], bool]
Mutate = Callable[[PresenceInteraction, PresenceInteraction, PresenceContext, dict], None]


@dataclass(frozen=True)
class PresenceEdge:
    id: str
    on: PresenceEventKind
    note: str
    line_open: bool | None = None
    expectation: Expectation | None = None
    guard: Guard | None = None
    mutate: Mutate | None = None


def _payload_flag(payload: dict, key: str) -> bool:
    return bool(payload.get(key))


def _mutate_expectation(value: Expectation) -> Mutate:
    def _run(
        after: PresenceInteraction,
        _before: PresenceInteraction,
        _ctx: PresenceContext,
        _payload: dict,
    ) -> None:
        after.expectation = value

    return _run


def _mutate_user_text_closed_required(
    after: PresenceInteraction,
    _before: PresenceInteraction,
    _ctx: PresenceContext,
    _payload: dict,
) -> None:
    after.expectation = Expectation.required


def _mutate_user_text_closed_clarify(
    after: PresenceInteraction,
    _before: PresenceInteraction,
    _ctx: PresenceContext,
    _payload: dict,
) -> None:
    after.expectation = Expectation.clarify


def _mutate_agent_utterance(
    after: PresenceInteraction,
    _before: PresenceInteraction,
    _ctx: PresenceContext,
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
    after: PresenceInteraction,
    _before: PresenceInteraction,
    _ctx: PresenceContext,
    _payload: dict,
) -> None:
    after.expectation = Expectation.deferred


def _mutate_proactive_open(
    after: PresenceInteraction,
    _before: PresenceInteraction,
    _ctx: PresenceContext,
    payload: dict,
) -> None:
    wait = bool(payload.get("wait_reply", True))
    after.expectation = Expectation.required if wait else Expectation.optional


def _mutate_proactive_delivered(
    after: PresenceInteraction,
    _before: PresenceInteraction,
    _ctx: PresenceContext,
    payload: dict,
) -> None:
    wait = bool(payload.get("wait_reply", True))
    after.expectation = Expectation.required if wait else Expectation.optional


def _mutate_ambiguity_detected(
    after: PresenceInteraction,
    _before: PresenceInteraction,
    _ctx: PresenceContext,
    _payload: dict,
) -> None:
    after.expectation = Expectation.clarify


def _mutate_scene_enter(
    after: PresenceInteraction,
    before: PresenceInteraction,
    _ctx: PresenceContext,
    _payload: dict,
) -> None:
    if before.expectation == Expectation.none:
        after.expectation = Expectation.deferred


PRESENCE_EDGES: tuple[PresenceEdge, ...] = (
    PresenceEdge(
        id="user_text.closed.open.required",
        on=PresenceEventKind.user_text,
        line_open=False,
        guard=lambda _s, _c, p: not _payload_flag(p, "ambiguous"),
        mutate=_mutate_user_text_closed_required,
        note="line opened → expectation required",
    ),
    PresenceEdge(
        id="user_text.closed.open.clarify",
        on=PresenceEventKind.user_text,
        line_open=False,
        guard=lambda _s, _c, p: _payload_flag(p, "ambiguous"),
        mutate=_mutate_user_text_closed_clarify,
        note="line opened → expectation clarify",
    ),
    PresenceEdge(
        id="user_text.clarify.resolved",
        on=PresenceEventKind.user_text,
        expectation=Expectation.clarify,
        guard=lambda _s, _c, p: _payload_flag(p, "resolves_clarify"),
        mutate=_mutate_expectation(Expectation.required),
        note="clarify→required",
    ),
    PresenceEdge(
        id="user_text.open.ambiguous",
        on=PresenceEventKind.user_text,
        line_open=True,
        guard=lambda _s, _c, p: _payload_flag(p, "ambiguous"),
        mutate=_mutate_expectation(Expectation.clarify),
        note="→clarify",
    ),
    PresenceEdge(
        id="user_text.optional.to_required",
        on=PresenceEventKind.user_text,
        expectation=Expectation.optional,
        mutate=_mutate_expectation(Expectation.required),
        note="optional→required",
    ),
    PresenceEdge(
        id="user_text.open.none.to_required",
        on=PresenceEventKind.user_text,
        line_open=True,
        expectation=Expectation.none,
        mutate=_mutate_expectation(Expectation.required),
        note="open line + none→required",
    ),
    PresenceEdge(
        id="user_text.proactive.reply",
        on=PresenceEventKind.user_text,
        guard=lambda _s, c, p: bool(c.proactive_intent_id or p.get("proactive_intent_id")),
        mutate=_mutate_expectation(Expectation.required),
        note="proactive intent answered → required",
    ),
    PresenceEdge(
        id="user_text.noop",
        on=PresenceEventKind.user_text,
        mutate=lambda _a, _b, _c, _p: None,
        note="user_text absorbed",
    ),
    PresenceEdge(
        id="agent_utterance",
        on=PresenceEventKind.agent_utterance,
        mutate=_mutate_agent_utterance,
        note="agent_utterance",
    ),
    PresenceEdge(
        id="agent_deferred",
        on=PresenceEventKind.agent_deferred,
        mutate=_mutate_agent_deferred,
        note="→deferred",
    ),
    PresenceEdge(
        id="proactive_open",
        on=PresenceEventKind.proactive_open,
        mutate=_mutate_proactive_open,
        note="proactive_open",
    ),
    PresenceEdge(
        id="proactive_delivered",
        on=PresenceEventKind.proactive_delivered,
        mutate=_mutate_proactive_delivered,
        note="proactive_delivered",
    ),
    PresenceEdge(
        id="ambiguity_detected",
        on=PresenceEventKind.ambiguity_detected,
        mutate=_mutate_ambiguity_detected,
        note="ambiguity_detected → clarify",
    ),
    PresenceEdge(
        id="clarify_resolved",
        on=PresenceEventKind.clarify_resolved,
        mutate=_mutate_expectation(Expectation.required),
        note="clarify_resolved → required",
    ),
    PresenceEdge(
        id="scene_enter",
        on=PresenceEventKind.scene_enter,
        mutate=_mutate_scene_enter,
        note="scene_enter",
    ),
)


def _edge_matches(
    edge: PresenceEdge,
    before: PresenceInteraction,
    context: PresenceContext,
    event: PresenceEvent,
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


def match_presence_edge(
    before: PresenceInteraction,
    context: PresenceContext,
    event: PresenceEvent,
) -> PresenceEdge | None:
    for edge in PRESENCE_EDGES:
        if _edge_matches(edge, before, context, event):
            return edge
    return None
