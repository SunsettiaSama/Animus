"""store 包装：在 node/edge store 的写入收口发事件（R1.1 node/edge/recall/forget）。

为什么选 store 层而不是五个建边调用点：所有建边路径（归档选父、episode 子图、
叙事编织、反刍、社交合并）最终都经过 ``GraphEdgeStore.put``；节点首写、
``on_recall`` 强化、``forget_scan`` 同理收口在 node store。包装器对 JSON 与
MySQL 后端行为一致（PRD R5.2 用伪造 store 断言事件完备性）。
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from agent.soul.memory.telemetry import emit_event
from agent.soul.memory.telemetry import events as ev

if TYPE_CHECKING:
    from agent.soul.memory.graph.node_store import GraphNodeStore
    from agent.soul.memory.ports import GraphEdgeStore


class TelemetryNodeStore:
    """GraphNodeStore 包装：node_created / recall_recorded / node_forgotten。

    仅包装写入与计数面；读方法（get/list_*/query_*）原样转发。
    ``put`` 前先探测存在性以区分首写与更新（更新不发事件——反刍改写/合并
    走各自业务事件，避免同一动作双计）。
    """

    def __init__(self, inner: GraphNodeStore) -> None:
        self._inner = inner

    @property
    def inner(self) -> GraphNodeStore:
        return self._inner

    def put(self, node: Any) -> None:
        try:
            existed = self._inner.get(node.id) is not None
        except Exception:
            existed = True  # 探测失败宁可漏发事件也不误报创建
        self._inner.put(node)
        if not existed:
            network = getattr(getattr(node, "network", None), "value", None) or ""
            tier = getattr(getattr(node, "tier", None), "value", None) or ""
            meta = getattr(node, "meta", None) or {}
            emit_event(
                ev.NODE_CREATED,
                node_id=str(node.id),
                network=str(network),
                node_type=str(getattr(node, "MEMORY_TYPE", "")),
                tier=str(tier),
                interactor_id=str(getattr(node, "interactor_id", "") or ""),
                life_event_id=str((meta or {}).get("life_event_id", "") or ""),
                focus=str(getattr(node, "focus", "") or "")[:80],
            )

    def on_recall(self, node_id: str) -> None:
        self._inner.on_recall(node_id)
        emit_event(ev.RECALL_RECORDED, node_id=str(node_id))

    def forget_scan(self, **kwargs) -> list[str]:
        archived = self._inner.forget_scan(**kwargs)
        dry_run = bool(kwargs.get("dry_run", False))
        if archived and not dry_run:
            emit_event(
                ev.NODE_FORGOTTEN,
                node_ids=archived,
                count=len(archived),
                network=str(getattr(kwargs.get("network"), "value", None) or kwargs.get("network") or ""),
            )
        return archived

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


class TelemetryEdgeStore:
    """GraphEdgeStore 包装：edge_added（全部建边路径的收口）。"""

    def __init__(self, inner: GraphEdgeStore) -> None:
        self._inner = inner

    @property
    def inner(self) -> GraphEdgeStore:
        return self._inner

    def put(self, edge: Any) -> None:
        self._inner.put(edge)
        edge_type = getattr(getattr(edge, "edge_type", None), "value", None) or str(
            getattr(edge, "edge_type", "")
        )
        emit_event(
            ev.EDGE_ADDED,
            edge_id=str(edge.id),
            edge_type=str(edge_type),
            from_id=str(edge.from_id),
            to_id=str(edge.to_id),
            weight=float(getattr(edge, "weight", 1.0) or 1.0),
        )

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


def wrap_stores(nodes: GraphNodeStore, edges: GraphEdgeStore | None):
    """按 telemetry 开关包装（关闭时原样返回，零包装、零对象）。"""
    from agent.soul.memory.telemetry import get_memory_telemetry

    if get_memory_telemetry() is None:
        return nodes, edges
    wrapped_nodes: GraphNodeStore = TelemetryNodeStore(nodes)  # type: ignore[assignment]
    wrapped_edges = TelemetryEdgeStore(edges) if edges is not None else None  # type: ignore[assignment]
    return wrapped_nodes, wrapped_edges
