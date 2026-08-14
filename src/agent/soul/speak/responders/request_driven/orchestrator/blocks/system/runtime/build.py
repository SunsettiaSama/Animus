from __future__ import annotations

from .layer import SpeakSystemLayer
from .role import SpeakTurnMode, build_role


def build_system_layer(
    *,
    mode: SpeakTurnMode = "inbound",
    output_format: str,
) -> SpeakSystemLayer:
    return SpeakSystemLayer(
        role=build_role(mode),
        output_format=output_format.strip(),
    )
