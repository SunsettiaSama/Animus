"""Work status transition guards."""
from __future__ import annotations

import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parents[2]
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

import pytest

from worker.work.service import WorkTransitionError, WorkerWorkService
from worker.work.types import WorkIntentSignal, WorkRecord, WorkStatus


def test_invalid_transition_raises():
    svc = WorkerWorkService(llm_cfg_path="config/llm_core/config.yaml")
    record = WorkRecord(
        signal=WorkIntentSignal(
            work_id="w1",
            session_id="s",
            channel_id="c",
            gen_id="g",
            question="你帮我写测试",
        ),
        status=WorkStatus.finished,
    )
    with pytest.raises(WorkTransitionError):
        svc._transition(record, WorkStatus.running)


def test_no_match_returns_none():
    svc = WorkerWorkService(llm_cfg_path="config/llm_core/config.yaml")
    assert svc.maybe_signal("随便聊聊天气", session_id="s", channel_id="c", gen_id="g") is None
