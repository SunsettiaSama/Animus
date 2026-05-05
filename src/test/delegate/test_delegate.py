"""Tests for delegate.manager: DelegateManager spawn, await, spawn_all, await_all."""
from __future__ import annotations

import sys
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

SRC = Path(__file__).resolve().parent.parent.parent
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import pytest
from delegate.config import DelegateConfig, DelegateProfile
from delegate.manager import DelegateManager
from delegate.result import DelegateResult


def _make_mgr(run_fn=None) -> DelegateManager:
    """Return a DelegateManager whose runner.run_sync is mocked."""
    cfg = DelegateConfig(llm_cfg_path="fake.yaml", profiles={
        "minimal": DelegateProfile(max_steps=10, system_note=""),
    })
    mgr = DelegateManager(cfg)
    if run_fn is not None:
        mgr._runner.run_sync = run_fn
    return mgr


class TestDelegateManagerDelegate:
    def test_delegate_returns_answer(self):
        mgr = _make_mgr(lambda inst, prof, path: "answer: " + inst)
        result = mgr.delegate("do something", profile="minimal")
        assert result == "answer: do something"

    def test_delegate_unknown_profile_falls_back_to_minimal(self):
        mgr = _make_mgr(lambda inst, prof, path: prof.system_note or "ok")
        result = mgr.delegate("task", profile="does_not_exist")
        assert result == "ok"


class TestDelegateManagerSpawn:
    def test_spawn_returns_agent_id(self):
        mgr = _make_mgr(lambda inst, prof, path: "done")
        agent_id = mgr.spawn("some instruction")
        assert isinstance(agent_id, str) and len(agent_id) > 0

    def test_spawn_completes(self):
        mgr = _make_mgr(lambda inst, prof, path: "result")
        agent_id = mgr.spawn("some instruction")
        result = mgr.await_agent(agent_id, timeout=5.0)
        assert result.status == "done"
        assert result.answer == "result"

    def test_spawn_captures_error(self):
        def _fail(inst, prof, path):
            raise RuntimeError("oops")
        mgr = _make_mgr(_fail)
        agent_id = mgr.spawn("will fail")
        result = mgr.await_agent(agent_id, timeout=5.0)
        assert result.status == "failed"
        assert "oops" in result.error

    def test_spawn_not_found_result(self):
        mgr = _make_mgr(lambda inst, prof, path: "x")
        result = mgr.get_result("nonexistent-id")
        assert result.status == "not_found"

    def test_spawn_timeout(self):
        def _slow(inst, prof, path):
            time.sleep(5.0)
            return "too late"
        mgr = _make_mgr(_slow)
        agent_id = mgr.spawn("slow task")
        result = mgr.await_agent(agent_id, timeout=0.1)
        assert result.status == "timeout"


class TestDelegateManagerSpawnAll:
    def test_spawn_all_returns_ids(self):
        mgr = _make_mgr(lambda inst, prof, path: "ok")
        tasks = [
            {"instruction": "task 1", "profile": "minimal"},
            {"instruction": "task 2", "profile": "minimal"},
        ]
        ids = mgr.spawn_all(tasks)
        assert len(ids) == 2
        assert all(isinstance(i, str) for i in ids)

    def test_await_all_collects_results(self):
        mgr = _make_mgr(lambda inst, prof, path: "done:" + inst)
        tasks = [
            {"instruction": "t1"},
            {"instruction": "t2"},
            {"instruction": "t3"},
        ]
        ids = mgr.spawn_all(tasks)
        results = mgr.await_all(ids, timeout=10.0)
        assert len(results) == 3
        assert all(r.status == "done" for r in results)

    def test_await_all_partial_failure(self):
        call_count = [0]

        def _mixed(inst, prof, path):
            call_count[0] += 1
            if inst == "fail_me":
                raise ValueError("intentional")
            return "ok"

        mgr = _make_mgr(_mixed)
        ids = mgr.spawn_all([
            {"instruction": "ok1"},
            {"instruction": "fail_me"},
            {"instruction": "ok2"},
        ])
        results = mgr.await_all(ids, timeout=10.0)
        statuses = {r.answer or r.error: r.status for r in results}
        assert any(r.status == "failed" for r in results)
        assert any(r.status == "done" for r in results)


class TestBackwardCompat:
    def test_sub_agent_alias(self):
        from delegate.manager import SubAgentManager
        assert SubAgentManager is DelegateManager

    def test_sub_agent_runner_alias(self):
        from delegate.runner import SubAgentRunner, DelegateRunner
        assert SubAgentRunner is DelegateRunner

    def test_sub_agent_config_alias(self):
        from delegate.config import SubAgentConfig, DelegateConfig
        assert SubAgentConfig is DelegateConfig

    def test_sub_agent_profile_alias(self):
        from delegate.config import SubAgentProfile, DelegateProfile
        assert SubAgentProfile is DelegateProfile

    def test_result_class(self):
        from delegate.result import DelegateResult
        r = DelegateResult(agent_id="x", status="done", answer="hi")
        assert r.agent_id == "x"
        assert r.status == "done"
        assert r.answer == "hi"
