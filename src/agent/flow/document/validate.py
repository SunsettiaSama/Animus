"""document/validate.py — 使用 base.graph 校验文档 DAG。"""
from __future__ import annotations

import re

from agent.flow.base.graph import has_cycle

from .model import DagPlanDocument

_ID_RE = re.compile(r"^[a-z][a-z0-9_]*$")


def validate_dag_document(doc: DagPlanDocument) -> list[str]:
    """返回人类可读错误列表；空列表表示通过校验。"""
    errors: list[str] = []
    if not doc.title.strip():
        errors.append("title is empty")
    if not doc.objective.strip():
        errors.append("objective is empty")
    if not doc.nodes:
        errors.append("no nodes defined")

    seen: set[str] = set()
    for n in doc.nodes:
        if n.task_id in seen:
            errors.append(f"duplicate task_id: {n.task_id!r}")
        seen.add(n.task_id)
        if not _ID_RE.match(n.task_id):
            errors.append(
                f"task_id {n.task_id!r} must be snake_case "
                "(^[a-z][a-z0-9_]*$)"
            )
        if n.task_id in n.depends_on:
            errors.append(f"task {n.task_id!r} depends_on itself")

    all_ids = {n.task_id for n in doc.nodes}
    for n in doc.nodes:
        for d in n.depends_on:
            if d not in all_ids:
                errors.append(
                    f"task {n.task_id!r} depends_on unknown id {d!r}"
                )

    if errors:
        return errors

    deps_map = {
        n.task_id: frozenset(d for d in n.depends_on if d in all_ids)
        for n in doc.nodes
    }
    if has_cycle(all_ids, deps_map):
        errors.append("dependency cycle detected")

    return errors


def assert_valid_dag_document(doc: DagPlanDocument) -> None:
    errs = validate_dag_document(doc)
    if errs:
        raise ValueError("; ".join(errs))
