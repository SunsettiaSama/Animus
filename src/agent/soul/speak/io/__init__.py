from __future__ import annotations

import importlib
from typing import Any

from .actions import SpeakAction

_LAZY: dict[str, tuple[str, str]] = {
    "SpeakDialogueBridge": ("agent.soul.speak.io.inbound.bridge", "SpeakDialogueBridge"),
    "SpeakExchange": ("agent.soul.speak.io.inbound.unit", "SpeakExchange"),
    "SpeakInboundPort": ("agent.soul.speak.io.inbound.ports", "SpeakInboundPort"),
    "SpeakIngestResult": ("agent.soul.speak.io.inbound.ingest", "SpeakIngestResult"),
    "SpeakQuestion": ("agent.soul.speak.io.inbound.unit", "SpeakQuestion"),
    "ingest_question": ("agent.soul.speak.io.inbound.ingest", "ingest_question"),
    "SpeakAnswer": ("agent.soul.speak.io.outbound", "SpeakAnswer"),
    "SpeakDeliverResult": ("agent.soul.speak.io.outbound", "SpeakDeliverResult"),
    "SpeakOrchestratorPort": ("agent.soul.speak.io.outbound", "SpeakOrchestratorPort"),
    "SpeakOutboundPort": ("agent.soul.speak.io.outbound", "SpeakOutboundPort"),
    "SpeakOutboundRouter": ("agent.soul.speak.io.outbound", "SpeakOutboundRouter"),
    "SpeakPresenceOutbound": ("agent.soul.speak.io.outbound.delivery", "SpeakPresenceOutbound"),
    "SpeakRequest": ("agent.soul.speak.io.outbound", "SpeakRequest"),
    "deliver_text": ("agent.soul.speak.io.outbound", "deliver_text"),
    "SpeakIOHub": ("agent.soul.speak.io.hub", "SpeakIOHub"),
    "SpeakInboundHub": ("agent.soul.speak.io.inbound.hub", "SpeakInboundHub"),
    "SpeakOutboundHub": ("agent.soul.speak.io.outbound.hub", "SpeakOutboundHub"),
    "SpeakOutboundStreamHub": ("agent.soul.speak.io.outbound.stream_hub", "SpeakOutboundStreamHub"),
}

__all__ = ["SpeakAction", *list(_LAZY)]


def __getattr__(name: str) -> Any:
    spec = _LAZY.get(name)
    if spec is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    mod = importlib.import_module(spec[0])
    return getattr(mod, spec[1])
