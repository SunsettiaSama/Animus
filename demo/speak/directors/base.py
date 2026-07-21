from __future__ import annotations

import json
import re
from typing import Any, Protocol

from ..contracts import ComposeBundle, FilledSegment, RhythmPlan, TextGenerator
from ..stage import DesireArc, StageSnapshot, StageState


class RhythmDirectorPort(Protocol):
    name: str

    def init(
        self,
        stage: StageState,
        *,
        supplier: Any = None,
        reason: str = "cold_init",
        previous: DesireArc | None = None,
    ) -> DesireArc: ...

    def hot_init(
        self,
        stage: StageState,
        *,
        supplier: Any = None,
        reason: str = "hot_init",
    ) -> DesireArc: ...

    def on_scene_due(self, stage: StageState) -> bool: ...

    def affect_due(self, stage: StageState) -> bool: ...

    def refresh_affect(
        self,
        stage: StageState,
        *,
        user_text: str,
        trigger: str,
    ) -> tuple[str, str, float]: ...

    def run(self, snapshot: StageSnapshot) -> RhythmPlan: ...


class ComposeDirectorPort(Protocol):
    name: str

    def run(
        self,
        stage: StageState,
        snapshot: StageSnapshot,
        *,
        rhythm: RhythmPlan,
        share_handoff: Any = None,
    ) -> ComposeBundle: ...


class ReplyDirectorPort(Protocol):
    name: str

    def run(
        self,
        *,
        user_text: str,
        rhythm: RhythmPlan,
        bundle: ComposeBundle,
        scripted_answer: str | None = None,
    ) -> tuple[FilledSegment, ...]: ...


def extract_json_object(raw: str, *, director: str) -> dict[str, Any]:
    text = raw.strip()
    if not text:
        raise ValueError(f"{director}: empty LLM output")
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match is None:
        raise ValueError(f"{director}: no JSON object in output: {raw!r}")
    payload = json.loads(match.group())
    if not isinstance(payload, dict):
        raise ValueError(f"{director}: JSON root must be object")
    return payload


def generate_text(llm: TextGenerator, *, system: str, user: str) -> str:
    return llm.generate(system=system, user=user).strip()
