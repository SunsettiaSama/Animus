from __future__ import annotations

import importlib
from typing import Any

_LAZY: dict[str, tuple[str, str]] = {
    "SpeakDialogueBridge": (".bridge", "SpeakDialogueBridge"),
    "SpeakIngestResult": (".ingest", "SpeakIngestResult"),
    "ingest_question": (".ingest", "ingest_question"),
    "SpeakInboundPort": (".ports", "SpeakInboundPort"),
    "SpeakExchange": (".unit", "SpeakExchange"),
    "SpeakQuestion": (".unit", "SpeakQuestion"),
    "InboundComposeGateway": (".compose.gateway", "InboundComposeGateway"),
}

__all__ = list(_LAZY)


def __getattr__(name: str) -> Any:
    spec = _LAZY.get(name)
    if spec is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    mod = importlib.import_module(spec[0], __name__)
    return getattr(mod, spec[1])
