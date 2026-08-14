from __future__ import annotations

from collections.abc import Callable

from ..contracts import RhythmPlan
from ..snapshot import RhythmSnapshot
from .json_util import extract_json_object
from .parse import plan_from_payload
from .prompts import RHYTHM_SYSTEM

DirectorGenerateFn = Callable[[str, str], str]


class RhythmDirector:
    """Decide gate / share / reply_guide; never writes character dialogue."""

    name = "rhythm"

    def __init__(self, generate_json: DirectorGenerateFn) -> None:
        self._generate_json = generate_json

    def run(self, snapshot: RhythmSnapshot) -> RhythmPlan:
        raw = self._generate_json(RHYTHM_SYSTEM, snapshot.prompt_lines())
        payload = extract_json_object(raw, director=self.name)
        return plan_from_payload(payload)
