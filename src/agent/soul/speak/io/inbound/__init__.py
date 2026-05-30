from .bridge import SpeakDialogueBridge
from .ingest import SpeakIngestResult, ingest_question
from .ports import SpeakInboundPort
from .unit import SpeakExchange, SpeakQuestion

__all__ = [
    "SpeakDialogueBridge",
    "SpeakExchange",
    "SpeakInboundPort",
    "SpeakIngestResult",
    "SpeakQuestion",
    "ingest_question",
]


def __getattr__(name: str):
    if name == "InboundComposeGateway":
        from .compose import InboundComposeGateway

        return InboundComposeGateway
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
