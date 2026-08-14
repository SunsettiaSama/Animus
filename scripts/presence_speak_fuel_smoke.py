#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from agent.soul.life.experience.domain.unit import (
    ExperienceAction,
    ExperienceActionKind,
    ExperienceFeeling,
    ExperienceSituation,
    ExperienceUnit,
)
from agent.soul.life.experience.unit_layer.manage.log import ExperienceLog
from agent.soul.presence import PresenceService
from agent.soul.speak.io.inbound.compose import (
    SpeakStatusStore,
    apply_presence_status_update,
    collect_status_injected,
)
from agent.soul.speak.responders.request_driven.orchestrator.blocks.persona import (
    collect_persona_layer,
)


def _persona_snapshot() -> dict:
    return {
        "profile": {
            "name": "Lina",
            "core_traits": ["calm", "careful"],
            "built": True,
            "built_at": "smoke",
        },
        "self_concept": {"narrative": "I accompany the user.", "beliefs": []},
        "attention_keywords": [],
        "persona_distill": {
            "schema_version": 1,
            "source_revision": "smoke|",
            "distilled_at": "2026-01-01T00:00:00+00:00",
            "slices": {
                "general": "Lina is calm and restrained.",
                "dialogue": "You answer gently, with short concrete replies.",
                "story": "No story context.",
                "reasoning": "Listen first, then respond.",
                "memory_anchor": "Keep dialogue clues easy to recall.",
            },
        },
    }


def _unit(*, narration: str, action: ExperienceActionKind, mood: str, salience: float) -> ExperienceUnit:
    return ExperienceUnit.make(
        situation=ExperienceSituation(
            session_id="tao",
            narration=narration,
        ),
        action=ExperienceAction(
            kind=action,
            content=narration,
        ),
        feeling=ExperienceFeeling(
            mood_span=mood,
            linger_days=2.0,
            subjective_narrative=narration,
            salience=salience,
        ),
        source="smoke",
    )


def main() -> None:
    log = ExperienceLog(str(ROOT / "data" / "smoke_presence_fuel"))
    presence = PresenceService()
    llm = MagicMock()
    llm.generate_messages.return_value = (
        "你这两天一直在整理 speak pipeline，仍然保持专注；"
        "刚才你注意到用户在等待对话反馈，所以会更留心下一句话是否能顺利送达。"
    )
    presence.bind_unit_distill_llm(llm)
    units = [
        _unit(
            narration="The agent is organizing the speak pipeline.",
            action=ExperienceActionKind.reasoning,
            mood="You remain focused on the speak pipeline.",
            salience=0.55,
        ),
        _unit(
            narration="The agent notices a user waiting for dialogue feedback.",
            action=ExperienceActionKind.attending,
            mood="You stay attentive to the user's next message.",
            salience=0.45,
        ),
    ]
    for unit in units:
        log.append(unit)
        presence.on_unit_ingested(unit, log)

    snap = presence.snapshot("tao")
    store = SpeakStatusStore()
    apply_presence_status_update(store, snap)
    status = collect_status_injected(presence_snap=snap, status_store=store)
    persona_layer = collect_persona_layer(
        persona_snap=_persona_snapshot(),
        presence_snap=snap,
        status_store=store,
    )

    print("=== speak status.presence ===")
    print(status.presence or "(empty)")
    print("\n=== speak persona.presence ===")
    print(persona_layer.presence or "(empty)")

    if not status.presence.strip():
        raise SystemExit("FAIL: presence status was not injected into speak")
    if "speak pipeline" not in status.presence and "等待对话反馈" not in status.presence:
        raise SystemExit("FAIL: presence status did not include smoke unit fuel")
    if not persona_layer.presence.state.strip():
        raise SystemExit("FAIL: persona presence layer was empty")

    print("\nOK: presence -> speak fuel smoke passed")


if __name__ == "__main__":
    main()
