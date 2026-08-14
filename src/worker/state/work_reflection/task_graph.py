"""Ephemeral task graph used only by the work-reflection sidecar."""
from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Iterable

_FAILED = ("error", "exception", "failed", "traceback", "denied", "错误", "异常", "失败", "拒绝")
_PARTIAL = ("partial", "warning", "incomplete", "部分", "警告", "未完成")


class TaskResultQuality(str, Enum):
    success = "success"
    partial = "partial"
    failed = "failed"


@dataclass
class TaskUnit:
    node_id: str
    title: str
    action: str
    result_summary: str
    quality: TaskResultQuality
    order: int
    archived_count: int = 1


@dataclass(frozen=True, order=True)
class TaskEdge:
    source: str
    target: str


def _clean(value: object, limit: int) -> str:
    text = " ".join(str(value or "").split()).strip()
    return text if len(text) <= limit else text[:limit].rstrip()


def assess_result(observation: str) -> tuple[TaskResultQuality, str]:
    text = _clean(observation, 120)
    lowered = text.lower()
    if not text:
        return TaskResultQuality.partial, "partial：动作没有返回可验证结果"
    if any(marker in lowered for marker in _FAILED):
        return TaskResultQuality.failed, f"failed：{text}"
    if any(marker in lowered for marker in _PARTIAL):
        return TaskResultQuality.partial, f"partial：{text}"
    return TaskResultQuality.success, f"success：{text}"


class TurnTaskGraph:
    """One graph per Worker request; never persisted across turns."""

    def __init__(self, goal: str, *, max_chars: int = 500) -> None:
        if max_chars < 240:
            raise ValueError("task graph max_chars must be at least 240")
        self.max_chars = max_chars
        self._nodes: dict[str, TaskUnit] = {}
        self._edges: set[TaskEdge] = set()
        self._sequence = 0
        root = self._add(
            f"处理用户需求：{_clean(goal, 100)}",
            "receive_requirement",
            "partial：需求已接收，等待执行与验证",
            TaskResultQuality.partial,
        )
        self._root_id = root.node_id
        self._frontier = (root.node_id,)

    @property
    def nodes(self) -> tuple[TaskUnit, ...]:
        return tuple(sorted(self._nodes.values(), key=lambda node: node.order))

    @property
    def edges(self) -> tuple[TaskEdge, ...]:
        return tuple(sorted(self._edges))

    @property
    def core_node_ids(self) -> tuple[str, ...]:
        return self._frontier

    def record_actions(
        self,
        calls: Iterable[dict],
        observations: Iterable[str],
    ) -> None:
        call_items = tuple(calls)
        observation_items = tuple(observations)
        if len(call_items) != len(observation_items):
            raise ValueError(
                "task graph requires one observation per action: "
                f"{len(call_items)} != {len(observation_items)}"
            )
        parents = self._frontier
        created: list[str] = []
        for call, observation in zip(call_items, observation_items):
            action = str(call.get("action") or "unknown_action")
            args = call.get("args") or {}
            keys = ",".join(str(key) for key in list(args)[:3]) if isinstance(args, dict) else ""
            quality, summary = assess_result(observation)
            node = self._add(
                f"执行 {action}" + (f"（{keys}）" if keys else ""),
                action,
                summary,
                quality,
            )
            created.append(node.node_id)
            for parent in parents:
                self._edges.add(TaskEdge(parent, node.node_id))
        if created:
            self._frontier = tuple(created)
        self._distill()

    def record_finish(self, answer: str, *, max_steps: bool = False) -> None:
        if max_steps:
            quality = TaskResultQuality.failed
            summary = "failed：达到最大步骤数，任务未正常完成"
            action = "max_steps"
            title = "任务因步骤耗尽而结束"
        else:
            quality, summary = assess_result(answer)
            action = "finish"
            title = "汇总并交付最终结果"
        node = self._add(title, action, summary, quality)
        for parent in self._frontier:
            self._edges.add(TaskEdge(parent, node.node_id))
        self._frontier = (node.node_id,)
        self._distill()

    def render(self) -> str:
        text = self._render()
        if len(text) > self.max_chars:
            raise RuntimeError(f"task graph exceeds budget: {len(text)}")
        return text

    def _add(
        self,
        title: str,
        action: str,
        summary: str,
        quality: TaskResultQuality,
        *,
        order: int | None = None,
        archived_count: int = 1,
    ) -> TaskUnit:
        self._sequence += 1
        node = TaskUnit(
            node_id=f"t{self._sequence}",
            title=_clean(title, 80),
            action=_clean(action, 60),
            result_summary=_clean(summary, 140),
            quality=quality,
            order=self._sequence if order is None else order,
            archived_count=archived_count,
        )
        self._nodes[node.node_id] = node
        return node

    def _render(self) -> str:
        lines = [
            f"- {n.node_id}|title={n.title}|action={n.action}|result_summary={n.result_summary}"
            for n in self.nodes
        ]
        edges = ",".join(f"{e.source}->{e.target}" for e in self.edges) or "none"
        return f"## 当前临场任务图\ncore={','.join(self._frontier)}\n" + "\n".join(lines) + f"\nedges={edges}"

    def _neighbors(self, node_id: str) -> tuple[str, ...]:
        values: set[str] = set()
        for edge in self._edges:
            if edge.source == node_id:
                values.add(edge.target)
            if edge.target == node_id:
                values.add(edge.source)
        return tuple(sorted(values, key=lambda key: self._nodes[key].order, reverse=True))

    def _recursive_neighborhood(self) -> list[str]:
        visited: set[str] = set()
        result: list[str] = []

        def visit(node_id: str) -> None:
            if node_id in visited:
                return
            visited.add(node_id)
            result.append(node_id)
            for neighbor in self._neighbors(node_id):
                visit(neighbor)

        for core in self._frontier:
            visit(core)
        for node in reversed(self.nodes):
            visit(node.node_id)
        return result

    def _distill(self) -> None:
        while len(self._render()) > self.max_chars and len(self._nodes) > 2:
            protected = set(self._frontier)
            latest_failed = next(
                (n.node_id for n in reversed(self.nodes) if n.quality == TaskResultQuality.failed),
                "",
            )
            if latest_failed:
                protected.add(latest_failed)
            candidates = [
                node_id
                for node_id in reversed(self._recursive_neighborhood())
                if node_id not in protected
            ]
            group = self._connected(candidates, protected)
            if len(group) < 2:
                group = candidates[:2]
            if len(group) < 2:
                break
            self._archive(group)
        if len(self._render()) > self.max_chars:
            for limit in (72, 48, 32, 20):
                for node in self._nodes.values():
                    node.title = _clean(node.title, 36)
                    node.action = _clean(node.action, 24)
                    node.result_summary = _clean(node.result_summary, limit)
                if len(self._render()) <= self.max_chars:
                    return
            raise RuntimeError("task graph cannot fit configured budget")

    def _connected(self, candidates: list[str], protected: set[str]) -> list[str]:
        if not candidates:
            return []
        allowed = set(candidates)
        group: list[str] = []

        def collect(node_id: str) -> None:
            if node_id not in allowed or node_id in protected or node_id in group or len(group) >= 4:
                return
            group.append(node_id)
            for neighbor in self._neighbors(node_id):
                collect(neighbor)

        collect(candidates[0])
        return group

    def _archive(self, node_ids: list[str]) -> None:
        group = set(node_ids)
        units = sorted((self._nodes[key] for key in group), key=lambda node: node.order)
        incoming = {e.source for e in self._edges if e.target in group and e.source not in group}
        outgoing = {e.target for e in self._edges if e.source in group and e.target not in group}
        qualities = {node.quality for node in units}
        quality = (
            TaskResultQuality.failed
            if TaskResultQuality.failed in qualities
            else TaskResultQuality.partial
            if TaskResultQuality.partial in qualities
            else TaskResultQuality.success
        )
        evidence = "；".join(
            re.sub(r"^(success|partial|failed)：", "", node.result_summary)
            for node in units[-2:]
        )
        archive = self._add(
            f"归档并蒸馏 {sum(n.archived_count for n in units)} 个相邻任务单元",
            "distill(" + ",".join(dict.fromkeys(n.action for n in units)) + ")",
            f"{quality.value}：{_clean(evidence, 80)}",
            quality,
            order=min(node.order for node in units),
            archived_count=sum(node.archived_count for node in units),
        )
        self._edges = {e for e in self._edges if e.source not in group and e.target not in group}
        self._edges.update(TaskEdge(source, archive.node_id) for source in incoming)
        self._edges.update(TaskEdge(archive.node_id, target) for target in outgoing)
        for node_id in group:
            self._nodes.pop(node_id)
        if self._root_id in group:
            self._root_id = archive.node_id
