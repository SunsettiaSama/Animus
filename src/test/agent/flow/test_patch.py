"""Tests for plan.patch: HumanPatch, PlanDiff.compute, PlanDiff.apply."""
from __future__ import annotations

import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent.parent
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from agent.flow.cluster.document import PlanParser, TaskStatus
from agent.flow.cluster.patch import HumanPatch, PatchOp, PlanDiff


_MD = """
# Plan: Patch Test

## Objective
Test patch computation.

## Tasks

### Module: core
- [ ] **task_a** `profile:minimal`
  First task.
- [ ] **task_b** `profile:minimal` `depends_on:task_a`
  Second task.
"""


class TestPlanDiff:
    def _doc(self):
        return PlanParser.parse(_MD)

    def test_no_diff_identical(self):
        doc = self._doc()
        edited = self._doc()
        patches = PlanDiff.compute(doc, edited)
        assert patches == []

    def test_skip_patch(self):
        doc = self._doc()
        edited = self._doc()
        edited.get_task("task_a").status = TaskStatus.skipped
        patches = PlanDiff.compute(doc, edited)
        ops = [p.op for p in patches]
        assert PatchOp.skip in ops
        skip_p = next(p for p in patches if p.op == PatchOp.skip)
        assert skip_p.task_id == "task_a"

    def test_set_params_patch(self):
        doc = self._doc()
        edited = self._doc()
        edited.get_task("task_b").profile = "researcher"
        patches = PlanDiff.compute(doc, edited)
        ops = [p.op for p in patches]
        assert PatchOp.set_params in ops
        sp = next(p for p in patches if p.op == PatchOp.set_params)
        assert sp.payload["profile"] == "researcher"

    def test_modify_desc_patch(self):
        doc = self._doc()
        edited = self._doc()
        edited.get_task("task_a").description = "Updated description"
        patches = PlanDiff.compute(doc, edited)
        ops = [p.op for p in patches]
        assert PatchOp.modify_desc in ops

    def test_pause_patch(self):
        doc = self._doc()
        edited = self._doc()
        edited.metadata.paused = True
        patches = PlanDiff.compute(doc, edited)
        ops = [p.op for p in patches]
        assert PatchOp.pause in ops

    def test_apply_skip(self):
        doc = self._doc()
        patches = [HumanPatch(op=PatchOp.skip, task_id="task_a")]
        PlanDiff.apply(doc, patches)
        assert doc.get_task("task_a").status == TaskStatus.skipped

    def test_apply_set_params(self):
        doc = self._doc()
        patches = [HumanPatch(op=PatchOp.set_params, task_id="task_b", payload={"profile": "analyst"})]
        PlanDiff.apply(doc, patches)
        assert doc.get_task("task_b").profile == "analyst"

    def test_apply_add_task(self):
        doc = self._doc()
        new_task = {
            "task_id": "task_c",
            "description": "New task",
            "module": "core",
            "profile": "minimal",
            "max_steps": None,
            "depends_on": ["task_b"],
            "writes": [],
            "parallel": False,
            "status": "pending",
            "result": None,
            "error": None,
            "params": {},
            "execution_ctx": None,
        }
        patches = [HumanPatch(op=PatchOp.add_task, task_id="task_c", payload=new_task)]
        new = PlanDiff.apply(doc, patches)
        assert len(new) == 1
        assert new[0].task_id == "task_c"
        assert doc.get_task("task_c") is not None

    def test_apply_pause_resume(self):
        doc = self._doc()
        PlanDiff.apply(doc, [HumanPatch(op=PatchOp.pause)])
        assert doc.metadata.paused
        assert not doc._resume_event.is_set()
        PlanDiff.apply(doc, [HumanPatch(op=PatchOp.resume)])
        assert not doc.metadata.paused
        assert doc._resume_event.is_set()
