"""document/markdown.py — DAG 计划文档的 Markdown 序列化（扁平 Tasks）。"""
from __future__ import annotations

import re
import uuid

from agent.flow.base.types import NodeStatus

from .model import DagDocNode, DagPlanDocument


# Word 等环境中常见「无 Markdown 粗体标记」的任务行：`- [ ] task_id …`
_TASK_LINE = re.compile(
    r"^-\s*(\[[xX\-~!> ]\])\s+"
    r"(?:\*\*([a-zA-Z0-9_]+)\*\*|([a-zA-Z0-9_]+))"
    r"\s*(.*?)$"
)
_ANNOTATION = re.compile(r"`([^:`]+):([^`]*)`")


class DagMarkdownParseError(ValueError):
    pass


class DagMarkdownIO:
    """与 cluster 任务行语法对齐的结构（扁平 ## Tasks），便于人工编辑 DAG。"""

    _STATUS_MARK: dict[NodeStatus, str] = {
        NodeStatus.pending: "[ ]",
        NodeStatus.running: "[>]",
        NodeStatus.done: "[x]",
        NodeStatus.failed: "[!]",
        NodeStatus.skipped: "[-]",
        NodeStatus.paused: "[~]",
    }

    _MARK_STATUS: dict[str, NodeStatus] = {
        "[ ]": NodeStatus.pending,
        "[x]": NodeStatus.done,
        "[X]": NodeStatus.done,
        "[-]": NodeStatus.skipped,
        "[~]": NodeStatus.paused,
        "[!]": NodeStatus.failed,
        "[>]": NodeStatus.running,
    }

    @classmethod
    def to_markdown(cls, doc: DagPlanDocument) -> str:
        lines: list[str] = [
            f"# Plan: {doc.title}",
            "",
            "## Objective",
            doc.objective,
            "",
            "## Tasks",
            "",
        ]
        for n in doc.nodes:
            annotations: list[str] = []
            if n.depends_on:
                annotations.append(f"`depends_on:{','.join(n.depends_on)}`")
            if n.tool_package:
                annotations.append(f"`tool:{n.tool_package}`")
            if n.max_steps is not None:
                annotations.append(f"`max_steps:{n.max_steps}`")
            if n.system_note:
                annotations.append(f"`note:{n.system_note}`")
            for k, v in sorted(n.tags.items()):
                if k.startswith("_"):
                    continue
                annotations.append(f"`tag:{k}={v}`")
            ann_str = (" " + " ".join(annotations)) if annotations else ""
            mark = cls._STATUS_MARK[NodeStatus.pending]
            lines.append(f"- {mark} **{n.task_id}**{ann_str}")
            desc = n.description.strip()
            if desc:
                for part in desc.splitlines():
                    lines.append(f"  {part}")
            lines.append("")
        return "\n".join(lines).rstrip() + "\n"

    @classmethod
    def from_markdown(cls, text: str, *, strict: bool = True) -> DagPlanDocument:
        lines = text.splitlines()
        title = ""
        objective_lines: list[str] = []
        nodes: list[DagDocNode] = []
        section: str | None = None
        last_idx: int | None = None

        for raw in lines:
            line = raw.rstrip()

            if line.startswith("# Plan:"):
                title = line[len("# Plan:") :].strip()
                section = None
                continue

            if line.startswith("## "):
                h = line[3:].strip().lower()
                if h == "objective":
                    section = "objective"
                elif h == "tasks":
                    section = "tasks"
                else:
                    section = None
                last_idx = None
                continue

            if section == "objective":
                if line:
                    objective_lines.append(line)
                continue

            if section == "tasks":
                m = _TASK_LINE.match(line)
                if m:
                    mark_str = m.group(1)
                    task_id = m.group(2) or m.group(3)
                    ann_str = m.group(4) or ""
                    inner = mark_str[1:-1]
                    status_key = f"[{inner}]"
                    _ = cls._MARK_STATUS.get(status_key, NodeStatus.pending)

                    annotations = list(_ANNOTATION.findall(ann_str))
                    ann_map: dict[str, str] = {}
                    tag_vals: list[str] = []
                    for k, v in annotations:
                        if k == "tag":
                            tag_vals.append(v)
                        else:
                            ann_map[k] = v

                    depends_raw = ann_map.get("depends_on", "")
                    depends_on = tuple(
                        d.strip() for d in depends_raw.split(",") if d.strip()
                    )
                    tool = ann_map.get("tool") or None
                    profile = ann_map.get("profile")
                    if tool is None and profile not in (None, "", "minimal"):
                        tool = profile
                    max_steps_raw = ann_map.get("max_steps")
                    max_steps = int(max_steps_raw) if max_steps_raw else None
                    system_note = ann_map.get("note", "")
                    tags: dict[str, str] = {}
                    for tv in tag_vals:
                        if "=" not in tv:
                            continue
                        a, b = tv.split("=", 1)
                        ka, kb = a.strip(), b.strip()
                        if ka:
                            tags[ka] = kb

                    node = DagDocNode(
                        task_id=task_id,
                        description="",
                        depends_on=depends_on,
                        tool_package=tool,
                        max_steps=max_steps,
                        system_note=system_note,
                        tags=tags,
                    )
                    nodes.append(node)
                    last_idx = len(nodes) - 1
                    continue

                if (
                    last_idx is not None
                    and line.startswith("  ")
                    and line.strip()
                ):
                    prev = nodes[last_idx]
                    content = line[2:]
                    sep = " " if prev.description else ""
                    nodes[last_idx] = DagDocNode(
                        task_id=prev.task_id,
                        description=prev.description + sep + content,
                        depends_on=prev.depends_on,
                        tool_package=prev.tool_package,
                        max_steps=prev.max_steps,
                        system_note=prev.system_note,
                        tags=prev.tags,
                    )
                    continue

        objective = " ".join(objective_lines).strip()
        if strict and not objective:
            raise DagMarkdownParseError("missing or empty ## Objective section")
        if strict and not nodes:
            raise DagMarkdownParseError(
                "no tasks found under ## Tasks (expected checklist lines)"
            )

        plan_id = str(uuid.uuid4())
        return DagPlanDocument(
            title=title or "Untitled Plan",
            objective=objective,
            nodes=nodes,
            plan_id=plan_id,
        )
