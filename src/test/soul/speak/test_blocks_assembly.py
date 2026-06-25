from __future__ import annotations

from agent.soul.speak.pipelines.request_driven.orchestrator.blocks.core.types import (
    VERSIONED_BLOCKS,
    TurnBlockAssembly,
)


def test_turn_block_assembly_ordered_slots():
    assembly = TurnBlockAssembly(session_id="tao", turn_index=2)
    assembly.set_slot("persona", narrative="你是博物学家。", version=1)
    assembly.set_slot("scene", narrative="林间小路。", version=2)
    assembly.set_slot("guidance", narrative="你打算先听再说。", version=3)
    slots = assembly.slots_in_order()
    assert [s.block for s in slots] == list(VERSIONED_BLOCKS)
    assert slots[0].version == 1
    assert slots[2].narrative.startswith("你打算")
    snap = assembly.snapshot()
    assert snap["turn_index"] == 2
    assert len(snap["slots"]) == 3
