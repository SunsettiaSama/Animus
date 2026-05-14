"""Tests for plan.channel: HumanEditChannel materialize, sync, watch, drain."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent.parent
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import pytest
from agent.flow.channel import HumanEditChannel
from agent.flow.document import PlanParser, TaskStatus
from agent.flow.patch import PatchOp


_MD = """
# Plan: Channel Test

## Objective
Test the human edit channel.

## Tasks

### Module: core
- [ ] **task_a** `profile:minimal`
  Task A.
- [ ] **task_b** `profile:minimal` `depends_on:task_a`
  Task B.
"""


@pytest.fixture
def channel_and_doc(tmp_path):
    doc = PlanParser.parse(_MD)
    ch = HumanEditChannel(str(tmp_path), doc.plan_id, poll_interval=0.1)
    return ch, doc


class TestHumanEditChannel:
    def test_materialize_creates_file(self, channel_and_doc):
        ch, doc = channel_and_doc
        ch.materialize(doc)
        assert ch._shadow_path.exists()

    def test_materialize_content(self, channel_and_doc):
        ch, doc = channel_and_doc
        ch.materialize(doc)
        text = ch._shadow_path.read_text(encoding="utf-8")
        assert "task_a" in text
        assert "task_b" in text

    def test_sync_no_changes_empty_patches(self, channel_and_doc):
        ch, doc = channel_and_doc
        ch.materialize(doc)
        patches = ch.sync(doc)
        assert patches == []

    def test_sync_skip_change(self, channel_and_doc):
        ch, doc = channel_and_doc
        ch.materialize(doc)

        # Manually modify shadow file to mark task_a as skipped
        text = ch._shadow_path.read_text(encoding="utf-8")
        text = text.replace("- [ ] **task_a**", "- [-] **task_a**")
        ch._shadow_path.write_text(text, encoding="utf-8")

        patches = ch.sync(doc)
        ops = [p.op for p in patches]
        assert PatchOp.skip in ops

    def test_sync_lenient_parse_tolerates_partial_edits(self, channel_and_doc):
        ch, doc = channel_and_doc
        ch.materialize(doc)

        # Write a partially malformed shadow (missing objective) — strict=False should tolerate it
        text = ch._shadow_path.read_text(encoding="utf-8")
        text = text.replace("## Objective\nTest the human edit channel.", "")
        ch._shadow_path.write_text(text, encoding="utf-8")

        # Should not raise, just return empty or minimal patches
        patches = ch.sync(doc)
        assert isinstance(patches, list)

    def test_watch_detects_pause_change(self, channel_and_doc):
        ch, doc = channel_and_doc
        ch.materialize(doc)

        async def _run():
            # Modify shadow to add paused: true
            text = ch._shadow_path.read_text(encoding="utf-8")
            # Insert metadata
            text = text.replace("## Tasks", "## Metadata\npaused: true\n\n## Tasks")
            ch._shadow_path.write_text(text, encoding="utf-8")
            # Set mtime to force detection
            import os, time
            ch._last_mtime = 0.0

            watch_task = asyncio.create_task(ch.watch(doc))
            await asyncio.sleep(0.3)
            watch_task.cancel()

        asyncio.get_event_loop().run_until_complete(_run())
        # doc.pause() should have been called by watch
        assert doc.metadata.paused

    def test_drain(self, channel_and_doc):
        ch, doc = channel_and_doc
        from agent.flow.patch import HumanPatch, PatchOp
        ch.patch_queue.put_nowait(HumanPatch(op=PatchOp.skip, task_id="task_a"))
        ch.patch_queue.put_nowait(HumanPatch(op=PatchOp.modify_desc, task_id="task_b", payload={"description": "new"}))

        patches = asyncio.get_event_loop().run_until_complete(ch.drain())
        assert len(patches) == 2
        assert ch.patch_queue.empty()
