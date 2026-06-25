#!/usr/bin/env python3
"""???ExperienceUnit ??Presence ?? ??Speak status ???????""

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
    apply_presence_status_update,
    collect_status_injected,
)
from agent.soul.speak.io.inbound.compose.store import SpeakStatusStore
from test.soul.persona.distill_fixtures import persona_snapshot_with_distill

from agent.soul.speak.pipelines.request_driven.orchestrator.persona import collect_persona_layer


def main() -> None:
    log = ExperienceLog(str(ROOT / "data" / "smoke_presence_fuel"))
    units = [
        ExperienceUnit.make(
            situation=ExperienceSituation(
                session_id="tao",
                narration="?????????????????,
            ),
            action=ExperienceAction(
                kind=ExperienceActionKind.reasoning,
                content="????",
            ),
            feeling=ExperienceFeeling(
                mood_span="????????????????",
                linger_days=2.0,
                subjective_narrative="??????????????????,
                salience=0.55,
            ),
            source="narrative",
        ),
        ExperienceUnit.make(
            situation=ExperienceSituation(
                session_id="tao",
                narration="????????????????,
            ),
            action=ExperienceAction(
                kind=ExperienceActionKind.attending,
                content="????",
            ),
            feeling=ExperienceFeeling(salience=0.4),
            source="narrative",
        ),
    ]
    for u in units:
        log.append(u)

    llm = MagicMock()
    llm.generate_messages.return_value = (
        "??????????????????????????????????
        "??????????????????????????
    )

    presence = PresenceService()
    presence.bind_unit_distill_llm(llm)
    for u in units:
        presence.on_unit_ingested(u, log)

    snap = presence.snapshot("tao")
    store = SpeakStatusStore()
    apply_presence_status_update(store, snap)

    persona_snap = persona_snapshot_with_distill(name="????)
    persona_layer = collect_persona_layer(
        persona_snap=persona_snap,
        presence_snap=snap,
        user_text="",
        status_store=store,
    )
    status = collect_status_injected(presence_snap=snap, status_store=store)

    print("=== recent_portrait ===")
    print(snap.state.recent_portrait.narrative)
    print("\n=== speak persona.presence ===")
    print(persona_layer.presence)
    print("\n=== system blocks ===")
    for block in persona_layer.render_blocks():
        print(block)
        print("---")

    forbidden = ("????, "????, "????????)
    for marker in forbidden:
        if marker in status.presence:
            raise SystemExit(f"FAIL: presence ??????{marker!r}")
    if status.presence and "?? not in status.presence[:120]:
        raise SystemExit("FAIL: presence ????????????)
    print("\nOK: presence ?????????")


if __name__ == "__main__":
    main()
