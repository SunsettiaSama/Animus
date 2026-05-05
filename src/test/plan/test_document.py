"""Tests for plan.document: PlanTask, PlanDocument, PlanParser, PlanValidator, CycleDetector."""
from __future__ import annotations

import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent.parent
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import pytest
from plan.document import (
    CycleDetector,
    PlanDocument,
    PlanModule,
    PlanParser,
    PlanParseError,
    PlanTask,
    PlanValidator,
    TaskStatus,
)


_PLAN_MD = """
# Plan: Test Plan

## Objective
Build a simple test project.

## Tasks

### Module: setup
- [ ] **init_repo** `profile:minimal` `writes:README.md`
  Initialise the repository.
- [ ] **add_deps** `profile:minimal` `depends_on:init_repo` `writes:requirements.txt`
  Add dependencies.

### Module: build
- [ ] **run_tests** `profile:minimal` `depends_on:add_deps`
  Run the test suite.
"""


class TestPlanParser:
    def test_basic_parse(self):
        doc = PlanParser.parse(_PLAN_MD)
        assert doc.title == "Test Plan"
        assert "simple test project" in doc.objective
        tasks = doc.all_tasks()
        assert len(tasks) == 3
        ids = [t.task_id for t in tasks]
        assert "init_repo" in ids
        assert "add_deps" in ids
        assert "run_tests" in ids

    def test_depends_on_parsed(self):
        doc = PlanParser.parse(_PLAN_MD)
        add_deps = doc.get_task("add_deps")
        assert "init_repo" in add_deps.depends_on

    def test_writes_parsed(self):
        doc = PlanParser.parse(_PLAN_MD)
        init = doc.get_task("init_repo")
        assert "README.md" in init.writes

    def test_strict_missing_objective_raises(self):
        md = "# Plan: X\n\n## Tasks\n\n### Module: m\n- [ ] **t1** `profile:minimal`\n  do it\n"
        with pytest.raises(PlanParseError):
            PlanParser.parse(md, strict=True)

    def test_lenient_missing_objective_ok(self):
        md = "# Plan: X\n\n## Tasks\n\n### Module: m\n- [ ] **t1** `profile:minimal`\n  do it\n"
        doc = PlanParser.parse(md, strict=False)
        assert doc.objective == ""
        assert len(doc.all_tasks()) == 1

    def test_status_markers(self):
        md = """# Plan: S
## Objective
test
## Tasks
### Module: m
- [x] **t_done** `profile:minimal`
  done task
- [!] **t_fail** `profile:minimal`
  failed task
"""
        doc = PlanParser.parse(md)
        assert doc.get_task("t_done").status == TaskStatus.done
        assert doc.get_task("t_fail").status == TaskStatus.failed

    def test_roundtrip_markdown(self):
        doc = PlanParser.parse(_PLAN_MD)
        md2 = doc.to_markdown()
        doc2 = PlanParser.parse(md2)
        ids1 = sorted(t.task_id for t in doc.all_tasks())
        ids2 = sorted(t.task_id for t in doc2.all_tasks())
        assert ids1 == ids2


class TestPlanDocument:
    def test_get_task_missing_raises(self):
        doc = PlanParser.parse(_PLAN_MD)
        with pytest.raises(KeyError):
            doc.get_task("nonexistent")

    def test_get_ready_tasks(self):
        doc = PlanParser.parse(_PLAN_MD)
        ready = [t.task_id for t in doc.get_ready_tasks()]
        assert "init_repo" in ready
        assert "add_deps" not in ready  # depends on init_repo

    def test_skip_cascade(self):
        doc = PlanParser.parse(_PLAN_MD)
        doc.skip("init_repo", cascade=True)
        assert doc.get_task("init_repo").status == TaskStatus.skipped
        assert doc.get_task("add_deps").status == TaskStatus.skipped

    def test_pause_resume(self):
        doc = PlanParser.parse(_PLAN_MD)
        assert not doc.metadata.paused
        doc.pause()
        assert doc.metadata.paused
        assert not doc._resume_event.is_set()
        doc.resume()
        assert not doc.metadata.paused
        assert doc._resume_event.is_set()

    def test_to_dict_from_dict_roundtrip(self):
        doc = PlanParser.parse(_PLAN_MD)
        d = doc.to_dict()
        doc2 = PlanDocument.from_dict(d)
        assert doc2.title == doc.title
        assert len(doc2.all_tasks()) == len(doc.all_tasks())

    def test_writes_field_roundtrip(self):
        doc = PlanParser.parse(_PLAN_MD)
        init = doc.get_task("init_repo")
        assert "README.md" in init.writes
        d = init.to_dict()
        t2 = PlanTask.from_dict(d)
        assert "README.md" in t2.writes

    def test_is_complete_false(self):
        doc = PlanParser.parse(_PLAN_MD)
        assert not doc.is_complete()

    def test_is_complete_true(self):
        doc = PlanParser.parse(_PLAN_MD)
        for t in doc.all_tasks():
            t.status = TaskStatus.done
        assert doc.is_complete()


class TestPlanValidator:
    def test_valid_plan(self):
        doc = PlanParser.parse(_PLAN_MD)
        errors = PlanValidator().validate(doc)
        assert errors == []

    def test_duplicate_task_id(self):
        doc = PlanParser.parse(_PLAN_MD)
        # Manually add duplicate
        dup = PlanTask(task_id="init_repo", description="dup")
        doc.modules[0].tasks.append(dup)
        errors = PlanValidator().validate(doc)
        assert any("Duplicate" in e for e in errors)

    def test_unknown_dep(self):
        doc = PlanParser.parse(_PLAN_MD)
        doc.get_task("init_repo").depends_on = ["nonexistent"]
        errors = PlanValidator().validate(doc)
        assert any("unknown" in e for e in errors)

    def test_self_reference(self):
        doc = PlanParser.parse(_PLAN_MD)
        doc.get_task("init_repo").depends_on = ["init_repo"]
        errors = PlanValidator().validate(doc)
        assert any("itself" in e for e in errors)


class TestCycleDetector:
    def test_no_cycle(self):
        doc = PlanParser.parse(_PLAN_MD)
        cycles = CycleDetector().detect(doc)
        assert cycles == []

    def test_cycle_detected(self):
        doc = PlanParser.parse(_PLAN_MD)
        # Create a cycle: run_tests → add_deps → init_repo → run_tests
        doc.get_task("init_repo").depends_on = ["run_tests"]
        cycles = CycleDetector().detect(doc)
        assert len(cycles) > 0
