from __future__ import annotations

import asyncio
import re
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


# ── Enums ─────────────────────────────────────────────────────────────────────

class TaskStatus(str, Enum):
    pending  = "pending"
    running  = "running"
    done     = "done"
    failed   = "failed"
    skipped  = "skipped"
    paused   = "paused"


# ── Dataclasses ───────────────────────────────────────────────────────────────

@dataclass
class TaskExecutionContext:
    task_id: str
    status: str
    result_summary: str = ""
    step_count: int = 0
    error: str | None = None
    last_steps: list[str] = field(default_factory=list)
    retry_count: int = 0

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "status": self.status,
            "result_summary": self.result_summary,
            "step_count": self.step_count,
            "error": self.error,
            "last_steps": self.last_steps,
            "retry_count": self.retry_count,
        }

    @classmethod
    def from_dict(cls, d: dict) -> TaskExecutionContext:
        return cls(**d)


@dataclass
class PlanTask:
    task_id: str
    description: str
    module: str = ""
    profile: str = "minimal"
    max_steps: int | None = None
    depends_on: list[str] = field(default_factory=list)
    writes: list[str] = field(default_factory=list)
    parallel: bool = False
    status: TaskStatus = TaskStatus.pending
    result: str | None = None
    error: str | None = None
    params: dict = field(default_factory=dict)
    execution_ctx: TaskExecutionContext | None = None

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "description": self.description,
            "module": self.module,
            "profile": self.profile,
            "max_steps": self.max_steps,
            "depends_on": list(self.depends_on),
            "writes": list(self.writes),
            "parallel": self.parallel,
            "status": self.status.value,
            "result": self.result,
            "error": self.error,
            "params": dict(self.params),
            "execution_ctx": self.execution_ctx.to_dict() if self.execution_ctx else None,
        }

    @classmethod
    def from_dict(cls, d: dict) -> PlanTask:
        d = dict(d)
        d["status"] = TaskStatus(d.get("status", "pending"))
        d.setdefault("writes", [])
        ctx = d.pop("execution_ctx", None)
        obj = cls(**d)
        if ctx:
            obj.execution_ctx = TaskExecutionContext.from_dict(ctx)
        return obj


@dataclass
class PlanModule:
    name: str
    tasks: list[PlanTask] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"name": self.name, "tasks": [t.to_dict() for t in self.tasks]}

    @classmethod
    def from_dict(cls, d: dict) -> PlanModule:
        return cls(
            name=d["name"],
            tasks=[PlanTask.from_dict(t) for t in d.get("tasks", [])],
        )


@dataclass
class PlanMetadata:
    max_replan_cycles: int = 3
    checkpoint: str = "per_module"
    timeout: float | None = None
    paused: bool = False

    def to_dict(self) -> dict:
        return {
            "max_replan_cycles": self.max_replan_cycles,
            "checkpoint": self.checkpoint,
            "timeout": self.timeout,
            "paused": self.paused,
        }

    @classmethod
    def from_dict(cls, d: dict) -> PlanMetadata:
        return cls(**d)


# ── PlanDocument ──────────────────────────────────────────────────────────────

class PlanDocument:
    def __init__(
        self,
        plan_id: str,
        title: str,
        objective: str,
        modules: list[PlanModule],
        metadata: PlanMetadata | None = None,
        replan_notes: list[str] | None = None,
        conclusion: str | None = None,
    ) -> None:
        self.plan_id = plan_id
        self.title = title
        self.objective = objective
        self.modules = modules
        self.metadata = metadata or PlanMetadata()
        self.replan_notes: list[str] = replan_notes or []
        self.conclusion: str | None = conclusion
        self._lock = asyncio.Lock()
        # Set when plan is running / not paused; cleared when paused.
        self._resume_event: asyncio.Event = asyncio.Event()
        self._resume_event.set()

    # ── Task access ──────────────────────────────────────────────────────────

    def all_tasks(self) -> list[PlanTask]:
        return [t for m in self.modules for t in m.tasks]

    def get_task(self, task_id: str) -> PlanTask:
        for t in self.all_tasks():
            if t.task_id == task_id:
                return t
        raise KeyError(f"task_id not found: {task_id!r}")

    def get_module(self, module_name: str) -> PlanModule | None:
        for m in self.modules:
            if m.name == module_name:
                return m
        return None

    def get_ready_tasks(self) -> list[PlanTask]:
        done_ids = {
            t.task_id for t in self.all_tasks()
            if t.status in (TaskStatus.done, TaskStatus.skipped)
        }
        return [
            t for t in self.all_tasks()
            if t.status == TaskStatus.pending
            and all(dep in done_ids for dep in t.depends_on)
        ]

    def compute_dag_width(self) -> int:
        """BFS topological layering; returns the maximum single-wave concurrency width."""
        tasks = self.all_tasks()
        if not tasks:
            return 1
        in_degree: dict[str, int] = {t.task_id: 0 for t in tasks}
        children: dict[str, list[str]] = {t.task_id: [] for t in tasks}
        all_ids = {t.task_id for t in tasks}
        for t in tasks:
            for dep in t.depends_on:
                if dep in all_ids:
                    in_degree[t.task_id] += 1
                    children[dep].append(t.task_id)
        queue = [tid for tid, deg in in_degree.items() if deg == 0]
        max_width = max(len(queue), 1)
        while queue:
            next_wave: list[str] = []
            for tid in queue:
                for child in children[tid]:
                    in_degree[child] -= 1
                    if in_degree[child] == 0:
                        next_wave.append(child)
            if next_wave:
                max_width = max(max_width, len(next_wave))
            queue = next_wave
        return max_width

    def is_complete(self) -> bool:
        return all(
            t.status in (TaskStatus.done, TaskStatus.skipped, TaskStatus.failed)
            for t in self.all_tasks()
        )

    # ── State mutation (async, thread-safe) ──────────────────────────────────

    async def update_task(self, task_id: str, **updates: Any) -> None:
        async with self._lock:
            task = self.get_task(task_id)
            for k, v in updates.items():
                setattr(task, k, v)

    def skip(self, task_id: str, cascade: bool = False) -> None:
        task = self.get_task(task_id)
        task.status = TaskStatus.skipped
        if cascade:
            skipped = {task_id}
            changed = True
            while changed:
                changed = False
                for t in self.all_tasks():
                    if t.status == TaskStatus.pending and any(
                        dep in skipped for dep in t.depends_on
                    ):
                        t.status = TaskStatus.skipped
                        skipped.add(t.task_id)
                        changed = True

    def pause(self) -> None:
        self.metadata.paused = True
        self._resume_event.clear()

    def resume(self) -> None:
        self.metadata.paused = False
        self._resume_event.set()

    def set_params(self, task_id: str, **overrides: Any) -> None:
        task = self.get_task(task_id)
        task.params.update(overrides)
        if "profile" in overrides:
            task.profile = overrides["profile"]
        if "max_steps" in overrides:
            task.max_steps = overrides["max_steps"]

    # ── Serialisation ────────────────────────────────────────────────────────

    def to_dict(self) -> dict:
        return {
            "plan_id": self.plan_id,
            "title": self.title,
            "objective": self.objective,
            "modules": [m.to_dict() for m in self.modules],
            "metadata": self.metadata.to_dict(),
            "replan_notes": list(self.replan_notes),
            "conclusion": self.conclusion,
        }

    @classmethod
    def from_dict(cls, d: dict) -> PlanDocument:
        return cls(
            plan_id=d["plan_id"],
            title=d["title"],
            objective=d["objective"],
            modules=[PlanModule.from_dict(m) for m in d.get("modules", [])],
            metadata=PlanMetadata.from_dict(d.get("metadata", {})),
            replan_notes=d.get("replan_notes", []),
            conclusion=d.get("conclusion"),
        )

    # ── Markdown ─────────────────────────────────────────────────────────────

    _STATUS_MARK: dict[TaskStatus, str] = {
        TaskStatus.pending:  "[ ]",
        TaskStatus.running:  "[>]",
        TaskStatus.done:     "[x]",
        TaskStatus.failed:   "[!]",
        TaskStatus.skipped:  "[-]",
        TaskStatus.paused:   "[~]",
    }

    _MARK_STATUS: dict[str, TaskStatus] = {v: k for k, v in _STATUS_MARK.items()}

    def to_markdown(self) -> str:
        lines: list[str] = [f"# Plan: {self.title}", "", "## Objective", self.objective, ""]

        if self.metadata.timeout or self.metadata.max_replan_cycles != 3:
            lines += ["## Metadata"]
            if self.metadata.max_replan_cycles != 3:
                lines.append(f"max_replan_cycles: {self.metadata.max_replan_cycles}")
            if self.metadata.timeout:
                lines.append(f"timeout: {self.metadata.timeout}")
            if self.metadata.paused:
                lines.append("paused: true")
            lines.append("")

        lines.append("## Tasks")
        lines.append("")
        for module in self.modules:
            lines.append(f"### Module: {module.name}")
            for task in module.tasks:
                mark = self._STATUS_MARK.get(task.status, "[ ]")
                annotations: list[str] = [f"`profile:{task.profile}`"]
                if task.max_steps is not None:
                    annotations.append(f"`max_steps:{task.max_steps}`")
                if task.depends_on:
                    annotations.append(f"`depends_on:{','.join(task.depends_on)}`")
                if task.writes:
                    annotations.append(f"`writes:{','.join(task.writes)}`")
                if task.parallel:
                    annotations.append("`parallel:true`")
                ann_str = " ".join(annotations)
                lines.append(f"- {mark} **{task.task_id}** {ann_str}")
                lines.append(f"  {task.description}")
                if task.result:
                    lines.append(f"  > Result: {task.result[:200]}")
                if task.error:
                    lines.append(f"  > Error: {task.error[:200]}")
            lines.append("")

        if self.replan_notes:
            lines += ["## Replan Notes", ""]
            for note in self.replan_notes:
                lines.append(f"- {note}")
            lines.append("")

        if self.conclusion:
            lines += ["## Conclusion", self.conclusion, ""]

        return "\n".join(lines)

    @classmethod
    def from_markdown(cls, text: str) -> PlanDocument:
        return PlanParser.parse(text)


# ── PlanParser ────────────────────────────────────────────────────────────────

_TASK_LINE = re.compile(
    r"^-\s*(\[[x\-~!> ]\])\s+\*\*([a-zA-Z0-9_]+)\*\*\s*(.*?)$"
)
_ANNOTATION = re.compile(r"`([^:`]+):([^`]*)`")
_STATUS_MAP: dict[str, TaskStatus] = {
    "[ ]": TaskStatus.pending,
    "[x]": TaskStatus.done,
    "[X]": TaskStatus.done,
    "[-]": TaskStatus.skipped,
    "[~]": TaskStatus.paused,
    "[!]": TaskStatus.failed,
    "[>]": TaskStatus.running,
}


class PlanParseError(ValueError):
    pass


class PlanParser:
    @staticmethod
    def parse(text: str, strict: bool = True) -> PlanDocument:
        lines = text.splitlines()
        plan_id = str(uuid.uuid4())
        title = ""
        objective_lines: list[str] = []
        metadata_lines: list[str] = []
        modules: list[PlanModule] = []
        replan_notes: list[str] = []
        conclusion_lines: list[str] = []

        section = None
        current_module: PlanModule | None = None
        last_task: PlanTask | None = None

        for raw in lines:
            line = raw.rstrip()

            # Top-level heading → title
            if line.startswith("# Plan:"):
                title = line[len("# Plan:"):].strip()
                section = None
                continue

            # H2 sections
            if line.startswith("## "):
                heading = line[3:].strip().lower()
                if heading == "objective":
                    section = "objective"
                elif heading == "metadata":
                    section = "metadata"
                elif heading == "tasks":
                    section = "tasks"
                    current_module = None
                elif heading == "replan notes":
                    section = "replan_notes"
                elif heading == "conclusion":
                    section = "conclusion"
                else:
                    section = None
                last_task = None
                continue

            # H3 → module
            if section == "tasks" and line.startswith("### Module:"):
                name = line[len("### Module:"):].strip()
                current_module = PlanModule(name=name)
                modules.append(current_module)
                last_task = None
                continue

            if section == "objective":
                if line:
                    objective_lines.append(line)
                continue

            if section == "metadata":
                if line:
                    metadata_lines.append(line)
                continue

            if section == "replan_notes":
                if line.startswith("- "):
                    replan_notes.append(line[2:])
                continue

            if section == "conclusion":
                if line:
                    conclusion_lines.append(line)
                continue

            if section == "tasks":
                m = _TASK_LINE.match(line)
                if m:
                    mark_str, task_id, ann_str = m.group(1), m.group(2), m.group(3)
                    status = _STATUS_MAP.get(f"[{mark_str[1]}]", TaskStatus.pending)
                    annotations = dict(_ANNOTATION.findall(ann_str))
                    profile = annotations.get("profile", "minimal")
                    max_steps_raw = annotations.get("max_steps")
                    max_steps = int(max_steps_raw) if max_steps_raw else None
                    depends_raw = annotations.get("depends_on", "")
                    depends_on = [d.strip() for d in depends_raw.split(",") if d.strip()]
                    writes_raw = annotations.get("writes", "")
                    writes = [w.strip() for w in writes_raw.split(",") if w.strip()]
                    parallel = annotations.get("parallel", "false").lower() == "true"

                    if current_module is None:
                        current_module = PlanModule(name="Default")
                        modules.append(current_module)

                    task = PlanTask(
                        task_id=task_id,
                        description="",
                        module=current_module.name,
                        profile=profile,
                        max_steps=max_steps,
                        depends_on=depends_on,
                        writes=writes,
                        parallel=parallel,
                        status=status,
                    )
                    current_module.tasks.append(task)
                    last_task = task
                    continue

                # Description / result continuation lines
                if last_task is not None and line.startswith("  "):
                    content = line[2:]
                    if content.startswith("> Result:"):
                        last_task.result = content[len("> Result:"):].strip()
                    elif content.startswith("> Error:"):
                        last_task.error = content[len("> Error:"):].strip()
                    elif content:
                        sep = " " if last_task.description else ""
                        last_task.description += sep + content
                    continue

        # Parse metadata block
        metadata = PlanMetadata()
        for mline in metadata_lines:
            if ":" in mline:
                k, _, v = mline.partition(":")
                k, v = k.strip(), v.strip()
                if k == "max_replan_cycles":
                    metadata.max_replan_cycles = int(v)
                elif k == "timeout":
                    metadata.timeout = float(v)
                elif k == "paused":
                    metadata.paused = v.lower() == "true"

        objective = " ".join(objective_lines).strip()
        if not objective:
            if strict:
                raise PlanParseError("Missing or empty ## Objective section")
            objective = ""
        if not modules:
            if strict:
                raise PlanParseError("No tasks found (missing ## Tasks section or task lines)")
            modules = []

        return PlanDocument(
            plan_id=plan_id,
            title=title or "Untitled Plan",
            objective=objective,
            modules=modules,
            metadata=metadata,
            replan_notes=replan_notes,
            conclusion=" ".join(conclusion_lines).strip() or None,
        )


# ── CycleDetector ─────────────────────────────────────────────────────────────

class CycleDetector:
    def detect(self, doc: PlanDocument) -> list[list[str]]:
        adj = {t.task_id: list(t.depends_on) for t in doc.all_tasks()}
        color: dict[str, str] = {tid: "white" for tid in adj}
        path: list[str] = []
        cycles: list[list[str]] = []

        def dfs(node: str) -> None:
            color[node] = "gray"
            path.append(node)
            for nb in adj.get(node, []):
                if nb not in color:
                    continue
                if color[nb] == "gray":
                    cycles.append(path[path.index(nb):] + [nb])
                elif color[nb] == "white":
                    dfs(nb)
            path.pop()
            color[node] = "black"

        for n in list(adj):
            if color[n] == "white":
                dfs(n)
        return cycles


# ── PlanValidator ─────────────────────────────────────────────────────────────

_SNAKE_CASE = re.compile(r"^[a-z][a-z0-9_]*$")


class PlanValidator:
    def validate(self, doc: PlanDocument) -> list[str]:
        errors: list[str] = []
        tasks = doc.all_tasks()
        seen_ids: set[str] = set()

        for task in tasks:
            # Duplicate task_id
            if task.task_id in seen_ids:
                errors.append(f"Duplicate task_id: '{task.task_id}'")
            seen_ids.add(task.task_id)

            # snake_case enforcement
            if not _SNAKE_CASE.match(task.task_id):
                errors.append(
                    f"task_id '{task.task_id}' must be snake_case (lowercase letters, digits, underscores)"
                )

        for task in tasks:
            # Self-reference
            if task.task_id in task.depends_on:
                errors.append(f"Task '{task.task_id}' depends_on itself")
            # Unknown references
            for dep in task.depends_on:
                if dep not in seen_ids:
                    errors.append(
                        f"Task '{task.task_id}' depends_on unknown task_id '{dep}'"
                    )

        # Cycle detection
        detector = CycleDetector()
        cycles = detector.detect(doc)
        for cycle in cycles:
            errors.append(f"Dependency cycle detected: {' → '.join(cycle)}")

        # Objective non-empty
        if not doc.objective.strip():
            errors.append("Objective is empty")

        return errors
