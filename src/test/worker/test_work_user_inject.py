"""Mid-run user inject into running Worker work."""
from __future__ import annotations

import pytest

from worker.work.service import WorkerWorkService, WorkTransitionError
from worker.work.types import WorkIntentSignal, WorkRecord, WorkStatus, utc_now_iso


class _FakeAdapter:
    def __init__(self) -> None:
        self.injected: list[str] = []

    def inject_user_text(self, text: str, *, metadata=None) -> bool:
        self.injected.append(text)
        return True


def test_inject_user_text_requires_running():
    svc = WorkerWorkService(llm_cfg_path="config/llm_core/config.yaml")
    signal = WorkIntentSignal(
        work_id="w1",
        session_id="s1",
        channel_id="c1",
        gen_id="g1",
        question="do work",
        matched_terms=["执行"],
        confidence=0.9,
    )
    record = WorkRecord(signal=signal, status=WorkStatus.pending_confirmation)
    svc._records["w1"] = record
    with pytest.raises(WorkTransitionError):
        svc.inject_user_text("w1", "hello")


def test_inject_user_text_while_running():
    svc = WorkerWorkService(llm_cfg_path="config/llm_core/config.yaml")
    signal = WorkIntentSignal(
        work_id="w2",
        session_id="s2",
        channel_id="c2",
        gen_id="g2",
        question="do work",
        matched_terms=["执行"],
        confidence=0.9,
    )
    record = WorkRecord(signal=signal, status=WorkStatus.running)
    record.started_at = utc_now_iso()
    svc._records["w2"] = record
    adapter = _FakeAdapter()
    svc._adapters["w2"] = adapter
    out = svc.inject_user_text("w2", "改成先列目录")
    assert out["ok"] is True
    assert adapter.injected == ["改成先列目录"]
    assert svc.running_work_for_session("s2") == "w2"
