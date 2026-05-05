from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from plan.document import PlanDocument


class PatchOp(str, Enum):
    skip          = "skip"
    set_params    = "set_params"
    add_task      = "add_task"
    modify_desc   = "modify_desc"
    insert_module = "insert_module"
    pause         = "pause"
    resume        = "resume"
    replan        = "replan"


@dataclass
class HumanPatch:
    op: PatchOp
    task_id: str | None = None
    payload: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"op": self.op.value, "task_id": self.task_id, "payload": self.payload}

    @classmethod
    def from_dict(cls, d: dict) -> HumanPatch:
        return cls(op=PatchOp(d["op"]), task_id=d.get("task_id"), payload=d.get("payload", {}))


class PlanDiff:
    @staticmethod
    def compute(original: PlanDocument, edited: PlanDocument) -> list[HumanPatch]:
        from plan.document import TaskStatus

        patches: list[HumanPatch] = []

        orig_tasks = {t.task_id: t for t in original.all_tasks()}
        edit_tasks = {t.task_id: t for t in edited.all_tasks()}

        for task_id, etask in edit_tasks.items():
            if task_id not in orig_tasks:
                # New task added
                patches.append(HumanPatch(
                    op=PatchOp.add_task,
                    task_id=task_id,
                    payload=etask.to_dict(),
                ))
                continue

            otask = orig_tasks[task_id]

            # Status change
            if etask.status != otask.status:
                if etask.status == TaskStatus.skipped:
                    patches.append(HumanPatch(op=PatchOp.skip, task_id=task_id))
                elif etask.status == TaskStatus.paused:
                    patches.append(HumanPatch(op=PatchOp.pause, task_id=task_id))
                elif etask.status == TaskStatus.pending and otask.status == TaskStatus.paused:
                    patches.append(HumanPatch(op=PatchOp.resume, task_id=task_id))

            # Profile / params change
            changed_params: dict[str, Any] = {}
            if etask.profile != otask.profile:
                changed_params["profile"] = etask.profile
            if etask.max_steps != otask.max_steps:
                changed_params["max_steps"] = etask.max_steps
            for k, v in etask.params.items():
                if otask.params.get(k) != v:
                    changed_params[k] = v
            if changed_params:
                patches.append(HumanPatch(
                    op=PatchOp.set_params,
                    task_id=task_id,
                    payload=changed_params,
                ))

            # Description change
            if etask.description != otask.description:
                patches.append(HumanPatch(
                    op=PatchOp.modify_desc,
                    task_id=task_id,
                    payload={"description": etask.description},
                ))

        # Metadata-level pause / resume
        if edited.metadata.paused and not original.metadata.paused:
            patches.append(HumanPatch(op=PatchOp.pause, task_id=None))
        elif not edited.metadata.paused and original.metadata.paused:
            patches.append(HumanPatch(op=PatchOp.resume, task_id=None))

        # !replan marker in replan_notes
        if any("!replan" in note for note in edited.replan_notes):
            patches.append(HumanPatch(op=PatchOp.replan, task_id=None))

        return patches

    @staticmethod
    def apply(doc: PlanDocument, patches: list[HumanPatch]) -> list[Any]:
        from plan.document import PlanTask, TaskStatus

        new_tasks: list[PlanTask] = []
        for patch in patches:
            if patch.op == PatchOp.skip and patch.task_id:
                doc.skip(patch.task_id)

            elif patch.op == PatchOp.set_params and patch.task_id:
                doc.set_params(patch.task_id, **patch.payload)

            elif patch.op == PatchOp.modify_desc and patch.task_id:
                task = doc.get_task(patch.task_id)
                task.description = patch.payload.get("description", task.description)

            elif patch.op == PatchOp.pause:
                doc.pause()

            elif patch.op == PatchOp.resume:
                doc.resume()

            elif patch.op == PatchOp.add_task:
                task = PlanTask.from_dict(patch.payload)
                module = doc.get_module(task.module)
                if module is None:
                    from plan.document import PlanModule
                    module = PlanModule(name=task.module)
                    doc.modules.append(module)
                module.tasks.append(task)
                new_tasks.append(task)

            elif patch.op == PatchOp.replan:
                # Signal only — handled by orchestrator
                pass

        return new_tasks
