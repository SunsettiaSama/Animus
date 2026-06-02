from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
_SLOTS_PATH = _ROOT / "agent" / "soul" / "speak" / "orchestrator" / "compose_slots.py"

_spec = importlib.util.spec_from_file_location("compose_slots", _SLOTS_PATH)
_mod = importlib.util.module_from_spec(_spec)
sys.modules["compose_slots"] = _mod
assert _spec.loader is not None
_spec.loader.exec_module(_mod)

TurnComposeAssembly = _mod.TurnComposeAssembly
KNOWN_COMPOSE_BLOCKS = _mod.KNOWN_COMPOSE_BLOCKS


def test_turn_compose_assembly_ordered_slots():
    assembly = TurnComposeAssembly(session_id="tao", turn_index=2)
    assembly.set_slot("persona", narrative="你是博物学家。", version=1)
    assembly.set_slot("scene", narrative="林间小路。", version=2)
    assembly.set_slot("guidance", narrative="你打算先听再说。", version=3)
    slots = assembly.slots_in_order()
    assert [s.block for s in slots] == list(KNOWN_COMPOSE_BLOCKS)
    assert slots[0].version == 1
    assert slots[2].narrative.startswith("你打算")
    snap = assembly.snapshot()
    assert snap["turn_index"] == 2
    assert len(snap["slots"]) == 3
