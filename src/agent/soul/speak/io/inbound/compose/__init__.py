from .block import SpeakStatusInjected
from .collect import collect_status_injected
from .render import render_presence, render_presence_static
from .request import ComposePrepareRequest
from .store import SpeakStatusStore, apply_presence_status_update

__all__ = [
    "ComposePrepareRequest",
    "InboundComposeGateway",
    "SpeakStatusInjected",
    "SpeakStatusStore",
    "apply_presence_status_update",
    "collect_status_injected",
    "render_presence",
    "render_presence_static",
]


def __getattr__(name: str):
    if name == "InboundComposeGateway":
        from .gateway import InboundComposeGateway

        return InboundComposeGateway
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
