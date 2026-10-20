"""R5.2 事件完备性：store 收口（node_created / edge_added / recall_recorded / node_forgotten）。"""
from __future__ import annotations

from agent.soul.memory.domain import EdgeType, MemoryEdge, MemoryNetwork
from agent.soul.memory.graph.networks.event.node import FactualMemory
from agent.soul.memory.telemetry import events as ev
from agent.soul.memory.telemetry.store_hooks import TelemetryEdgeStore, TelemetryNodeStore

from .conftest import events_of, read_events


class _FakeNodeStore:
    def __init__(self):
        self.rows: dict[str, FactualMemory] = {}
        self.archived: list[str] = []

    def put(self, node):
        self.rows[node.id] = node

    def get(self, node_id):
        return self.rows.get(node_id)

    def on_recall(self, node_id):
        if node_id in self.rows:
            self.rows[node_id].recall_count += 1

    def forget_scan(self, *, threshold=0.05, half_life_days=30.0, dry_run=False, network=None):
        ids = [nid for nid, n in self.rows.items() if n.base_activation < threshold]
        if not dry_run:
            self.archived.extend(ids)
        return ids


def _node(node_id="n1", activation=0.5):
    return FactualMemory(
        id=node_id, focus="测试", fact="事实", base_activation=activation,
        meta={"life_event_id": "exp-1"},
    )


def test_first_put_emits_node_created(telemetry):
    inner = _FakeNodeStore()
    wrapped = TelemetryNodeStore(inner)
    wrapped.put(_node())
    [created] = events_of(read_events(telemetry), ev.NODE_CREATED)
    assert created["node_id"] == "n1"
    assert created["network"] == MemoryNetwork.event.value
    assert created["node_type"] == "factual"
    assert created["tier"] == "short_term"
    assert created["life_event_id"] == "exp-1"


def test_update_put_does_not_reemit_node_created(telemetry):
    inner = _FakeNodeStore()
    wrapped = TelemetryNodeStore(inner)
    node = _node()
    wrapped.put(node)
    node.focus = "改写后"
    wrapped.put(node)  # 反刍改写等更新路径
    assert len(events_of(read_events(telemetry), ev.NODE_CREATED)) == 1


def test_on_recall_emits_recall_recorded(telemetry):
    inner = _FakeNodeStore()
    wrapped = TelemetryNodeStore(inner)
    wrapped.put(_node())
    wrapped.on_recall("n1")
    [recall] = events_of(read_events(telemetry), ev.RECALL_RECORDED)
    assert recall["node_id"] == "n1"
    assert inner.rows["n1"].recall_count == 1, "强化记账本身不受观测影响"


def test_forget_scan_emits_node_forgotten_only_when_not_dry_run(telemetry):
    inner = _FakeNodeStore()
    wrapped = TelemetryNodeStore(inner)
    wrapped.put(_node("low", activation=0.01))

    ids = wrapped.forget_scan(threshold=0.05, half_life_days=30.0, dry_run=True)
    assert ids == ["low"]
    assert not events_of(read_events(telemetry), ev.NODE_FORGOTTEN), "dry_run 不发事件"

    ids = wrapped.forget_scan(threshold=0.05, half_life_days=30.0, dry_run=False)
    assert ids == ["low"]
    [forgotten] = events_of(read_events(telemetry), ev.NODE_FORGOTTEN)
    assert forgotten["node_ids"] == ["low"]
    assert forgotten["count"] == 1


def test_edge_put_emits_edge_added(telemetry):
    class _FakeEdgeStore:
        def __init__(self):
            self.edges: dict[str, MemoryEdge] = {}

        def put(self, edge):
            self.edges[edge.id] = edge

    inner = _FakeEdgeStore()
    wrapped = TelemetryEdgeStore(inner)
    edge = MemoryEdge(from_id="parent", to_id="child", edge_type=EdgeType.related_to, weight=0.8)
    wrapped.put(edge)
    [added] = events_of(read_events(telemetry), ev.EDGE_ADDED)
    assert added["edge_type"] == "related_to"
    assert added["from_id"] == "parent"
    assert added["to_id"] == "child"
    assert abs(added["weight"] - 0.8) < 1e-9


def test_wrapper_forwards_reads_to_inner(telemetry):
    inner = _FakeNodeStore()
    wrapped = TelemetryNodeStore(inner)
    wrapped.put(_node())
    assert wrapped.get("n1") is inner.rows["n1"]
    assert wrapped.get("missing") is None
    assert wrapped.inner is inner
