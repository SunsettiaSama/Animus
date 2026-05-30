from __future__ import annotations

import os
import random
from collections.abc import Callable
from typing import TYPE_CHECKING

from ..io.outbound.stream import SpeakStreamEvent

if TYPE_CHECKING:
    from ..io.outbound.stream.pipeline import SpeakStreamPipeline

ELLIPSIS_SPEAK = "【......】"
SilencePolicy = str  # "ellipsis" | "hidden"


def _ellipsis_probability() -> float:
    raw = os.environ.get("REACT_SPEAK_SILENCE_ELLIPSIS_PROB", "0.5").strip()
    return min(1.0, max(0.0, float(raw)))


def roll_empty_speak_policy(*, rng: Callable[[], float] = random.random) -> SilencePolicy:
    if rng() < _ellipsis_probability():
        return "ellipsis"
    return "hidden"


def emit_forced_speak(
    pipeline: SpeakStreamPipeline,
    session_id: str,
    text: str,
) -> list[SpeakStreamEvent]:
    from ..io.outbound.stream.parse.tags import SpeakTagBlock

    block = SpeakTagBlock(kind="speak", content=text)
    channels = pipeline._flush_channels()
    return list(channels.tag_dispatch.flush_block(session_id, block))


def apply_empty_speak_policy(
    *,
    session_id: str,
    pipeline: SpeakStreamPipeline,
    stream: bool,
    policy: SilencePolicy | None = None,
    rng: Callable[[], float] = random.random,
) -> tuple[SilencePolicy, str, list[SpeakStreamEvent]]:
    resolved = policy or roll_empty_speak_policy(rng=rng)
    if resolved == "ellipsis":
        events = emit_forced_speak(pipeline, session_id, ELLIPSIS_SPEAK) if stream else []
        return resolved, ELLIPSIS_SPEAK, events
    return resolved, "", []
