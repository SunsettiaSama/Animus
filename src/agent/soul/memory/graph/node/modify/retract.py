from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agent.soul.memory.graph.node_store import GraphNodeStore
    from agent.soul.memory.ports import VectorIndexPort

from agent.soul.memory.graph.node.maintain.vectors import remove_node


def retract_by_life_event(
    nodes: GraphNodeStore,
    life_event_id: str,
    *,
    vectors: VectorIndexPort | None = None,
) -> bool:
    if not life_event_id:
        return False
    unit = nodes.get_by_life_event_id(life_event_id)
    if unit is None:
        return False
    nodes.archive(unit.id)
    if vectors is not None:
        remove_node(vectors, unit.id)
    return True
