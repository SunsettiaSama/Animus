from .actions import SpeakAction
from .inbound import (
    SpeakDialogueBridge,
    SpeakExchange,
    SpeakInboundPort,
    SpeakIngestResult,
    SpeakQuestion,
    ingest_question,
)
from .outbound import (
    SpeakAnswer,
    SpeakDeliverResult,
    SpeakOrchestratorPort,
    SpeakOutboundPort,
    SpeakOutboundRouter,
    SpeakPresenceOutbound,
    SpeakRequest,
    deliver_text,
)

__all__ = [
    "SpeakAction",
    "SpeakAnswer",
    "SpeakDeliverResult",
    "SpeakDialogueBridge",
    "SpeakExchange",
    "SpeakInboundPort",
    "SpeakIngestResult",
    "SpeakOrchestratorPort",
    "SpeakOutboundPort",
    "SpeakOutboundRouter",
    "SpeakPresenceOutbound",
    "SpeakQuestion",
    "SpeakRequest",
    "deliver_text",
    "ingest_question",
]


def __getattr__(name: str):
    if name == "SpeakIOHub":
        from .hub import SpeakIOHub

        return SpeakIOHub
    if name == "SpeakInboundHub":
        from .inbound.hub import SpeakInboundHub

        return SpeakInboundHub
    if name in ("SpeakOutboundHub", "SpeakOutboundStreamHub"):
        from .outbound.hub import SpeakOutboundHub
        from .outbound.stream_hub import SpeakOutboundStreamHub

        return SpeakOutboundStreamHub if name == "SpeakOutboundStreamHub" else SpeakOutboundHub
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
