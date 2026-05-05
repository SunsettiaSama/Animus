"""Tests for plan.snapshot: SnapshotStore.save, list, load, rollback."""
from __future__ import annotations

import sys
from pathlib import Path
import tempfile

SRC = Path(__file__).resolve().parent.parent.parent
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import pytest
from plan.document import PlanParser, TaskStatus
from plan.snapshot import SnapshotStore


_MD = """
# Plan: Snap Test

## Objective
Snapshot test plan.

## Tasks

### Module: core
- [ ] **task_a** `profile:minimal`
  Do A.
- [>] **task_b** `profile:minimal` `depends_on:task_a`
  Do B (running).
- [!] **task_c** `profile:minimal` `depends_on:task_a`
  Do C (failed).
"""


@pytest.fixture
def tmp_store(tmp_path):
    doc = PlanParser.parse(_MD)
    store = SnapshotStore(str(tmp_path), doc.plan_id)
    return store, doc


class TestSnapshotStore:
    def test_save_and_list(self, tmp_store):
        store, doc = tmp_store
        snap = store.save(doc, trigger="test", cycle=0)
        snaps = store.list()
        assert len(snaps) == 1
        assert snaps[0].snapshot_id == snap.snapshot_id

    def test_load(self, tmp_store):
        store, doc = tmp_store
        snap = store.save(doc, trigger="test", cycle=0)
        loaded = store.load(snap.snapshot_id)
        assert loaded.all_tasks().__len__() == len(doc.all_tasks())

    def test_rollback_clears_running(self, tmp_store):
        store, doc = tmp_store
        snap = store.save(doc, trigger="pre_run", cycle=0)
        rolled = store.rollback(snap.snapshot_id)
        task_b = rolled.get_task("task_b")
        assert task_b.status == TaskStatus.pending
        assert task_b.execution_ctx is None

    def test_rollback_clears_failed(self, tmp_store):
        store, doc = tmp_store
        snap = store.save(doc, trigger="pre_run", cycle=0)
        rolled = store.rollback(snap.snapshot_id)
        task_c = rolled.get_task("task_c")
        assert task_c.status == TaskStatus.pending
        assert task_c.execution_ctx is None

    def test_rollback_preserves_done(self, tmp_store):
        store, doc = tmp_store
        doc.get_task("task_a").status = TaskStatus.done
        doc.get_task("task_a").result = "all good"
        snap = store.save(doc, trigger="done", cycle=1)
        rolled = store.rollback(snap.snapshot_id)
        assert rolled.get_task("task_a").status == TaskStatus.done
        assert rolled.get_task("task_a").result == "all good"

    def test_multiple_snapshots_sorted(self, tmp_store):
        import time
        store, doc = tmp_store
        store.save(doc, trigger="t1", cycle=0)
        time.sleep(0.01)
        store.save(doc, trigger="t2", cycle=1)
        snaps = store.list()
        assert len(snaps) == 2
        # Most recent first
        assert snaps[0].timestamp >= snaps[1].timestamp
